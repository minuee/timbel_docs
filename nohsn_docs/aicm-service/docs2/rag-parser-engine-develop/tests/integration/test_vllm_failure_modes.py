"""Phase 5 T5.1 — vLLM failure mode tests (Section 6.2 운영 정책 검증).

spec 참조: docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md
  6.2 외부 vLLM Endpoint 운영 정책 + 12.4 vLLM endpoint 운영 검증

검증 항목 (단위 테스트 — 실 endpoint 의존 X, AsyncMock + httpx 예외 주입):
1. endpoint down (httpx.ConnectError) → fallback 동작 + 실패 누적
2. TLS error (httpx.ConnectError "SSL") → graceful fallback (재시도 가능)
3. model mismatch (404 model not found) → non-retryable, 다음 엔드포인트로
4. timeout (httpx.ReadTimeout) → retry 후 fallback
5. health check 의 unhealthy 응답 → alert path 동작 (status 반영)

데이터 driven — 시나리오 리스트 fixture 로 주입. 코드 안에 사례 enum X
(feedback_no_hardcoding_first_principle + feedback_pattern_over_case_enumeration).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import httpx
import pytest

from src.common.exceptions import LLMRoutingError
from src.common.llm.base import LLMRequest, LLMResponse, LLMStreamChunk, LLMTask
from src.common.llm.fallbacks import EndpointSpec


# ---------------------------------------------------------------------------
# Fault scenario taxonomy (Section 6.2 mapping)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaultScenario:
    """One vLLM failure injection — semantic mapping → exception."""
    name: str
    exception: Exception
    expected_retryable: bool   # router._is_retryable_error 의 기대 결과
    expected_fallback_served: bool  # primary 실패 시 fallback 이 응답해야 하는가


def _http_status_exc(status_code: int, message: str) -> Exception:
    """Build an exception that mimics OpenAI SDK error with status_code attribute."""
    exc = Exception(message)
    exc.status_code = status_code  # type: ignore[attr-defined]
    return exc


FAULT_SCENARIOS: list[FaultScenario] = [
    # Section 6.2 — endpoint down (network unreachable / connect refused)
    FaultScenario(
        name="endpoint_down_connect_refused",
        exception=httpx.ConnectError("connect refused"),
        expected_retryable=True,
        expected_fallback_served=True,
    ),
    # Section 6.2 — TLS error (Self-signed CA missing / handshake fail)
    FaultScenario(
        name="tls_handshake_error",
        exception=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"),
        expected_retryable=True,
        expected_fallback_served=True,
    ),
    # Section 6.2 — model mismatch (LUCAS_VLLM_MODEL_REVISION mismatch)
    # 404 는 _is_retryable_error 의 status_code 분기 — None 분기로 떨어져 보수적 retry 됨
    # 다음 endpoint 로 fallback 가능 여부 검증
    FaultScenario(
        name="model_not_found_404",
        exception=_http_status_exc(404, "model not found"),
        expected_retryable=True,  # router 의 보수적 정책
        expected_fallback_served=True,
    ),
    # Section 6.2 — timeout (>60s)
    FaultScenario(
        name="read_timeout_60s",
        exception=httpx.ReadTimeout("read timeout"),
        expected_retryable=True,
        expected_fallback_served=True,
    ),
    # Section 6.2 — 401/403 auth — non-retryable, fallback 로 전환
    FaultScenario(
        name="auth_unauthorized_401",
        exception=_http_status_exc(401, "unauthorized"),
        expected_retryable=False,
        expected_fallback_served=True,
    ),
]


# ---------------------------------------------------------------------------
# Helpers (test_router_fallback.py 패턴 재사용)
# ---------------------------------------------------------------------------


def _make_response(text: str, model: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        model=model,
        usage={"input_tokens": 1, "output_tokens": 1},
        latency_ms=1,
    )


def _make_request() -> LLMRequest:
    return LLMRequest(prompt="vllm-failure-test", max_tokens=8, temperature=0.0)


def _stub_client(label: str, model: str, side_effect: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    if side_effect is not None:
        client.generate = AsyncMock(side_effect=side_effect)
    else:
        client.generate = AsyncMock(return_value=_make_response(f"ok-{label}", model))
    return client


def _stream_raise_before_first(exc: Exception, _model: str):
    async def _g(_req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        raise exc
        yield  # pragma: no cover
    return _g


def _stream_gen(chunks: list[str], model: str):
    async def _g(_req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        for c in chunks:
            yield LLMStreamChunk(text=c, model=model)
    return _g


@pytest.fixture
def router_factory(monkeypatch):
    """Empty router + injected endpoints — circuit breaker / Redis no-op."""
    from src.common.llm import router as router_mod

    def _factory(endpoint_clients):
        router = router_mod.LLMRouter.__new__(router_mod.LLMRouter)
        router._endpoints = list(endpoint_clients)
        router._redis = None

        async def _noop(*_a, **_kw):
            return None

        async def _none_redis():
            return None

        monkeypatch.setattr(router, "_record_stats", _noop, raising=False)
        monkeypatch.setattr(router, "_get_redis", _none_redis, raising=False)

        cb_mock = AsyncMock()
        cb_mock.is_open = AsyncMock(return_value=False)
        cb_mock.record_success = AsyncMock(return_value=None)
        cb_mock.record_failure = AsyncMock(return_value=None)
        cb_mock.get_status = AsyncMock(return_value={"state": "closed", "fail_count": 0, "opened_at": None})
        monkeypatch.setattr(router_mod, "circuit_breaker", cb_mock)

        async def _fast_sleep(_s):
            return None

        monkeypatch.setattr(router_mod.asyncio, "sleep", _fast_sleep)
        return router, cb_mock

    return _factory


# ---------------------------------------------------------------------------
# T5.1.1 — retryability classification (data driven)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", FAULT_SCENARIOS, ids=lambda s: s.name)
def test_fault_classification_matches_policy(scenario: FaultScenario):
    """_is_retryable_error 가 운영 정책과 합치하는지."""
    from src.common.llm.router import _is_retryable_error
    assert _is_retryable_error(scenario.exception) is scenario.expected_retryable


# ---------------------------------------------------------------------------
# T5.1.2 — endpoint failure → fallback 동작 (route)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", FAULT_SCENARIOS, ids=lambda s: s.name)
async def test_primary_fault_falls_back_to_secondary(router_factory, scenario: FaultScenario):
    """primary 가 운영 정책상 fault 일 때 fallback 엔드포인트가 응답을 채운다."""
    primary_spec = EndpointSpec("primary", "https://vllm.primary/v1", "gemma-4")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://gb10:7026/v1", "gemma-4-31b-dense")

    primary = _stub_client("primary", "gemma-4", side_effect=scenario.exception)
    fallback = _stub_client("gb10_31b_dense", "gemma-4-31b-dense")

    router, cb = router_factory([(primary_spec, primary), (fallback_spec, fallback)])

    if scenario.expected_fallback_served:
        resp = await router.route(LLMTask.RAG_GENERATION, _make_request())
        assert resp.text == "ok-gb10_31b_dense"
        fallback.generate.assert_awaited_once()
        cb.record_failure.assert_awaited()  # primary 실패 카운트
    else:
        with pytest.raises(LLMRoutingError):
            await router.route(LLMTask.RAG_GENERATION, _make_request())


# ---------------------------------------------------------------------------
# T5.1.3 — 모든 endpoint 가 같은 fault → LLMRoutingError + 모든 라벨 errors 에
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", FAULT_SCENARIOS, ids=lambda s: s.name)
async def test_all_endpoints_same_fault_raises_routing_error(router_factory, scenario: FaultScenario):
    primary_spec = EndpointSpec("primary", "https://vllm.primary/v1", "gemma-4")
    fb1_spec = EndpointSpec("gb10_31b_dense", "http://gb10:7026/v1", "gemma-4-31b-dense")

    primary = _stub_client("primary", "gemma-4", side_effect=scenario.exception)
    fb1 = _stub_client("gb10_31b_dense", "gemma-4-31b-dense", side_effect=scenario.exception)

    router, _cb = router_factory([(primary_spec, primary), (fb1_spec, fb1)])

    with pytest.raises(LLMRoutingError) as ei:
        await router.route(LLMTask.RAG_GENERATION, _make_request())

    errors = ei.value.details["errors"]
    assert "primary" in errors
    assert "gb10_31b_dense" in errors


# ---------------------------------------------------------------------------
# T5.1.4 — circuit breaker open 시 endpoint 건너뜀
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_open_skips_endpoint_uses_fallback(router_factory):
    """5분 50% 실패 → 30초 open 정책의 동작 — primary circuit open 시 fallback 만."""
    primary_spec = EndpointSpec("primary", "https://vllm.primary/v1", "gemma-4")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://gb10:7026/v1", "gemma-4-31b-dense")

    primary = _stub_client("primary", "gemma-4")
    fallback = _stub_client("gb10_31b_dense", "gemma-4-31b-dense")

    router, cb = router_factory([(primary_spec, primary), (fallback_spec, fallback)])

    async def _is_open(key: str) -> bool:
        return key == "vllm:primary"

    cb.is_open = AsyncMock(side_effect=_is_open)

    resp = await router.route(LLMTask.RAG_GENERATION, _make_request())
    assert resp.text == "ok-gb10_31b_dense"
    primary.generate.assert_not_called()
    fallback.generate.assert_awaited_once()


# ---------------------------------------------------------------------------
# T5.1.5 — health check (provider stats) → state 가 노출되어 alert 가능
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_stats_exposes_circuit_state_for_alerting(router_factory):
    """60초 주기 health ping 의 결과는 get_provider_stats() 에 노출되어야 한다."""
    spec = EndpointSpec("primary", "https://vllm.primary/v1", "gemma-4")
    client = _stub_client("primary", "gemma-4")
    router, cb = router_factory([(spec, client)])

    # health unhealthy → circuit open 상태 노출
    cb.get_status = AsyncMock(return_value={
        "state": "open",
        "fail_count": 12,
        "opened_at": 1716000000.0,
    })

    stats = await router.get_provider_stats()
    assert stats["endpoints"]["primary"]["circuit_breaker"]["state"] == "open"
    assert stats["endpoints"]["primary"]["circuit_breaker"]["fail_count"] == 12
    # legacy top-level summary 도 같은 정보 반영
    assert stats["providers"]["vllm"]["circuit_breaker"]["state"] == "open"


# ---------------------------------------------------------------------------
# T5.1.6 — stream 경로: 첫 chunk 전 TLS/timeout 실패 → fallback, 첫 chunk 후 → 전파
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"),
        httpx.ReadTimeout("stream read timeout"),
        httpx.ConnectError("connection refused"),
    ],
    ids=["tls", "timeout", "down"],
)
async def test_stream_primary_fault_before_first_chunk_falls_back(router_factory, fault):
    primary_spec = EndpointSpec("primary", "https://vllm.primary/v1", "gemma-4")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://gb10:7026/v1", "gemma-4-31b-dense")

    primary = AsyncMock()
    primary.generate_stream = _stream_raise_before_first(fault, "gemma-4")
    fallback = AsyncMock()
    fallback.generate_stream = _stream_gen(["hello ", "world"], "gemma-4-31b-dense")

    router, _cb = router_factory([(primary_spec, primary), (fallback_spec, fallback)])

    collected: list[str] = []
    async for chunk in router.route_stream(LLMTask.RAG_GENERATION, _make_request()):
        collected.append(chunk.text)
    assert collected == ["hello ", "world"]
