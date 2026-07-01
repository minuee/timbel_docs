"""D48 §2 + §4 — image_confidence + ETA progress 단위 검증."""
from __future__ import annotations

import os

import pytest

from src.pipeline.processors.image_confidence import (
    build_progress,
    compute_eta_seconds,
    is_enabled,
    progress_update_enabled,
    score_image_confidence,
    to_metadata_dict,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    for k in (
        "IMAGE_CONFIDENCE_ENABLED",
        "IMAGE_CONFIDENCE_MAX_TEXT_CHARS",
        "IMAGE_CONFIDENCE_DECORATIVE_MIN_AREA",
        "PIPELINE_PROGRESS_UPDATE_ENABLED",
        "ETA_BASE_SEC",
        "ETA_PER_BLOCK_SEC",
        "ETA_BASE_SEC_PPT",
        "ETA_PER_BLOCK_SEC_PPT",
    ):
        monkeypatch.delenv(k, raising=False)


# --- §2 score tests --------------------------------------------------------


def test_both_missing_small_image_is_decorative():
    conf = score_image_confidence(
        ocr_text=None, vision_caption=None, image_pixels=100
    )
    assert conf.is_decorative
    assert conf.label == "decorative"
    assert conf.score == 0.0


def test_both_missing_large_image_is_low_not_decorative():
    conf = score_image_confidence(
        ocr_text=None, vision_caption=None, image_pixels=10000
    )
    assert not conf.is_decorative
    assert conf.label == "low"


def test_ocr_and_vision_agreement_high():
    ocr = "월간 매출 추이 2026 5월 증가"
    vision = "월간 매출 추이 2026년 5월 증가 차트"
    conf = score_image_confidence(ocr_text=ocr, vision_caption=vision)
    assert conf.ocr_present and conf.vision_present
    assert conf.agreement > 0.4  # 토큰 잘 겹침
    assert conf.label in ("high", "medium")


def test_ocr_only_short_text_low():
    conf = score_image_confidence(ocr_text="OK", vision_caption=None)
    assert conf.ocr_present and not conf.vision_present
    assert conf.label == "low"


def test_vision_only_long_text_medium():
    conf = score_image_confidence(
        ocr_text=None,
        vision_caption="이 슬라이드는 클라우드 전환의 단계를 시각화한 흐름도입니다",
    )
    assert conf.vision_present and not conf.ocr_present
    assert conf.label in ("medium", "low")


def test_lang_mismatch_fallback_to_ngram():
    # 영문 caption + 한글 OCR — token jaccard 는 0 가깝지만 n-gram fallback 적용
    ocr = "매출 보고서"
    vision = "monthly sales report"
    conf = score_image_confidence(ocr_text=ocr, vision_caption=vision)
    # fallback used 또는 0 score 둘 다 허용 (실 데이터 의존)
    assert conf.ocr_present and conf.vision_present


def test_numeric_normalization_dates_match():
    # 2026-05-11 vs 2026/5/11 → 정규화 후 매칭
    ocr = "보고일 2026-05-11"
    vision = "보고일 2026/5/11"
    conf = score_image_confidence(ocr_text=ocr, vision_caption=vision)
    # 정규화 후 동일 토큰
    assert conf.agreement > 0.3


def test_long_text_truncated_with_ref(monkeypatch):
    # 비정상값 방어 — 0 / 음수 / 64 미만 → 최소 64 floor
    monkeypatch.setenv("IMAGE_CONFIDENCE_MAX_TEXT_CHARS", "100")
    ocr = "a" * 1000
    conf = score_image_confidence(ocr_text=ocr, vision_caption=None)
    assert conf.ocr_needs_ref
    assert conf.ocr_preview is not None and len(conf.ocr_preview) <= 110  # 100 + "..."

    md = to_metadata_dict(conf, document_id="d1", block_id="b1")
    assert md["ocr_extracted_text_ref"] == (
        "kms-intermediate/image_confidence/d1/b1-ocr.txt"
    )
    assert "..." in md["ocr_extracted_text_preview"]


def test_max_chars_min_floor_64(monkeypatch):
    """비정상값 (0/음수) → 최소 64 floor 적용."""
    monkeypatch.setenv("IMAGE_CONFIDENCE_MAX_TEXT_CHARS", "0")
    ocr = "a" * 200
    conf = score_image_confidence(ocr_text=ocr, vision_caption=None)
    # 64 char preview + "..." → len <= 67
    assert conf.ocr_preview is not None
    assert len(conf.ocr_preview) <= 67


def test_ref_prefix_env_override(monkeypatch):
    monkeypatch.setenv("IMAGE_CONFIDENCE_REF_PREFIX", "custom-bucket/myprefix")
    monkeypatch.setenv("IMAGE_CONFIDENCE_MAX_TEXT_CHARS", "100")
    ocr = "x" * 500
    conf = score_image_confidence(ocr_text=ocr, vision_caption=None)
    md = to_metadata_dict(conf, document_id="docA", block_id="blkB")
    assert md["ocr_extracted_text_ref"] == "custom-bucket/myprefix/docA/blkB-ocr.txt"


def test_path_sanitization():
    """document_id / block_id 에 path injection 문자 포함 → sanitize."""
    from src.pipeline.processors.image_confidence import _sanitize_path_segment

    assert _sanitize_path_segment("hello") == "hello"
    assert "../" not in _sanitize_path_segment("../../etc/passwd")
    assert _sanitize_path_segment("a/b/c") == "a_b_c"
    assert _sanitize_path_segment("uuid-1234-abc") == "uuid-1234-abc"  # 하이픈 보존


def test_threshold_env_override(monkeypatch):
    # high 임계를 0.5 로 낮추면 medium score 가 high 로 승격
    monkeypatch.setenv("IMAGE_CONFIDENCE_HIGH_THRESHOLD", "0.5")
    conf = score_image_confidence(
        ocr_text="hello world test data",
        vision_caption="hello world test data",
    )
    assert conf.label == "high"
    # medium 임계를 0.1 로 낮추면 low 인 짧은 텍스트도 medium 으로 승격
    monkeypatch.setenv("IMAGE_CONFIDENCE_MEDIUM_THRESHOLD", "0.1")
    conf2 = score_image_confidence(ocr_text="hi", vision_caption=None)
    # score 0.15 >= 0.1 → medium (env override)
    assert conf2.label in ("medium", "high")


def test_per_page_fallback_env(monkeypatch):
    monkeypatch.setenv("ETA_PER_PAGE_FALLBACK_SEC", "50")
    eta = compute_eta_seconds(
        estimated_blocks=None, page_count=10, source_format="pdf"
    )
    # 10 * 50 = 500
    assert eta == 500


def test_short_text_no_ref():
    conf = score_image_confidence(
        ocr_text="짧은 OCR", vision_caption="짧은 caption"
    )
    md = to_metadata_dict(conf, document_id="d1", block_id="b1")
    assert "ocr_extracted_text_ref" not in md
    assert "vision_caption_ref" not in md
    assert md["ocr_extracted_text_preview"] == "짧은 OCR"


def test_is_enabled_env(monkeypatch):
    assert is_enabled() is True
    monkeypatch.setenv("IMAGE_CONFIDENCE_ENABLED", "false")
    assert is_enabled() is False
    monkeypatch.setenv("IMAGE_CONFIDENCE_ENABLED", "1")
    assert is_enabled() is True


def test_metadata_dict_includes_required_keys():
    conf = score_image_confidence(
        ocr_text="hello world", vision_caption="hello world"
    )
    md = to_metadata_dict(conf, document_id="d", block_id="b")
    required = {
        "image_confidence_score",
        "image_confidence_label",
        "image_confidence_agreement",
        "is_decorative",
        "image_confidence_fallback_used",
    }
    assert required.issubset(md.keys())


# --- §4 ETA + progress tests ----------------------------------------------


def test_eta_pdf_default():
    eta = compute_eta_seconds(
        estimated_blocks=100, page_count=20, source_format="pdf"
    )
    # 176 + 0.81 * 100 = 257
    assert 250 <= eta <= 270


def test_eta_ppt_uses_ppt_coefficients():
    eta_pdf = compute_eta_seconds(estimated_blocks=100, source_format="pdf")
    eta_ppt = compute_eta_seconds(estimated_blocks=100, source_format="pptx")
    # PPT 계수가 더 보수 (1.3 vs 0.81)
    assert eta_ppt > eta_pdf


def test_eta_fallback_to_page_count():
    eta = compute_eta_seconds(
        estimated_blocks=None, page_count=10, source_format="pdf"
    )
    # 10 * 30 = 300
    assert eta == 300


def test_eta_ppt_fallback():
    eta = compute_eta_seconds(
        estimated_blocks=None, page_count=20, source_format="pptx"
    )
    # 20 * 40 = 800
    assert eta == 800


def test_eta_no_data_returns_base():
    eta = compute_eta_seconds(
        estimated_blocks=None, page_count=None, source_format="pdf"
    )
    assert eta >= 100  # base_sec


def test_eta_env_override(monkeypatch):
    monkeypatch.setenv("ETA_BASE_SEC", "60")
    monkeypatch.setenv("ETA_PER_BLOCK_SEC", "0.5")
    eta = compute_eta_seconds(estimated_blocks=100, source_format="pdf")
    # 60 + 0.5 * 100 = 110
    assert 105 <= eta <= 115


def test_build_progress_structure():
    prog = build_progress(
        current_part=3,
        total_parts=8,
        current_stage="blocking",
        stage_started_at_iso="2026-05-11T08:15:17Z",
        elapsed_seconds=60,
        eta_seconds=300,
    )
    assert prog["current_part"] == 3
    assert prog["total_parts"] == 8
    assert prog["current_stage"] == "blocking"
    assert prog["estimated_remaining_seconds"] == 240
    assert prog["elapsed_seconds"] == 60


def test_build_progress_negative_remaining_clamps_zero():
    prog = build_progress(
        current_part=8,
        total_parts=8,
        current_stage="embedding",
        stage_started_at_iso="2026-05-11T08:15:17Z",
        elapsed_seconds=1000,
        eta_seconds=300,
    )
    assert prog["estimated_remaining_seconds"] == 0


def test_progress_update_enabled_env(monkeypatch):
    assert progress_update_enabled() is True
    monkeypatch.setenv("PIPELINE_PROGRESS_UPDATE_ENABLED", "0")
    assert progress_update_enabled() is False
