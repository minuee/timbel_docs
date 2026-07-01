"""검색 Prometheus 메트릭."""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

from prometheus_client import Counter, Histogram

from src.common.logging import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

SEARCH_REQUESTS_TOTAL = Counter(
    "aicm_search_engine_requests_total",
    "검색 엔진 요청 총 수 (모드/캐시 구분)",
    labelnames=["mode", "cached"],
)

SEARCH_CACHE_HITS_TOTAL = Counter(
    "aicm_search_engine_cache_hits_total",
    "검색 엔진 캐시 히트 수",
)

SEARCH_CACHE_MISSES_TOTAL = Counter(
    "aicm_search_engine_cache_misses_total",
    "검색 엔진 캐시 미스 수",
)

RERANKER_CALLS_TOTAL = Counter(
    "aicm_reranker_calls_total",
    "리랭커 호출 수",
)

SEARCH_NO_RESULTS_TOTAL = Counter(
    "aicm_search_no_results_total",
    "검색 결과 없음 수",
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

SEARCH_DURATION_SECONDS = Histogram(
    "aicm_search_engine_duration_seconds",
    "검색 엔진 단계별 소요 시간 (초)",
    labelnames=["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

LLM_RAG_DURATION_SECONDS = Histogram(
    "aicm_llm_rag_duration_seconds",
    "LLM RAG 응답 생성 소요 시간 (초)",
    labelnames=["model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def track_search_stage(stage: str) -> Callable[[F], F]:
    """
    검색 단계별 레이턴시 자동 계측 데코레이터.

    사용 예:
        @track_search_stage("dense")
        async def search_dense(...):
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                elapsed = time.monotonic() - start
                SEARCH_DURATION_SECONDS.labels(stage=stage).observe(elapsed)

        return wrapper  # type: ignore[return-value]

    return decorator


def record_search_request(mode: str, cached: bool) -> None:
    """검색 요청 메트릭 기록."""
    SEARCH_REQUESTS_TOTAL.labels(mode=mode, cached=str(cached).lower()).inc()


def record_cache_hit() -> None:
    """캐시 히트 메트릭 기록."""
    SEARCH_CACHE_HITS_TOTAL.inc()


def record_cache_miss() -> None:
    """캐시 미스 메트릭 기록."""
    SEARCH_CACHE_MISSES_TOTAL.inc()


def record_reranker_call() -> None:
    """리랭커 호출 메트릭 기록."""
    RERANKER_CALLS_TOTAL.inc()


def record_no_results() -> None:
    """검색 결과 없음 메트릭 기록."""
    SEARCH_NO_RESULTS_TOTAL.inc()


def observe_search_duration(stage: str, duration_seconds: float) -> None:
    """검색 단계별 소요 시간 수동 기록."""
    SEARCH_DURATION_SECONDS.labels(stage=stage).observe(duration_seconds)


def observe_llm_rag_duration(model: str, duration_seconds: float) -> None:
    """LLM RAG 응답 생성 소요 시간 기록."""
    LLM_RAG_DURATION_SECONDS.labels(model=model).observe(duration_seconds)
