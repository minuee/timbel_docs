"""Prometheus 메트릭 레지스트리 및 미들웨어.

전체 AICM 서비스의 Prometheus 메트릭을 수집한다.
- API 요청 카운트, 지연시간, 오류
- 검색, 파이프라인, LLM 커스텀 메트릭 (다른 모듈에서 import 가능)
- 캐시 히트/미스, 감사 이벤트, 테넌트별 메트릭
"""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Match

from src.common.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 공용 레지스트리 (prometheus_client 기본 레지스트리 사용)
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry()


# ---------------------------------------------------------------------------
# API 요청 메트릭
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "aicm_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

REQUEST_DURATION = Histogram(
    "aicm_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

REQUEST_ERRORS = Counter(
    "aicm_http_request_errors_total",
    "Total HTTP request errors (4xx/5xx)",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

REQUESTS_IN_PROGRESS = Gauge(
    "aicm_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# 검색 메트릭
# ---------------------------------------------------------------------------

SEARCH_REQUESTS = Counter(
    "aicm_search_requests_total",
    "Total search requests",
    ["search_type", "tenant_id"],
    registry=REGISTRY,
)

SEARCH_LATENCY = Histogram(
    "aicm_search_latency_seconds",
    "검색 요청 레이턴시 (모드별)",
    ["mode"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    registry=REGISTRY,
)

SEARCH_DURATION = Histogram(
    "aicm_search_duration_seconds",
    "Search request duration in seconds",
    ["stage"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

SEARCH_CACHE_HITS = Counter(
    "aicm_search_cache_hits_total",
    "Total search cache hits",
    registry=REGISTRY,
)

SEARCH_CACHE_MISSES = Counter(
    "aicm_search_cache_misses_total",
    "Total search cache misses",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# 캐시 메트릭 (범용 — cache_type 레이블로 구분)
# ---------------------------------------------------------------------------

CACHE_HITS_TOTAL = Counter(
    "aicm_cache_hits_total",
    "캐시 히트 총 수 (캐시 유형별)",
    ["cache_type"],
    registry=REGISTRY,
)

CACHE_MISSES_TOTAL = Counter(
    "aicm_cache_misses_total",
    "캐시 미스 총 수 (캐시 유형별)",
    ["cache_type"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# 감사 이벤트 메트릭
# ---------------------------------------------------------------------------

AUDIT_EVENTS_TOTAL = Counter(
    "aicm_audit_events_total",
    "감사 이벤트 총 수 (액션별, 리소스 유형별)",
    ["action", "resource_type"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# 파이프라인 메트릭
# ---------------------------------------------------------------------------

PIPELINE_DOCUMENTS_PROCESSED = Counter(
    "aicm_pipeline_documents_processed_total",
    "Total documents processed by pipeline",
    ["format", "status"],
    registry=REGISTRY,
)

PIPELINE_PROCESSING_DURATION = Histogram(
    "aicm_pipeline_processing_duration_seconds",
    "Document processing duration in seconds",
    ["stage"],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    registry=REGISTRY,
)

PIPELINE_QUEUE_DEPTH = Gauge(
    "aicm_pipeline_queue_depth",
    "Current pipeline queue depth",
    ["topic"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# LLM 메트릭
# ---------------------------------------------------------------------------

LLM_REQUESTS = Counter(
    "aicm_llm_requests_total",
    "Total LLM API requests",
    ["model", "task", "status"],
    registry=REGISTRY,
)

LLM_DURATION = Histogram(
    "aicm_llm_request_duration_seconds",
    "LLM request duration in seconds",
    ["model"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

LLM_TOKENS = Counter(
    "aicm_llm_tokens_total",
    "Total LLM tokens used",
    ["model", "direction"],
    registry=REGISTRY,
)

LLM_COST = Counter(
    "aicm_llm_estimated_cost_usd",
    "Estimated LLM API cost in USD",
    ["model"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# 인프라 메트릭 (게이지)
# ---------------------------------------------------------------------------

DB_POOL_SIZE = Gauge(
    "aicm_db_pool_size",
    "Database connection pool size",
    registry=REGISTRY,
)

DB_POOL_CHECKED_OUT = Gauge(
    "aicm_db_pool_checked_out",
    "Database connections currently checked out",
    registry=REGISTRY,
)

APP_UPTIME = Gauge(
    "aicm_app_uptime_seconds",
    "Application uptime in seconds",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Assist Stream 메트릭
# ---------------------------------------------------------------------------

ASSIST_STREAM_REQUESTS = Counter(
    "aicm_assist_stream_requests_total",
    "Assist stream requests",
    ["status", "stage_fail"],  # status=ok|error, stage_fail=none|intent|search|distill|generate
    registry=REGISTRY,
)

ASSIST_STREAM_STAGE_DURATION = Histogram(
    "aicm_assist_stream_stage_duration_seconds",
    "Assist stream stage duration",
    ["stage"],  # intent|search|distill|generate
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0),
    registry=REGISTRY,
)

ASSIST_STREAM_TOKENS = Counter(
    "aicm_assist_stream_tokens_total",
    "Assist stream token counters",
    ["kind"],  # context|completion
    registry=REGISTRY,
)

ASSIST_STREAM_CONCURRENT = Gauge(
    "aicm_assist_stream_concurrent",
    "Assist stream concurrent in-flight requests (per tenant)",
    ["tenant_id"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# 미들웨어
# ---------------------------------------------------------------------------


def _get_route_template(request: Request) -> str:
    """요청에 매칭되는 라우트 템플릿을 반환한다.

    FastAPI 라우트 패턴을 추출하여 카디널리티를 제한한다.
    매칭되지 않으면 'unknown'을 반환한다.
    """
    app = request.app
    for route in app.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", "unknown")
    return "unknown"


class PrometheusMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 요청에 대해 Prometheus 메트릭을 자동 수집하는 미들웨어."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """요청/응답 사이클에서 메트릭을 수집한다."""
        # /metrics, /health 등 내부 엔드포인트는 메트릭에서 제외
        path = request.url.path
        if path in ("/metrics", "/health", "/health/ready", "/health/detailed"):
            return await call_next(request)

        method = request.method
        endpoint = _get_route_template(request)

        REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            REQUEST_ERRORS.labels(
                method=method, endpoint=endpoint, status="500"
            ).inc()
            REQUEST_COUNT.labels(
                method=method, endpoint=endpoint, status="500"
            ).inc()
            REQUESTS_IN_PROGRESS.labels(method=method).dec()
            raise

        duration = time.perf_counter() - start_time
        status = str(response.status_code)

        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)

        if response.status_code >= 400:
            REQUEST_ERRORS.labels(
                method=method, endpoint=endpoint, status=status
            ).inc()

        REQUESTS_IN_PROGRESS.labels(method=method).dec()

        return response
