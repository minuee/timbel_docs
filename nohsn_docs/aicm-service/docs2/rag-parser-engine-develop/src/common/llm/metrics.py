"""LLM 라우터 Prometheus 메트릭 + 폴백 digest 로그.

Task 31 — Fallback 관측(Observability) 레이어.

LLMRouter 가 엔드포인트 체인을 통해 요청을 처리할 때:
- success/fail 카운터
- non-primary 엔드포인트가 서빙한 fallback 카운터
- 레이턴시 히스토그램
- 회로 차단기(circuit breaker) 게이지

모든 메트릭은 `aicm_llm_*` 접두사를 따른다 (기존 src/api/metrics.py 패턴과 일치).
`prometheus_client` 가 설치되어 있지 않은 환경(테스트 전용 slim venv 등) 에서도
import 가 실패하지 않도록 방어적 import 를 유지한다.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.common.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    pass

log = get_logger(__name__)


try:
    from prometheus_client import Counter, Gauge, Histogram
except Exception:  # pragma: no cover - 방어적
    Counter = None  # type: ignore[assignment]
    Gauge = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Prometheus 메트릭 정의
# ---------------------------------------------------------------------------

# 기존 src/api/metrics.py 와 **별개**의 접두사를 사용한다 (`aicm_llm_request_*`).
# 기존 `aicm_llm_requests_total{model,task,status}` 는 API 계층에서 추적하는 반면,
# 여기서는 **엔드포인트(label)** 단위 폴백 체인 관점에서 추적한다.

if Counter is not None:
    LLM_REQUEST_TOTAL = Counter(
        "aicm_llm_request_total",
        "LLM 엔드포인트 요청 총 수 (endpoint, outcome)",
        ["endpoint", "outcome"],
    )

    LLM_FALLBACK_SERVED_TOTAL = Counter(
        "aicm_llm_fallback_served_total",
        "비-primary 엔드포인트가 요청을 서빙한 횟수",
        ["endpoint"],
    )

    LLM_REQUEST_DURATION = Histogram(
        "aicm_llm_request_duration_seconds",
        "LLM 엔드포인트 요청 레이턴시 (endpoint)",
        ["endpoint"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
    )

    LLM_CIRCUIT_OPEN = Gauge(
        "aicm_llm_circuit_open",
        "LLM 엔드포인트의 circuit breaker 가 open 상태인지 여부 (1=open, 0=closed)",
        ["endpoint"],
    )
else:  # pragma: no cover
    LLM_REQUEST_TOTAL = None  # type: ignore[assignment]
    LLM_FALLBACK_SERVED_TOTAL = None  # type: ignore[assignment]
    LLM_REQUEST_DURATION = None  # type: ignore[assignment]
    LLM_CIRCUIT_OPEN = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def record_request(endpoint: str, outcome: str, duration_seconds: float | None = None) -> None:
    """LLM 요청 결과 기록 (성공/실패 카운터 + 레이턴시).

    Args:
        endpoint: 엔드포인트 라벨 (`primary`, `gb10_31b_dense`, ...).
        outcome: `success` | `fail`.
        duration_seconds: 요청에 걸린 전체 시간. None 이면 히스토그램 기록 생략.
    """
    if LLM_REQUEST_TOTAL is None:
        return
    try:
        LLM_REQUEST_TOTAL.labels(endpoint=endpoint, outcome=outcome).inc()
        if duration_seconds is not None and LLM_REQUEST_DURATION is not None:
            LLM_REQUEST_DURATION.labels(endpoint=endpoint).observe(duration_seconds)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("llm_metric_record_failed", endpoint=endpoint, error=str(exc))


def record_fallback_served(endpoint: str) -> None:
    """비-primary 엔드포인트가 요청을 서빙한 사건 기록."""
    if LLM_FALLBACK_SERVED_TOTAL is None:
        return
    try:
        LLM_FALLBACK_SERVED_TOTAL.labels(endpoint=endpoint).inc()
    except Exception as exc:  # pragma: no cover
        log.warning("llm_fallback_metric_record_failed", endpoint=endpoint, error=str(exc))


def set_circuit_open(endpoint: str, is_open: bool) -> None:
    """특정 엔드포인트의 circuit breaker 상태 게이지 갱신."""
    if LLM_CIRCUIT_OPEN is None:
        return
    try:
        LLM_CIRCUIT_OPEN.labels(endpoint=endpoint).set(1 if is_open else 0)
    except Exception as exc:  # pragma: no cover
        log.warning("llm_circuit_gauge_failed", endpoint=endpoint, error=str(exc))


# ---------------------------------------------------------------------------
# 폴백 Summary digest (5분 주기)
# ---------------------------------------------------------------------------


DIGEST_INTERVAL_SECONDS = 300
"""Summary digest 출력 주기(초)."""


async def _compute_digest_payload() -> dict[str, Any]:
    """현재 엔드포인트 상태를 digest payload 로 집계.

    router.get_provider_stats() 를 호출해 Redis 기반 success/fail 통계를 가져오고,
    primary_success_rate, 총 fallback_served_count, 엔드포인트별 상태를 요약한다.
    """
    from src.common.llm.router import llm_router

    try:
        stats = await llm_router.get_provider_stats()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc)}

    endpoints_info = stats.get("endpoints", {})
    primary_info = endpoints_info.get("primary", {})
    primary_tasks = primary_info.get("tasks", {})

    primary_success = sum(t.get("success", 0) for t in primary_tasks.values())
    primary_fail = sum(t.get("fail", 0) for t in primary_tasks.values())
    primary_total = primary_success + primary_fail
    primary_rate = round(primary_success / primary_total, 3) if primary_total > 0 else None

    # fallback served count = 모든 non-primary 엔드포인트의 success 합
    fallbacks_served = 0
    endpoints_status: dict[str, dict[str, Any]] = {}
    for label, info in endpoints_info.items():
        cb = info.get("circuit_breaker", {})
        tasks = info.get("tasks", {})
        success = sum(t.get("success", 0) for t in tasks.values())
        fail = sum(t.get("fail", 0) for t in tasks.values())
        endpoints_status[label] = {
            "state": cb.get("state", "unknown"),
            "success": success,
            "fail": fail,
        }
        if label != "primary":
            fallbacks_served += success

    return {
        "primary_success_rate": primary_rate,
        "fallbacks_served_count": fallbacks_served,
        "endpoints_status": endpoints_status,
    }


async def _digest_loop() -> None:
    """DIGEST_INTERVAL_SECONDS 마다 llm_fallback_summary 로그 이벤트 발행."""
    while True:
        try:
            await asyncio.sleep(DIGEST_INTERVAL_SECONDS)
            payload = await _compute_digest_payload()
            log.info("llm_fallback_summary", **payload)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("llm_fallback_summary_error", error=str(exc))


_digest_task: asyncio.Task[None] | None = None


def start_digest_task() -> asyncio.Task[None] | None:
    """API 시작 시 호출 — 주기적 digest 로그 태스크 기동.

    이미 실행 중인 태스크가 있으면 그대로 반환한다.
    이벤트 루프가 없으면 None.
    """
    global _digest_task
    if _digest_task is not None and not _digest_task.done():
        return _digest_task
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:  # pragma: no cover
        return None
    _digest_task = loop.create_task(_digest_loop(), name="llm_fallback_digest")
    log.info("llm_fallback_digest_started", interval_seconds=DIGEST_INTERVAL_SECONDS)
    return _digest_task


def stop_digest_task() -> None:
    """shutdown 시 호출."""
    global _digest_task
    if _digest_task is not None and not _digest_task.done():
        _digest_task.cancel()
    _digest_task = None
