"""Integration Layer Prometheus 메트릭 정의.

모든 외부 연동 관련 메트릭을 한 곳에서 정의하여 일관성을 유지한다.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# External API
# ---------------------------------------------------------------------------

EXTERNAL_API_REQUESTS_TOTAL = Counter(
    "aicm_external_api_requests_total",
    "외부 API 요청 총 수",
    ["endpoint", "api_key_name"],
)

EXTERNAL_API_DURATION_SECONDS = Histogram(
    "aicm_external_api_duration_seconds",
    "외부 API 응답 시간 (초)",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

WEBHOOK_DISPATCHES_TOTAL = Counter(
    "aicm_webhook_dispatches_total",
    "Webhook 발행 총 수",
    ["event", "status"],
)

# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

SYNC_OPERATIONS_TOTAL = Counter(
    "aicm_sync_operations_total",
    "외부 문서 동기화 작업 총 수",
    ["source_type", "status"],
)

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_STATE = Gauge(
    "aicm_circuit_breaker_state",
    "Circuit breaker 상태 (0=closed, 1=open, 2=half_open)",
    ["name"],
)

# ---------------------------------------------------------------------------
# Response Cache
# ---------------------------------------------------------------------------

CACHE_HIT_TOTAL = Counter(
    "aicm_cache_hit_total",
    "캐시 히트 총 수",
    ["cache_type"],
)

CACHE_MISS_TOTAL = Counter(
    "aicm_cache_miss_total",
    "캐시 미스 총 수",
    ["cache_type"],
)


def update_circuit_breaker_metrics() -> None:
    """모든 등록된 circuit breaker의 상태를 Gauge에 반영.

    주기적으로 호출하거나, 상태 전환 시 호출한다.
    """
    from src.integration.resilience.circuit_breaker import CircuitState, all_breakers

    state_map = {
        CircuitState.CLOSED: 0,
        CircuitState.OPEN: 1,
        CircuitState.HALF_OPEN: 2,
    }
    for name, breaker in all_breakers().items():
        CIRCUIT_BREAKER_STATE.labels(name=name).set(state_map.get(breaker.state, 0))
