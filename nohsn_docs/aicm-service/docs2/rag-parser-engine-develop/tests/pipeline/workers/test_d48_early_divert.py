"""D48 §1 — early divert helpers (`_should_divert_to_large`) 단위 검증."""
from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from src.common.constants import (
    TOPIC_DOCUMENT_UPLOADED,
    TOPIC_DOCUMENT_UPLOADED_LARGE,
    TOPIC_DOCUMENT_UPLOADED_SMALL,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    for k in (
        "PIPELINE_EARLY_DIVERT_ENABLED",
        "PIPELINE_LARGE_TOPIC_ENABLED",
        "PIPELINE_SMALL_SIZE_MB_THRESHOLD",
    ):
        monkeypatch.delenv(k, raising=False)


def _import_main():
    from src.pipeline.workers import main as main_module
    return main_module


def _event_value(profile: str | None = None, file_size_bytes: int | None = None,
                 source_path: str = "/data/sample.pdf") -> bytes:
    payload: dict = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "repository_id": "00000000-0000-0000-0000-000000000003",
        "source_format": "pdf",
        "source_path": source_path,
        "timestamp": "2026-05-11T08:00:00Z",
    }
    if profile or file_size_bytes is not None:
        payload["upload_classification"] = {
            "profile": profile or "small",
            "reason": "test",
            "threshold_mib": 2,
            "file_size_bytes": file_size_bytes or 0,
        }
    return json.dumps(payload).encode("utf-8")


def test_divert_only_when_small_profile():
    main = _import_main()
    val = _event_value(profile="large")
    # large 프로파일 워커는 divert 안 함
    assert not main._should_divert_to_large(
        value_bytes=val, profile="large", incoming_topic=TOPIC_DOCUMENT_UPLOADED
    )


def test_divert_only_for_legacy_topic():
    main = _import_main()
    val = _event_value(profile="large")
    # small worker 가 small topic 에서 받으면 divert 안 함 (정상 처리)
    assert not main._should_divert_to_large(
        value_bytes=val, profile="small", incoming_topic=TOPIC_DOCUMENT_UPLOADED_SMALL
    )


def test_divert_when_classification_says_large():
    main = _import_main()
    val = _event_value(profile="large")
    assert main._should_divert_to_large(
        value_bytes=val, profile="small", incoming_topic=TOPIC_DOCUMENT_UPLOADED
    )


def test_no_divert_when_classification_says_small():
    main = _import_main()
    val = _event_value(profile="small")
    assert not main._should_divert_to_large(
        value_bytes=val, profile="small", incoming_topic=TOPIC_DOCUMENT_UPLOADED
    )


def test_divert_disabled_by_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_EARLY_DIVERT_ENABLED", "false")
    main = _import_main()
    val = _event_value(profile="large")
    assert not main._should_divert_to_large(
        value_bytes=val, profile="small", incoming_topic=TOPIC_DOCUMENT_UPLOADED
    )


def test_divert_disabled_when_large_topic_disabled(monkeypatch):
    monkeypatch.setenv("PIPELINE_LARGE_TOPIC_ENABLED", "false")
    main = _import_main()
    val = _event_value(profile="large")
    # large 토픽이 비활성화 → blackhole 방지 위해 divert 안 함
    assert not main._should_divert_to_large(
        value_bytes=val, profile="small", incoming_topic=TOPIC_DOCUMENT_UPLOADED
    )


def test_divert_fallback_classify_when_no_classification(tmp_path):
    """upload_classification 메타가 없으면 file_size 로 재분류."""
    main = _import_main()
    # 임시 5 MiB 파일 (실제로는 sparse 가능)
    fake = tmp_path / "big.pdf"
    fake.write_bytes(b"x" * (5 * 1_048_576))

    payload = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "repository_id": "00000000-0000-0000-0000-000000000003",
        "source_format": "pdf",
        "source_path": str(fake),
        "timestamp": "2026-05-11T08:00:00Z",
    }
    val = json.dumps(payload).encode("utf-8")
    # 5 MiB > 2 MiB threshold → divert
    assert main._should_divert_to_large(
        value_bytes=val, profile="small", incoming_topic=TOPIC_DOCUMENT_UPLOADED
    )


def test_worker_profile_resolution(monkeypatch):
    main = _import_main()
    monkeypatch.setenv("PIPELINE_WORKER_PROFILE", "small")
    assert main._resolve_worker_profile() == "small"
    monkeypatch.setenv("PIPELINE_WORKER_PROFILE", "large")
    assert main._resolve_worker_profile() == "large"
    monkeypatch.setenv("PIPELINE_WORKER_PROFILE", "garbage")
    assert main._resolve_worker_profile() == "legacy"
    monkeypatch.delenv("PIPELINE_WORKER_PROFILE")
    assert main._resolve_worker_profile() == "legacy"


def test_uploaded_topics_per_profile():
    main = _import_main()
    assert main._resolve_uploaded_topics_for_profile("small") == [
        TOPIC_DOCUMENT_UPLOADED_SMALL,
        TOPIC_DOCUMENT_UPLOADED,
    ]
    assert main._resolve_uploaded_topics_for_profile("large") == [
        TOPIC_DOCUMENT_UPLOADED_LARGE,
    ]
    legacy = main._resolve_uploaded_topics_for_profile("legacy")
    assert TOPIC_DOCUMENT_UPLOADED in legacy
    assert TOPIC_DOCUMENT_UPLOADED_SMALL in legacy
    assert TOPIC_DOCUMENT_UPLOADED_LARGE in legacy


def test_parallel_workers_per_profile(monkeypatch):
    main = _import_main()
    monkeypatch.delenv("PIPELINE_PARALLEL_WORKERS_SMALL", raising=False)
    monkeypatch.delenv("PIPELINE_PARALLEL_WORKERS_LARGE", raising=False)
    assert main._resolve_parallel_workers("small") == 4
    assert main._resolve_parallel_workers("large") == 1
    monkeypatch.setenv("PIPELINE_PARALLEL_WORKERS_SMALL", "8")
    assert main._resolve_parallel_workers("small") == 8
    monkeypatch.setenv("PIPELINE_PARALLEL_WORKERS_LARGE", "2")
    assert main._resolve_parallel_workers("large") == 2
