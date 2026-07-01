"""Pipeline Prometheus 메트릭 -- Phase 3 Production Hardening.

prometheus_client 기반 메트릭 정의와 자동 계측 데코레이터.
파이프라인 워커 전용 메트릭 HTTP 서버 포함 (포트 8001).

사용법::

    from src.pipeline.metrics import PIPELINE_METRICS, track_stage

    @track_stage("parse")
    async def handle_document_uploaded(event, producer):
        ...

    # 수동 메트릭 기록
    PIPELINE_METRICS.chunks_created.inc(42)
    PIPELINE_METRICS.documents_processed_total.labels(tenant="t1", status="success").inc()
"""

from __future__ import annotations

import functools
import json
import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, TypeVar

from prometheus_client import Counter, Gauge, Histogram, generate_latest, REGISTRY

from src.common.logging import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Pipeline 워커 메트릭/health 서버 포트.
# 기본 8001 (compose healthcheck 와 동일). k8s 등에서 EKS SG 정책상 다른 포트가
# 필요하면 PIPELINE_METRICS_PORT env 로 override (예: 8080).
PIPELINE_METRICS_PORT = int(os.environ.get("PIPELINE_METRICS_PORT", "8001"))


# ---------------------------------------------------------------------------
# 메트릭 정의
# ---------------------------------------------------------------------------

class PipelineMetrics:
    """파이프라인 Prometheus 메트릭 집합.

    기존 스테이지별 메트릭 + 테넌트/검색/LLM/캐시/감사 메트릭을 통합한다.
    """

    def __init__(self) -> None:
        # === 기존 스테이지별 메트릭 (하위 호환) ===

        self.documents_processed = Counter(
            "aicm_pipeline_stage_documents_total",
            "처리된 문서 수 (스테이지별)",
            labelnames=["stage", "status"],
        )

        self.stage_duration = Histogram(
            "aicm_pipeline_stage_duration_seconds",
            "파이프라인 스테이지별 처리 시간 (초)",
            labelnames=["stage"],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
        )

        self.documents_in_progress = Gauge(
            "aicm_pipeline_documents_in_progress",
            "현재 처리 중인 문서 수",
        )

        self.errors = Counter(
            "aicm_pipeline_errors_total",
            "파이프라인 오류 수",
            labelnames=["stage", "error_type"],
        )

        self.chunks_created = Counter(
            "aicm_pipeline_chunks_created_total",
            "생성된 청크 수",
        )

        self.embedding_batch_size = Histogram(
            "aicm_pipeline_embedding_batch_size",
            "임베딩 배치 크기 분포",
            buckets=(1, 4, 8, 16, 32, 64, 128, 256),
        )

        # === 문서 처리 카운터 (테넌트별) ===

        self.documents_processed_total = Counter(
            "aicm_documents_processed_total",
            "처리된 문서 총 수 (테넌트별, 상태별)",
            labelnames=["tenant", "status"],
        )

        # === LLM 호출 메트릭 ===

        self.llm_call_duration = Histogram(
            "aicm_llm_call_duration_seconds",
            "LLM 호출 소요 시간 (초)",
            labelnames=["provider", "task"],
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
        )

        self.llm_calls_total = Counter(
            "aicm_llm_calls_total",
            "LLM 호출 총 수",
            labelnames=["provider", "task", "success"],
        )

        # === 임베딩 배치 크기 히스토그램 ===

        self.embed_batch_size = Histogram(
            "aicm_embed_batch_size",
            "BGE-M3 임베딩 배치 크기 분포",
            buckets=(1, 4, 8, 16, 32, 64, 128, 256, 512),
        )

        # === 파이프라인 큐 게이지 ===

        self.pipeline_queue_size = Gauge(
            "aicm_pipeline_queue_size",
            "파이프라인 처리 대기 큐 크기",
        )

        self.pipeline_active_workers = Gauge(
            "aicm_pipeline_active_workers",
            "현재 활성 파이프라인 워커 수",
        )

        # === 문서 현황 게이지 (테넌트별) ===

        self.documents_total = Gauge(
            "aicm_documents_total",
            "현재 문서 수 (테넌트별, 상태별)",
            labelnames=["tenant", "status"],
        )

        # === 스토리지 게이지 (테넌트별) ===

        self.storage_bytes = Gauge(
            "aicm_storage_bytes",
            "MinIO 스토리지 사용량 (바이트)",
            labelnames=["tenant", "bucket"],
        )


