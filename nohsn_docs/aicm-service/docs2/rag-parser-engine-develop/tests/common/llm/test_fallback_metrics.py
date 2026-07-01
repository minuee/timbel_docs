"""LLM 폴백 Prometheus 메트릭 테스트 (Task 31).

- route() 성공 시 aicm_llm_request_total{outcome="success"} 증가
- 폴백 서빙 시 aicm_llm_fallback_served_total 증가
- circuit open 시 aicm_llm_circuit_open gauge 가 1 로 설정
- digest payload 구조 검증
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from src.common.llm import metrics as llm_metrics
from src.common.llm.base import LLMRequest, LLMResponse, LLMTask
from src.common.llm.fallbacks import EndpointSpec


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
    client = AsyncMock()
    client.generate = AsyncMock(return_value=_make_response(f"ok-{label}", model))
    return client


def _counter_value(counter, **labels) -> float:
    """prometheus_client Counter 의 현재 값을 label 조합으로 읽는다."""
    if counter is None:
        return 0.0
    return counter.labels(**labels)._value.get()


def _gauge_value(gauge, **labels) -> float:
    if gauge is None:
        return 0.0
    return gauge.labels(**labels)._value.get()


@pytest.fixture
def router_factory(monkeypatch):
    """공용 router factory — fallback 테스트와 동일한 구조."""
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

        cb_mock = AsyncMock()
        cb_mock.is_open = AsyncMock(return_value=False)
        cb_mock.record_success = AsyncMock(return_value=None)
        cb_mock.record_failure = AsyncMock(return_value=None)
        monkeypatch.setattr(router_mod, "circuit_breaker", cb_mock)

        async def _fast_sleep(_s: float) -> None:
            return None

        monkeypatch.setattr(router_mod.asyncio, "sleep", _fast_sleep)

        return router, cb_mock

    return _factory


@pytest.mark.asyncio
async def test_route_success_increments_request_total(router_factory):
    """Primary 성공 → aicm_llm_request_total{endpoint=primary,outcome=success} 증가."""
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    primary = _make_stub_client("primary", "primary-model")

    router, _cb = router_factory([(primary_spec, primary)])

    before = _counter_value(
        llm_metrics.LLM_REQUEST_TOTAL, endpoint="primary", outcome="success"
    )

    await router.route(LLMTask.RAG_GENERATION, _make_request())

    after = _counter_value(
        llm_metrics.LLM_REQUEST_TOTAL, endpoint="primary", outcome="success"
    )
    assert after - before == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_route_fallback_increments_fallback_served(router_factory):
    """Primary 실패 → fallback 이 서빙 → fallback_served_total 증가."""
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = _make_stub_client("primary", "primary-model")
    primary.generate = AsyncMock(side_effect=httpx.ConnectError("down"))
    fallback = _make_stub_client("gb10_31b_dense", "fb-model")

    router, _cb = router_factory([(primary_spec, primary), (fallback_spec, fallback)])

    before_fb = _counter_value(
        llm_metrics.LLM_FALLBACK_SERVED_TOTAL, endpoint="gb10_31b_dense"
    )
    before_fail = _counter_value(
        llm_metrics.LLM_REQUEST_TOTAL, endpoint="primary", outcome="fail"
    )

    await router.route(LLMTask.RAG_GENERATION, _make_request())

    after_fb = _counter_value(
        llm_metrics.LLM_FALLBACK_SERVED_TOTAL, endpoint="gb10_31b_dense"
    )
    after_fail = _counter_value(
        llm_metrics.LLM_REQUEST_TOTAL, endpoint="primary", outcome="fail"
    )
    assert after_fb - before_fb == pytest.approx(1.0)
    assert after_fail - before_fail == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_circuit_open_updates_gauge(router_factory):
    """Circuit OPEN 판정 시 aicm_llm_circuit_open 이 1 로 설정."""
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = _make_stub_client("primary", "primary-model")
    fallback = _make_stub_client("gb10_31b_dense", "fb-model")

    router, cb = router_factory([(primary_spec, primary), (fallback_spec, fallback)])

    # primary 만 circuit OPEN
    async def _is_open(key: str) -> bool:
        return key == "vllm:primary"

    cb.is_open = AsyncMock(side_effect=_is_open)

    await router.route(LLMTask.RAG_GENERATION, _make_request())

    gauge_primary = _gauge_value(llm_metrics.LLM_CIRCUIT_OPEN, endpoint="primary")
    gauge_fallback = _gauge_value(
        llm_metrics.LLM_CIRCUIT_OPEN, endpoint="gb10_31b_dense"
    )
    assert gauge_primary == 1.0
    assert gauge_fallback == 0.0


@pytest.mark.asyncio
async def test_digest_payload_structure(router_factory, monkeypatch):
    """_compute_digest_payload 가 primary_success_rate / fallbacks_served_count / endpoints_status 를 담는다."""
    primary_spec = EndpointSpec("primary", "http://primary/v1", "primary-model")
    fallback_spec = EndpointSpec("gb10_31b_dense", "http://fb/v1", "fb-model")
    primary = _make_stub_client("primary", "primary-model")
    fallback = _make_stub_client("gb10_31b_dense", "fb-model")

    router, _cb = router_factory([(primary_spec, primary), (fallback_spec, fallback)])

    # llm_router 싱글턴을 factory 결과로 교체
    from src.common.llm import metrics as metrics_mod
    from src.common.llm import router as router_mod

    monkeypatch.setattr(router_mod, "llm_router", router)

    # get_provider_stats 가 예측 가능한 값을 반환하도록 간단히 patch
    async def _stub_stats() -> dict:
        return {
            "endpoints": {
                "primary": {
                    "url": "http://primary/v1",
                    "model": "primary-model",
                    "circuit_breaker": {"state": "closed"},
                    "tasks": {"rag_generation": {"success": 80, "fail": 20}},
                },
                "gb10_31b_dense": {
                    "url": "http://fb/v1",
                    "model": "fb-model",
                    "circuit_breaker": {"state": "closed"},
                    "tasks": {"rag_generation": {"success": 5, "fail": 0}},
                },
            }
        }

    monkeypatch.setattr(router, "get_provider_stats", _stub_stats)

    payload = await metrics_mod._compute_digest_payload()
    assert set(payload.keys()) >= {
        "primary_success_rate",
        "fallbacks_served_count",
        "endpoints_status",
    }
    assert payload["primary_success_rate"] == pytest.approx(0.8)
    assert payload["fallbacks_served_count"] == 5
    assert payload["endpoints_status"]["primary"]["state"] == "closed"
    assert payload["endpoints_status"]["gb10_31b_dense"]["success"] == 5
