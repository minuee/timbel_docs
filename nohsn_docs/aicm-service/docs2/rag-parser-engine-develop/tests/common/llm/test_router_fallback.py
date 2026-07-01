"""LLMRouter GB10 fallback chain 테스트.

B200 (primary) 장애 시 GB10 DGX Spark 로 순차 폴백되는지 검증.
각 테스트는 LLMRouter 인스턴스를 직접 생성해 monkeypatch 로 엔드포인트/circuit 을 주입한다.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest

from src.common.exceptions import LLMRoutingError
from src.common.llm.base import LLMRequest, LLMResponse, LLMStreamChunk, LLMTask
from src.common.llm.fallbacks import (
    DEFAULT_GB10_FALLBACKS,
    EndpointSpec,
    parse_fallbacks,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_response(text: str, model: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        model=model,
        usage={"input_tokens": 1, "output_tokens": 1},
        latency_ms=1,
    )


def _make_request() -> LLMRequest:
    return LLMRequest(prompt="hello", max_tokens=10, temperature=0.0)


def _make_stub_client(label: str, model: str) -> AsyncMock:
    """BaseLLMClient 인터페이스를 흉내내는 AsyncMock."""
    client = AsyncMock()
    client.generate = AsyncMock(return_value=_make_response(f"ok-{label}", model))
    # generate_stream 은 async generator 를 돌려주는 동기 함수로 설정 (기본)
    return client


def _stream_gen(chunks: list[str], model: str):
    async def _g(_req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        for c in chunks:
            yield LLMStreamChunk(text=c, model=model)
    return _g


def _stream_raise_before_first(exc: Exception, model: str):
    async def _g(_req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        raise exc
        yield  # pragma: no cover
    return _g


def _stream_one_then_raise(chunk: str, exc: Exception, model: str):
    async def _g(_req: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        yield LLMStreamChunk(text=chunk, model=model)
        raise exc
    return _g


@pytest.fixture
def router_with_endpoints(monkeypatch):
    """LLMRouter 인스턴스를 빈 상태로 만들고 fake endpoints 주입.

    - circuit_breaker 의 is_open/record_* 를 AsyncMock 으로 patch
    - _record_stats / _get_redis 는 no-op 으로 patch (Redis 의존성 제거)
    """
    from src.common.llm import router as router_mod

    def _factory(endpoint_clients: list[tuple[EndpointSpec, AsyncMock]]):
        router = router_mod.LLMRouter.__new__(router_mod.LLMRouter)
        router._endpoints = list(endpoint_clients)
        router._redis = None

        async def _noop_stats(*_a, **_kw) -> None:
            return None

        async def _none_redis() -> None:
            return None

        monkeypatch.setattr(router, "_record_stats", _noop_stats, raising=False)
        monkeypatch.setattr(router, "_get_redis", _none_redis, raising=False)

        # Circuit breaker — 기본은 closed (is_open=False)
        cb_mock = AsyncMock()
        cb_mock.is_open = AsyncMock(return_value=False)
        cb_mock.record_success = AsyncMock(return_value=None)
        cb_mock.record_failure = AsyncMock(return_value=None)
        monkeypatch.setattr(router_mod, "circuit_breaker", cb_mock)

        # asyncio.sleep 을 순간-반환으로 패치 (backoff 테스트 시간 단축)
        async def _fast_sleep(_s: float) -> None:
            return None

        monkeypatch.setattr(router_mod.asyncio, "sleep", _fast_sleep)

        return router, cb_mock

    return _factory


# ──────────────────────────────────────────────────────────────────────────────
# parse_fallbacks 단위 테스트
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_fallbacks_empty_returns_empty():
    assert parse_fallbacks("") == []
    assert parse_fallbacks("   ") == []


def test_parse_fallbacks_auto_returns_three_gb10():
    specs = parse_fallbacks("auto")
    assert len(specs) == 3
    assert specs[0].label == "gb10_31b_dense"
    assert specs[1].label == "gb10_26b_moe"
    assert specs[2].label == "gb10_e4b"
    # 기본 상수와 동일
    assert specs == DEFAULT_GB10_FALLBACKS


def test_parse_fallbacks_json_explicit():
    raw = '[{"label":"x","url":"http://y/v1","model":"z"}]'
    specs = parse_fallbacks(raw)
    assert len(specs) == 1
    assert specs[0] == EndpointSpec("x", "http://y/v1", "z")


def test_parse_fallbacks_invalid_json_returns_empty():
    assert parse_fallbacks("not json") == []
    # dict (list 아님) 도 빈 리스트
    assert parse_fallbacks('{"label": "x"}') == []


def test_parse_fallbacks_json_skips_malformed_entries():
    raw = '[{"label":"ok","url":"http://a","model":"m"}, {"bad":"entry"}]'
    specs = parse_fallbacks(raw)
    assert len(specs) == 1
    assert specs[0].label == "ok"


# ──────────────────────────────────────────────────────────────────────────────
# route() 폴백 체인 테스트
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_primary_success_no_fallback_call(router_with_endpoints, caplog):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = _make_stub_client("primary", "primary-model")
    fallback = _make_stub_client("gb10_31b_dense", "fb-model")

    router, _cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    caplog.set_level("WARNING")
    response = await router.route(LLMTask.RAG_GENERATION, _make_request())

    assert response.text == "ok-primary"
    primary.generate.assert_awaited_once()
    fallback.generate.assert_not_called()
    # llm_fallback_served 로그가 없어야 함
    assert not any("llm_fallback_served" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_primary_fails_fallback_serves_request(router_with_endpoints, capsys):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = _make_stub_client("primary", "primary-model")
    primary.generate = AsyncMock(side_effect=httpx.ConnectError("primary down"))
    fallback = _make_stub_client("gb10_31b_dense", "fb-model")

    router, _cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    response = await router.route(LLMTask.RAG_GENERATION, _make_request())

    assert response.text == "ok-gb10_31b_dense"
    # primary 는 MAX_RETRIES+1 번 시도됨
    assert primary.generate.await_count >= 2
    fallback.generate.assert_awaited_once()

    # structlog stdout 에 llm_fallback_served + label 포함되는지 확인
    captured = capsys.readouterr()
    assert "llm_fallback_served" in captured.out
    assert "gb10_31b_dense" in captured.out


@pytest.mark.asyncio
async def test_all_endpoints_fail_raises_routing_error(router_with_endpoints):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fb1_spec = EndpointSpec("gb10_31b_dense", "http://fb1/v1", "fb1-model")
    fb2_spec = EndpointSpec("gb10_26b_moe", "http://fb2/v1", "fb2-model")
    err = httpx.ConnectError("down")

    primary = _make_stub_client("primary", "p")
    primary.generate = AsyncMock(side_effect=err)
    fb1 = _make_stub_client("gb10_31b_dense", "f1")
    fb1.generate = AsyncMock(side_effect=err)
    fb2 = _make_stub_client("gb10_26b_moe", "f2")
    fb2.generate = AsyncMock(side_effect=err)

    router, _cb = router_with_endpoints([
        (primary_spec, primary),
        (fb1_spec, fb1),
        (fb2_spec, fb2),
    ])

    with pytest.raises(LLMRoutingError) as ei:
        await router.route(LLMTask.RAG_GENERATION, _make_request())

    errors = ei.value.details["errors"]
    assert "primary" in errors
    assert "gb10_31b_dense" in errors
    assert "gb10_26b_moe" in errors


@pytest.mark.asyncio
async def test_circuit_open_skips_endpoint(router_with_endpoints):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = _make_stub_client("primary", "primary-model")
    fallback = _make_stub_client("gb10_31b_dense", "fb-model")

    router, cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    # primary 만 circuit OPEN
    async def _is_open(key: str) -> bool:
        return key == "vllm:primary"

    cb.is_open = AsyncMock(side_effect=_is_open)

    response = await router.route(LLMTask.RAG_GENERATION, _make_request())

    assert response.text == "ok-gb10_31b_dense"
    primary.generate.assert_not_called()
    fallback.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_endpoints_configured_raises():
    from src.common.llm import router as router_mod

    router = router_mod.LLMRouter.__new__(router_mod.LLMRouter)
    router._endpoints = []
    router._redis = None

    with pytest.raises(LLMRoutingError):
        await router.route(LLMTask.RAG_GENERATION, _make_request())


# ──────────────────────────────────────────────────────────────────────────────
# route_stream() 테스트
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_endpoint_fail_before_first_chunk_tries_next(router_with_endpoints):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")

    primary = AsyncMock()
    primary.generate_stream = _stream_raise_before_first(
        httpx.ConnectError("primary stream down"), "primary-model"
    )
    fallback = AsyncMock()
    fallback.generate_stream = _stream_gen(["hello ", "world"], "fb-model")

    router, _cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    collected: list[str] = []
    async for chunk in router.route_stream(LLMTask.RAG_GENERATION, _make_request()):
        collected.append(chunk.text)

    assert collected == ["hello ", "world"]


@pytest.mark.asyncio
async def test_stream_endpoint_fail_after_first_chunk_propagates(router_with_endpoints):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")

    primary = AsyncMock()
    primary.generate_stream = _stream_one_then_raise(
        "partial ", httpx.ConnectError("mid-stream fail"), "primary-model"
    )
    fallback = AsyncMock()
    fallback.generate_stream = _stream_gen(["never-served"], "fb-model")

    router, _cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    collected: list[str] = []
    with pytest.raises(LLMRoutingError):
        async for chunk in router.route_stream(LLMTask.RAG_GENERATION, _make_request()):
            collected.append(chunk.text)

    # 첫 chunk 는 consumer 로 전달되었어야 함
    assert collected == ["partial "]


@pytest.mark.asyncio
async def test_stream_all_endpoints_fail_raises(router_with_endpoints):
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")

    primary = AsyncMock()
    primary.generate_stream = _stream_raise_before_first(
        httpx.ConnectError("p down"), "primary-model"
    )
    fallback = AsyncMock()
    fallback.generate_stream = _stream_raise_before_first(
        httpx.ConnectError("fb down"), "fb-model"
    )

    router, _cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    with pytest.raises(LLMRoutingError):
        async for _chunk in router.route_stream(LLMTask.RAG_GENERATION, _make_request()):
            pass


# ──────────────────────────────────────────────────────────────────────────────
# route_vision() smoke
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vision_primary_fails_fallback_serves(router_with_endpoints):
    from src.common.llm.base import LLMVisionRequest

    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = AsyncMock()
    primary.generate_vision = AsyncMock(side_effect=httpx.ConnectError("vision down"))
    fallback = AsyncMock()
    fallback.generate_vision = AsyncMock(return_value=_make_response("vision-ok", "fb-model"))

    router, _cb = router_with_endpoints([(primary_spec, primary), (fallback_spec, fallback)])

    req = LLMVisionRequest(prompt="describe", images=[b"fake-bytes"], max_tokens=10)
    response = await router.route_vision(LLMTask.VISION_OCR, req)

    assert response.text == "vision-ok"
    assert primary.generate_vision.await_count >= 1
    fallback.generate_vision.assert_awaited_once()
