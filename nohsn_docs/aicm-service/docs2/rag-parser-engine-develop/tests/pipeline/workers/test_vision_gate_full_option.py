"""vision_gate 풀옵션 모드 테스트 — KMS-Plus 2026-05-07.

사용자 절칙: "비전 처리 및 OCR도 필요하면 전부 풀옵션으로 처리".

검증:
- BROKEN_RATIO_THRESHOLD 가 0.10 으로 낮춰진 상태.
- SCANNED_RATIO_THRESHOLD 가 0.15 로 낮춰진 상태.
- VISION_ALWAYS_PDF=1 env 시 깨끗한 PDF 도 use_vision=True.
- env 미설정 시 기존 게이트 그대로 (회귀 0).
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from src.pipeline.workers.vision_gate import (
    BROKEN_RATIO_THRESHOLD,
    SCANNED_RATIO_THRESHOLD,
    _force_vision_for_pdfs,
    decide_vision,
)


def _fake_parse_result(*, raw_text="text content", pages=None, pdf_path=None):
    pr = MagicMock()
    pr.raw_text = raw_text
    pr.pages = pages or []
    pr.pdf_path = pdf_path
    pr.metadata = {}
    return pr


def test_thresholds_lowered_for_full_option():
    """KMS-Plus 2026-05-07 — 절칙: 풀옵션 강화."""
    assert BROKEN_RATIO_THRESHOLD == 0.10, "BROKEN: 0.20 → 0.10 (절칙)"
    assert SCANNED_RATIO_THRESHOLD == 0.15, "SCANNED: 0.30 → 0.15 (절칙)"


def test_force_vision_env_default_off(monkeypatch):
    """env 미설정 시 default off — 기존 게이트 작동."""
    monkeypatch.delenv("VISION_ALWAYS_PDF", raising=False)
    assert _force_vision_for_pdfs() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "On"])
def test_force_vision_env_on(monkeypatch, val):
    """env 활성화 — 다양한 truthy 값 인식."""
    monkeypatch.setenv("VISION_ALWAYS_PDF", val)
    assert _force_vision_for_pdfs() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "  "])
def test_force_vision_env_off(monkeypatch, val):
    monkeypatch.setenv("VISION_ALWAYS_PDF", val)
    assert _force_vision_for_pdfs() is False


def test_clean_pdf_text_path_when_env_off(monkeypatch, tmp_path):
    """env off + 깨끗한 PDF (broken=0, scanned=0) → text path."""
    monkeypatch.delenv("VISION_ALWAYS_PDF", raising=False)
    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    pr = _fake_parse_result(raw_text="clean korean text 깨끗한 본문", pdf_path=None)
    decision = decide_vision(pr, str(pdf_path))
    # 깨끗한 PDF — vision 안씀.
    assert decision.use_vision is False
    assert decision.reason == "text_path_clean_pdf"


def test_clean_pdf_force_vision_when_env_on(monkeypatch, tmp_path):
    """env on + 깨끗한 PDF → 풀옵션 모드, vision 강제."""
    monkeypatch.setenv("VISION_ALWAYS_PDF", "1")
    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    pr = _fake_parse_result(raw_text="clean korean text 깨끗한 본문")
    decision = decide_vision(pr, str(pdf_path))
    assert decision.use_vision is True
    assert decision.reason == "pdf_full_option_env"


def test_lower_broken_threshold_triggers_vision(monkeypatch, tmp_path):
    """0.10~0.20 사이 broken 비율 — 옛 게이트라면 text, 새 게이트 vision."""
    monkeypatch.delenv("VISION_ALWAYS_PDF", raising=False)
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    # 11% 깨진 비율 가정 — detect_broken_text_ratio 직접 호출 어려우니 mock.
    from unittest.mock import patch
    with patch(
        "src.pipeline.workers.vision_gate.detect_broken_text_ratio",
        return_value=0.12,
    ), patch(
        "src.pipeline.workers.vision_gate.detect_glyph_doubling_runs",
        return_value=0,
    ):
        pr = _fake_parse_result(raw_text="broken")
        decision = decide_vision(pr, str(pdf_path))
    # 새 임계값 0.10 → 0.12 면 vision.
    assert decision.use_vision is True
    assert decision.reason == "broken_text"
