"""Vision 파이프라인 분기 결정 모듈 (Phase B-1).

block_worker 가 LLMPipeline(3-stage Vision)을 호출할지 텍스트 세그먼터
경로로 갈지 판정한다.

판정 규칙
---------
1. 원본이 PPT/PPTX → **항상 Vision** (슬라이드 순서가 곧 의미 순서가 아니므로
   전체 슬라이드 맥락 이해가 필요)
2. PDF 또는 PDF 변환본:
   - 깨진 한글 비율(broken_text_ratio) ≥ 0.20 → Vision
   - 스캔 페이지(ocr_used=True) 비율 ≥ 0.30 → Vision
   - 위 조건 모두 미충족 → 텍스트 경로 (LLMBlockSegmenter / FallbackSegmenter)
3. PDF 가 아니고 PPT 도 아니면 → 텍스트 경로

깨끗한 영문/디지털 PDF 는 텍스트 경로로 빠지므로 GPU 시간을 절약하고,
한글 CID 깨짐/스캔/PPT 등 텍스트로 풀기 어려운 케이스만 Vision 으로 보낸다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.pdf_parser import (
    detect_broken_text_ratio,
    detect_glyph_doubling_runs,
)


# Vision 분기 임계값 — 변경 시 docs/PIPELINE_BASELINE.md 회귀 기준도 함께 수정
#
# KMS-Plus 2026-05-07 — 비전/OCR 풀옵션 강화 (사용자 절칙):
# "표나 그림 등의 자료를 보여줘야 할수 있고 답변을 해야할수 있기 때문이야.
#  비전 처리 및 OCR도 필요하면 전부 풀옵션으로 처리해서 데이터는 처리 할수 있도록 해"
# - BROKEN_RATIO_THRESHOLD : 0.20 → 0.10  (더 적극적 vision 사용)
# - SCANNED_RATIO_THRESHOLD: 0.30 → 0.15  (스캔 페이지 1/7 만 있어도 vision)
# - VISION_ALWAYS_PDF env  : "1"/"true" 면 PDF 전부 항상 vision (text path 우회)
BROKEN_RATIO_THRESHOLD = 0.10
SCANNED_RATIO_THRESHOLD = 0.15
# AABB+ 런이 이 개수 이상이면 glyph doubling 깨짐 판정 (하이패스 타입)
GLYPH_DOUBLING_RUNS_THRESHOLD = 3
_PPT_EXTS = (".ppt", ".pptx")
_PDF_EXTS = (".pdf",)


def _force_vision_for_pdfs() -> bool:
    """PDF 면 항상 vision — 풀옵션 모드. env ``VISION_ALWAYS_PDF`` 로 토글.

    "1" / "true" / "yes" / "on" 모두 활성화. 기본 비활성 (회귀 0).
    """
    raw = os.environ.get("VISION_ALWAYS_PDF", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


@dataclass
class VisionDecision:
    """Vision 파이프라인 사용 여부 + 사유."""

    use_vision: bool
    reason: str
    is_ppt: bool = False
    broken_ratio: float = 0.0
    scanned_ratio: float = 0.0
    glyph_doubling_runs: int = 0
    pdf_path: Optional[str] = None  # Vision 호출 시 사용할 PDF 경로


def _is_ppt(source_path: str, parse_result: ParseResult) -> bool:
    """원본이 PPT/PPTX 인지 판정. 변환 메타도 함께 확인.

    GPT-5 P1-7 — converted_from 대소문자 무관 비교 ("PPTX"/"Pptx" 도 매칭).
    """
    ext = os.path.splitext(source_path or "")[1].lower()
    if ext in _PPT_EXTS:
        return True
    converted_from_raw = (parse_result.metadata or {}).get("converted_from", "")
    converted_from = str(converted_from_raw).strip().lower()
    return converted_from in ("pptx", "ppt")


def _resolve_pdf_path(source_path: str, parse_result: ParseResult) -> Optional[str]:
    """Vision 파이프라인 입력으로 사용할 PDF 경로를 결정한다.

    1) 원본이 PDF 면 source_path 그대로
    2) 변환된 임시 PDF 가 있으면 (`parse_result.pdf_path`) 그 경로
    3) 둘 다 없으면 None (Vision 호출 불가)
    """
    if source_path and source_path.lower().endswith(_PDF_EXTS):
        return source_path
    if parse_result.pdf_path and os.path.isfile(parse_result.pdf_path):
        return parse_result.pdf_path
    return None


def _scanned_pages_ratio(parse_result: ParseResult) -> float:
    """ocr_used=True 페이지 비율."""
    pages = parse_result.pages or []
    if not pages:
        return 0.0
    scanned = sum(1 for p in pages if getattr(p, "ocr_used", False))
    return scanned / len(pages)


def decide_vision(parse_result: ParseResult, source_path: str) -> VisionDecision:
    """Vision 파이프라인 사용 여부를 결정한다.

    Args:
        parse_result: 파서가 반환한 결과.
        source_path: 원본 문서 경로 (확장자 판정용).

    Returns:
        VisionDecision — 호출자는 use_vision/is_ppt 를 보고 분기.
    """
    is_ppt = _is_ppt(source_path, parse_result)
    pdf_path = _resolve_pdf_path(source_path, parse_result)

    # PPT 는 항상 Vision (PDF 가 준비된 경우에만)
    if is_ppt:
        if pdf_path is None:
            return VisionDecision(
                use_vision=False,
                reason="ppt_no_converted_pdf",
                is_ppt=True,
            )
        return VisionDecision(
            use_vision=True,
            reason="ppt_full_context",
            is_ppt=True,
            pdf_path=pdf_path,
        )

    # PDF 가 아니면 텍스트 경로
    if pdf_path is None:
        return VisionDecision(use_vision=False, reason="not_pdf")

    # PDF — 품질 게이트
    raw_text = parse_result.raw_text or ""
    broken_ratio = detect_broken_text_ratio(raw_text)
    doubling_runs = detect_glyph_doubling_runs(raw_text)
    scanned_ratio = _scanned_pages_ratio(parse_result)

    base_kwargs = dict(
        broken_ratio=round(broken_ratio, 4),
        scanned_ratio=round(scanned_ratio, 4),
        glyph_doubling_runs=doubling_runs,
        pdf_path=pdf_path,
    )

    # KMS-Plus 2026-05-07 — 풀옵션 모드 (env): PDF 전부 vision.
    # 표/그림 첨부 응답 시 caption/OCR 필수라 깨끗한 PDF 도 vision 으로 강제.
    if _force_vision_for_pdfs():
        return VisionDecision(
            use_vision=True, reason="pdf_full_option_env", **base_kwargs
        )

    if broken_ratio >= BROKEN_RATIO_THRESHOLD:
        return VisionDecision(use_vision=True, reason="broken_text", **base_kwargs)
    if doubling_runs >= GLYPH_DOUBLING_RUNS_THRESHOLD:
        return VisionDecision(use_vision=True, reason="glyph_doubling", **base_kwargs)
    if scanned_ratio >= SCANNED_RATIO_THRESHOLD:
        return VisionDecision(use_vision=True, reason="scanned_pdf", **base_kwargs)

    return VisionDecision(
        use_vision=False, reason="text_path_clean_pdf", **base_kwargs
    )
