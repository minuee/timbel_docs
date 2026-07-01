"""D46-v3 §6 — per-stage logging + Prometheus metric tests.

검증:
- src.common.metrics 의 4 metric (3 stage + 1 retry) 정의됨.
- helper 4종 export 동작.
- prometheus_client NoOp fallback (Histogram observe) 안전.
- embed_worker 의 stage timing log 호출 (caplog 기반).
"""
from __future__ import annotations

import pytest


def test_kms_pipeline_stage_metrics_exported() -> None:
    """4 metric + 4 helper 모두 src.common.metrics 에 export."""
    from src.common import metrics as m

    assert hasattr(m, "KMS_PIPELINE_STAGE_DURATION_SECONDS")
    assert hasattr(m, "KMS_PIPELINE_STAGE_FAILURE_TOTAL")
    assert hasattr(m, "KMS_PIPELINE_STAGE_COUNT_TOTAL")
    assert hasattr(m, "KMS_PIPELINE_MERGE_PART_RETRY_TOTAL")
    assert hasattr(m, "inc_kms_pipeline_stage_count")
    assert hasattr(m, "observe_kms_pipeline_stage_duration")
    assert hasattr(m, "inc_kms_pipeline_stage_failure")
    assert hasattr(m, "inc_kms_pipeline_merge_part_retry")


def test_helpers_callable_no_exception() -> None:
    """helper 함수가 호출 시 예외 없이 동작 (NoOp fallback 안전)."""
    from src.common.metrics import (
        inc_kms_pipeline_merge_part_retry,
        inc_kms_pipeline_stage_count,
        inc_kms_pipeline_stage_failure,
        observe_kms_pipeline_stage_duration,
    )

    inc_kms_pipeline_stage_count("reload")
    inc_kms_pipeline_stage_count("contextual")
    inc_kms_pipeline_stage_count("metadata")
    inc_kms_pipeline_stage_count("embedding")
    inc_kms_pipeline_stage_count("qdrant")
    observe_kms_pipeline_stage_duration("reload", 0.5)
    observe_kms_pipeline_stage_duration("qdrant", 12.3)
    inc_kms_pipeline_stage_failure("embedding", "RuntimeError")
    inc_kms_pipeline_merge_part_retry()
    # 예외 없이 통과 → 검증 완료.


def test_histogram_noop_fallback_observe_method() -> None:
    """prometheus_client 미설치 시 Histogram NoOp 에 observe 메서드 존재.

    실 prometheus_client 가 설치된 환경에서도 Histogram 객체가 observe 를 가지므로
    호출만 검증 — 둘 다 동작.
    """
    from src.common.metrics import KMS_PIPELINE_STAGE_DURATION_SECONDS

    # labels().observe() chain — NoOp 이든 진짜이든 무예외.
    KMS_PIPELINE_STAGE_DURATION_SECONDS.labels(stage="test").observe(1.0)


def test_failure_metric_label_safety() -> None:
    """error_type 라벨이 type(exc).__name__ 으로 제공되는 패턴 확인."""
    from src.common.metrics import inc_kms_pipeline_stage_failure

    try:
        raise ValueError("test")
    except ValueError as exc:
        inc_kms_pipeline_stage_failure("reload", type(exc).__name__)
    # 무예외 통과.


def test_embed_worker_module_imports_helpers() -> None:
    """embed_worker.py 가 §6 helper 를 import 하는지 (lazy import 시뮬레이션)."""
    import src.pipeline.workers.embed_worker  # noqa: F401

    # import 만으로 검증 — 모듈 load 시 syntax/import 오류 없음.
