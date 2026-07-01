"""D48 §1 — upload_topic_classifier unit tests.

- format-aware 우선 규칙 (text-only/scan/video)
- file_size 임계 (binary MiB)
- env toggle (PIPELINE_LARGE_TOPIC_ENABLED=false → legacy)
- file_size 미상 → small 보수
"""
from __future__ import annotations

import os

import pytest

from src.common.constants import (
    TOPIC_DOCUMENT_UPLOADED,
    TOPIC_DOCUMENT_UPLOADED_LARGE,
    TOPIC_DOCUMENT_UPLOADED_SMALL,
)
from src.pipeline.services.upload_topic_classifier import classify_upload_topic


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """매 테스트 직전 env 초기화 — 다른 테스트의 상태 누수 방지."""
    for k in (
        "PIPELINE_SMALL_SIZE_MB_THRESHOLD",
        "PIPELINE_LARGE_TOPIC_ENABLED",
    ):
        monkeypatch.delenv(k, raising=False)


def test_text_only_md_is_small_regardless_of_size(monkeypatch):
    # 10 MiB markdown — 임계 초과지만 text-only 우선 규칙으로 small
    decision = classify_upload_topic(
        file_size_bytes=10 * 1_048_576,
        source_path="/data/note.md",
        source_format="markdown",
    )
    assert decision.topic == TOPIC_DOCUMENT_UPLOADED_SMALL
    assert decision.profile == "small"
    assert decision.reason == "text_only_format"


def test_text_only_txt_is_small():
    decision = classify_upload_topic(
        file_size_bytes=5 * 1_048_576,
        source_path="/data/dump.txt",
        source_format="txt",
    )
    assert decision.profile == "small"


def test_scan_tiff_is_large_regardless_of_size():
    decision = classify_upload_topic(
        file_size_bytes=100_000,  # 작아도 스캔
        source_path="/data/scan.tiff",
        source_format="image",
    )
    assert decision.topic == TOPIC_DOCUMENT_UPLOADED_LARGE
    assert decision.profile == "large"
    assert decision.reason == "scan_or_video_format"


def test_video_mp4_is_large():
    decision = classify_upload_topic(
        file_size_bytes=1_000_000,
        source_path="/data/clip.mp4",
        source_format="video",
    )
    assert decision.profile == "large"


def test_pdf_below_threshold_is_small():
    decision = classify_upload_topic(
        file_size_bytes=1_500_000,  # ~1.43 MiB < 2 MiB
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.profile == "small"
    assert decision.reason == "size_below_threshold"


def test_pdf_above_threshold_is_large():
    decision = classify_upload_topic(
        file_size_bytes=5 * 1_048_576,  # 5 MiB > 2 MiB
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.profile == "large"
    assert decision.reason == "size_above_threshold"


def test_pdf_exact_threshold_is_large():
    decision = classify_upload_topic(
        file_size_bytes=2 * 1_048_576,  # 정확히 2 MiB → large (>=)
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.profile == "large"


def test_env_disabled_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("PIPELINE_LARGE_TOPIC_ENABLED", "false")
    decision = classify_upload_topic(
        file_size_bytes=10 * 1_048_576,
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.topic == TOPIC_DOCUMENT_UPLOADED
    assert decision.profile == "legacy"
    assert decision.reason == "large_topic_disabled"


def test_unknown_size_defaults_small():
    decision = classify_upload_topic(
        file_size_bytes=None,
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.profile == "small"
    assert decision.reason == "size_unknown_default_small"


def test_zero_size_defaults_small():
    decision = classify_upload_topic(
        file_size_bytes=0,
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.profile == "small"


def test_custom_threshold_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_SMALL_SIZE_MB_THRESHOLD", "5")
    # 3 MiB < 5 MiB → small
    decision = classify_upload_topic(
        file_size_bytes=3 * 1_048_576,
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision.profile == "small"
    # 6 MiB > 5 MiB → large
    decision2 = classify_upload_topic(
        file_size_bytes=6 * 1_048_576,
        source_path="/data/report.pdf",
        source_format="pdf",
    )
    assert decision2.profile == "large"


def test_pptx_above_threshold_is_large():
    decision = classify_upload_topic(
        file_size_bytes=10 * 1_048_576,
        source_path="/data/deck.pptx",
        source_format="pptx",
    )
    assert decision.profile == "large"


def test_docx_below_threshold_is_small():
    decision = classify_upload_topic(
        file_size_bytes=500_000,
        source_path="/data/letter.docx",
        source_format="docx",
    )
    assert decision.profile == "small"


def test_path_none_safely_handled():
    decision = classify_upload_topic(
        file_size_bytes=1_000_000,
        source_path=None,
        source_format=None,
    )
    # 확장자 추출 불가 → file_size 임계로 결정. 1 MiB < 2 MiB → small
    assert decision.profile == "small"