# 싱글턴 인스턴스
PIPELINE_METRICS = PipelineMetrics()


# ---------------------------------------------------------------------------
# 파이프라인 워커 메트릭 HTTP 서버
# ---------------------------------------------------------------------------

_metrics_server_started = False


class _PipelineMetricsHandler(BaseHTTPRequestHandler):
    """파이프라인 워커용 HTTP 핸들러: /metrics + /health/live."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health/live":
            body = json.dumps({"status": "alive"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/metrics":
            body = generate_latest(REGISTRY)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """기본 stderr 로깅 억제."""
        pass


def start_pipeline_metrics_server(port: int = PIPELINE_METRICS_PORT) -> None:
    """파이프라인 워커용 /metrics + /health/live HTTP 서버를 백그라운드 스레드로 시작한다.

    - ``GET /metrics``      — Prometheus 메트릭 (기본 레지스트리)
    - ``GET /health/live``  — liveness probe (항상 200)

    Parameters
    ----------
    port : int
        메트릭/헬스 서버 포트 (기본값: 8001)
    """
    global _metrics_server_started
    if _metrics_server_started:
        return
    try:
        server = HTTPServer(("0.0.0.0", port), _PipelineMetricsHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _metrics_server_started = True
        log.info("pipeline_metrics_server_started", port=port, endpoints=["/metrics", "/health/live"])
    except OSError as exc:
        log.warning("pipeline_metrics_server_failed", port=port, error=str(exc))


# ---------------------------------------------------------------------------
# 자동 계측 데코레이터
# ---------------------------------------------------------------------------

def track_stage(stage: str) -> Callable[[F], F]:
    """비동기 함수를 Prometheus 메트릭으로 자동 계측하는 데코레이터.

    - documents_processed (stage, success/failure)
    - stage_duration (stage)
    - documents_in_progress (+1 시작, -1 종료)
    - errors (stage, error_type) -- 예외 발생 시

    Parameters
    ----------
    stage : str
        파이프라인 스테이지 이름 (예: "parse", "block", "embed")
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            PIPELINE_METRICS.documents_in_progress.inc()
            PIPELINE_METRICS.pipeline_active_workers.inc()
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.monotonic() - start
                PIPELINE_METRICS.stage_duration.labels(stage=stage).observe(elapsed)
                PIPELINE_METRICS.documents_processed.labels(
                    stage=stage, status="success"
                ).inc()
                return result
            except Exception as exc:
                elapsed = time.monotonic() - start
                PIPELINE_METRICS.stage_duration.labels(stage=stage).observe(elapsed)
                PIPELINE_METRICS.documents_processed.labels(
                    stage=stage, status="failure"
                ).inc()
                error_type = type(exc).__name__
                PIPELINE_METRICS.errors.labels(
                    stage=stage, error_type=error_type
                ).inc()
                raise
            finally:
                PIPELINE_METRICS.documents_in_progress.dec()
                PIPELINE_METRICS.pipeline_active_workers.dec()

        return wrapper  # type: ignore[return-value]

    return decorator


def track_llm_call(provider: str, task: str) -> Callable[[F], F]:
    """LLM 호출을 Prometheus 메트릭으로 계측하는 데코레이터.

    Parameters
    ----------
    provider : str
        LLM 제공자 (예: "gemma", "qwen", "claude")
    task : str
        LLM 작업 유형 (예: "block_segmentation", "classification", "rag")
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.monotonic() - start
                PIPELINE_METRICS.llm_call_duration.labels(
                    provider=provider, task=task
                ).observe(elapsed)
                PIPELINE_METRICS.llm_calls_total.labels(
                    provider=provider, task=task, success="true"
                ).inc()
                return result
            except Exception:
                elapsed = time.monotonic() - start
                PIPELINE_METRICS.llm_call_duration.labels(
                    provider=provider, task=task
                ).observe(elapsed)
                PIPELINE_METRICS.llm_calls_total.labels(
                    provider=provider, task=task, success="false"
                ).inc()
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
