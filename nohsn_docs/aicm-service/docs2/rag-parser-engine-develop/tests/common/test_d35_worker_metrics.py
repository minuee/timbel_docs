"""D35 §1 + §3 (#215) — worker rebind / self-check counter unit tests.

검증:
- inc_kms_worker_rebind_failure (site, topic) 가 라벨 화이트리스트 강제.
- inc_kms_worker_self_check_fatal (reason) 가 라벨 화이트리스트 강제.
- 미허용 site/topic/reason → 'other' 로 매핑.
- NoOp Counter 폴백 (prometheus_client 미설치 환경 보호).
"""
from __future__ import annotations

import importlib

from src.common.metrics import (
    ALLOWED_FATAL_REASONS,
    ALLOWED_REBIND_SITES,
    ALLOWED_REBIND_TOPICS,
    KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL,
    KMS_WORKER_SELF_CHECK_FATAL_TOTAL,
    REBIND_SITE_BLOCK_PARSED,
    REBIND_SITE_BLOCK_PART_READY,
    REBIND_SITE_DOCUMENT_PROCESSOR,
    REBIND_SITE_MERGE_PART_BLOCKED,
    REBIND_SITE_SEQUENTIAL,
    inc_kms_worker_rebind_failure,
    inc_kms_worker_self_check_fatal,
)


def _read_rebind(site: str, topic: str) -> float:
    return KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL.labels(
        site=site, topic=topic
    )._value.get()


def _read_fatal(reason: str) -> float:
    return KMS_WORKER_SELF_CHECK_FATAL_TOTAL.labels(reason=reason)._value.get()


def test_rebind_site_constants() -> None:
    """REBIND_SITE_* 상수 5종 + 화이트리스트 정합."""
    assert REBIND_SITE_SEQUENTIAL == "sequential_queue_processor"
    assert REBIND_SITE_BLOCK_PARSED == "block_worker_parsed"
    assert REBIND_SITE_BLOCK_PART_READY == "block_worker_part_ready"
    assert REBIND_SITE_MERGE_PART_BLOCKED == "merge_worker_part_blocked"
    assert REBIND_SITE_DOCUMENT_PROCESSOR == "document_processor"
    assert ALLOWED_REBIND_SITES == frozenset(
        {
            REBIND_SITE_SEQUENTIAL,
            REBIND_SITE_BLOCK_PARSED,
            REBIND_SITE_BLOCK_PART_READY,
            REBIND_SITE_MERGE_PART_BLOCKED,
            REBIND_SITE_DOCUMENT_PROCESSOR,
        }
    )


def test_rebind_topic_whitelist() -> None:
    """ALLOWED_REBIND_TOPICS 8종 (any + 7 TOPIC_DOCUMENT_*)."""
    assert "any" in ALLOWED_REBIND_TOPICS
    for t in (
        "aicm.document.uploaded",
        "aicm.document.parsed",
        "aicm.document.chunked",
        "aicm.document.blocked",
        "aicm.document.split",
        "aicm.document.part_ready",
        "aicm.document.part_blocked",
    ):
        assert t in ALLOWED_REBIND_TOPICS


def test_inc_rebind_allowed_site_topic() -> None:
    """allowed site + topic — 정상 카운트."""
    before = _read_rebind(REBIND_SITE_SEQUENTIAL, "aicm.document.uploaded")
    inc_kms_worker_rebind_failure(REBIND_SITE_SEQUENTIAL, "aicm.document.uploaded")
    after = _read_rebind(REBIND_SITE_SEQUENTIAL, "aicm.document.uploaded")
    assert after == before + 1.0


def test_inc_rebind_unknown_site_maps_to_other() -> None:
    """미허용 site → 'other' 로 강제 (cardinality 안전)."""
    before = _read_rebind("other", "any")
    inc_kms_worker_rebind_failure("not_a_real_site", "any")
    after = _read_rebind("other", "any")
    assert after == before + 1.0


def test_inc_rebind_unknown_topic_maps_to_other() -> None:
    """미허용 topic → 'other' 로 강제."""
    before = _read_rebind(REBIND_SITE_SEQUENTIAL, "other")
    inc_kms_worker_rebind_failure(REBIND_SITE_SEQUENTIAL, "ad-hoc.topic.x")
    after = _read_rebind(REBIND_SITE_SEQUENTIAL, "other")
    assert after == before + 1.0


def test_inc_rebind_default_topic_any() -> None:
    """topic 미지정 시 default 'any'."""
    before = _read_rebind(REBIND_SITE_DOCUMENT_PROCESSOR, "any")
    inc_kms_worker_rebind_failure(REBIND_SITE_DOCUMENT_PROCESSOR)
    after = _read_rebind(REBIND_SITE_DOCUMENT_PROCESSOR, "any")
    assert after == before + 1.0


def test_fatal_reason_whitelist() -> None:
    """ALLOWED_FATAL_REASONS — 현재 1종 (bypass_rls_true_app_mode)."""
    assert ALLOWED_FATAL_REASONS == frozenset({"bypass_rls_true_app_mode"})


def test_inc_self_check_fatal_allowed_reason() -> None:
    """allowed reason — 정상 카운트."""
    before = _read_fatal("bypass_rls_true_app_mode")
    inc_kms_worker_self_check_fatal("bypass_rls_true_app_mode")
    after = _read_fatal("bypass_rls_true_app_mode")
    assert after == before + 1.0


def test_inc_self_check_fatal_unknown_reason_maps_to_other() -> None:
    """미허용 reason → 'other'."""
    before = _read_fatal("other")
    inc_kms_worker_self_check_fatal("made_up_reason")
    after = _read_fatal("other")
    assert after == before + 1.0


def test_inc_self_check_fatal_default_reason() -> None:
    """reason 미지정 시 default 'bypass_rls_true_app_mode'."""
    before = _read_fatal("bypass_rls_true_app_mode")
    inc_kms_worker_self_check_fatal()
    after = _read_fatal("bypass_rls_true_app_mode")
    assert after == before + 1.0


def test_noop_counter_fallback_safe() -> None:
    """prometheus_client 미설치 환경 fallback — Counter 호출 안전.

    실 environment 에서는 prometheus_client 설치되어 있으므로
    NoOp 분기 직접 검증은 module-level import 시점에서 처리.
    여기서는 module reload 후 Counter 가 정상 동작하는지만 확인.
    """
    mod = importlib.import_module("src.common.metrics")
    # NoOp 또는 실 Counter 모두 .labels(...).inc() 가 안전.
    mod.KMS_WORKER_SELF_CHECK_FATAL_TOTAL.labels(reason="bypass_rls_true_app_mode").inc()
    mod.KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL.labels(
        site="sequential_queue_processor", topic="any"
    ).inc()


def test_inc_helpers_swallow_exceptions(monkeypatch) -> None:
    """wrapper try/except — 내부 raise 시 main flow 안 막는다."""
    import src.common.metrics as m

    class _RaiseCounter:
        def labels(self, *a, **kw):
            raise RuntimeError("simulated registry error")

        def inc(self):  # pragma: no cover
            raise RuntimeError("simulated inc error")

    monkeypatch.setattr(m, "KMS_WORKER_SELF_CHECK_FATAL_TOTAL", _RaiseCounter())
    monkeypatch.setattr(
        m, "KMS_WORKER_PER_EVENT_REBIND_FAILURE_TOTAL", _RaiseCounter()
    )
    # 호출 시 raise 가 흡수되어야 함.
    m.inc_kms_worker_self_check_fatal("bypass_rls_true_app_mode")
    m.inc_kms_worker_rebind_failure("sequential_queue_processor", "any")
