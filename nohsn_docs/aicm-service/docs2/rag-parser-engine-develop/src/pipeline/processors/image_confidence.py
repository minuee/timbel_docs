"""D48 §2 — OCR + Vision 통합 신뢰도 점수.

핵심 설계
=========
- OCR text + Vision caption 둘 다 존재 → 토큰 jaccard + (low score 시) char 3-gram fallback
- OCR 만 / Vision 만 → 단독 score (길이 + lang 일치)
- 둘 다 부재 → is_decorative=true (logo 추정)
- label: high (>=0.75) / medium (0.4~0.75) / low (<0.4)

본 모듈은 **기록만** — block metadata 에 score / label / preview / ref 저장.
실제 retrieval boost-down 은 별 PR.

JSONB TOAST 폭주 방지:
- preview 는 IMAGE_CONFIDENCE_MAX_TEXT_CHARS (default 2048) 까지만
- 초과분은 MinIO `kms-intermediate/image_confidence/{document_id}/{block_id}-{kind}.txt` 저장
- metadata 에 *_ref (key path) 만 저장
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional


_HIGH_THRESHOLD_DEFAULT = 0.75
_MEDIUM_THRESHOLD_DEFAULT = 0.40
_LOW_SCORE_FOR_FALLBACK_DEFAULT = 0.10  # jaccard < 임계 → char n-gram 으로 재시도
_NGRAM_SIZE_DEFAULT = 3
_MIN_LANG_MATCH_BOOST_DEFAULT = 0.10
_PER_PAGE_FALLBACK_PDF_DEFAULT = 30.0
_PER_PAGE_FALLBACK_PPT_DEFAULT = 40.0
_REF_PREFIX_DEFAULT = "kms-intermediate/image_confidence"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = raw.strip()
    return val or default


# ---------------------------------------------------------------------------
# 임계값 resolver (env override 모든 항목)
# ---------------------------------------------------------------------------


def _resolve_thresholds() -> dict:
    return {
        "high": _env_float("IMAGE_CONFIDENCE_HIGH_THRESHOLD", _HIGH_THRESHOLD_DEFAULT),
        "medium": _env_float("IMAGE_CONFIDENCE_MEDIUM_THRESHOLD", _MEDIUM_THRESHOLD_DEFAULT),
        "low_fallback": _env_float(
            "IMAGE_CONFIDENCE_LOW_FALLBACK_THRESHOLD", _LOW_SCORE_FOR_FALLBACK_DEFAULT
        ),
        "ngram_size": max(2, int(_env_int("IMAGE_CONFIDENCE_NGRAM_SIZE", _NGRAM_SIZE_DEFAULT))),
        "lang_boost": _env_float(
            "IMAGE_CONFIDENCE_LANG_MATCH_BOOST", _MIN_LANG_MATCH_BOOST_DEFAULT
        ),
    }


@dataclass(frozen=True)
class ImageConfidence:
    """OCR + Vision 통합 신뢰도 결과."""

    score: float
    label: str  # "high" | "medium" | "low" | "decorative"
    ocr_present: bool
    vision_present: bool
    agreement: float
    is_decorative: bool
    ocr_preview: Optional[str]
    vision_preview: Optional[str]
    ocr_needs_ref: bool
    vision_needs_ref: bool
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# 텍스트 정규화 / 토큰
# ---------------------------------------------------------------------------

_NORMALIZE_RE = re.compile(r"[^\w\s가-힣]+", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


def _normalize(text: str) -> str:
    """기호/구두점 제거 + 소문자 + 공백 normalize. 숫자/한글 보존."""
    if not text:
        return ""
    # 날짜 구분 정규화 (2026-05-11 vs 2026/5/11)
    text = re.sub(r"(\d+)[\-./](\d+)[\-./](\d+)", r"\1 \2 \3", text)
    text = _NORMALIZE_RE.sub(" ", text.lower())
    text = _WS_RE.sub(" ", text).strip()
    return text


def _tokenize(text: str) -> set[str]:
    norm = _normalize(text)
    if not norm:
        return set()
    return set(norm.split())


def _char_ngrams(text: str, n: int = _NGRAM_SIZE_DEFAULT) -> set[str]:
    norm = _normalize(text).replace(" ", "")
    if len(norm) < n:
        return {norm} if norm else set()
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _detect_language(text: str) -> str:
    """간단 lang 판정: hangul / latin / mixed / other."""
    if not text:
        return "none"
    has_hangul = bool(re.search(r"[가-힣]", text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))
    if has_hangul and has_latin:
        return "mixed"
    if has_hangul:
        return "hangul"
    if has_latin:
        return "latin"
    return "other"


# ---------------------------------------------------------------------------
# 메인 점수 함수
# ---------------------------------------------------------------------------


def _build_preview(text: Optional[str], max_chars: int) -> tuple[Optional[str], bool]:
    """text 가 max_chars 초과 시 preview + needs_ref=True, 아니면 그대로 + False."""
    if text is None:
        return None, False
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "...", True


def _score_pair(
    ocr_text: str, vision_text: str, thresholds: dict
) -> tuple[float, float, bool]:
    """OCR + Vision 둘 다 있는 경우 score + agreement + fallback_used."""
    ocr_tok = _tokenize(ocr_text)
    vis_tok = _tokenize(vision_text)
    j_score = _jaccard(ocr_tok, vis_tok)
    fallback = False
    if j_score < thresholds["low_fallback"]:
        # char n-gram 재시도 (한-영 혼용 / 짧은 텍스트 대응)
        ocr_ng = _char_ngrams(ocr_text, thresholds["ngram_size"])
        vis_ng = _char_ngrams(vision_text, thresholds["ngram_size"])
        ng_score = _jaccard(ocr_ng, vis_ng)
        if ng_score > j_score:
            j_score = ng_score
            fallback = True
    # lang 일치 시 약간 boost
    if _detect_language(ocr_text) == _detect_language(vision_text):
        agreement = min(1.0, j_score + thresholds["lang_boost"])
    else:
        agreement = j_score
    score = agreement
    return score, agreement, fallback


def _score_single(text: str) -> float:
    """한쪽만 있는 경우 — 길이 + lang detect 기반 score."""
    norm = _normalize(text)
    if not norm:
        return 0.0
    # 5 chars 이하 → low (decorative 가능성), 30 chars 이상 → 0.5+ saturate
    length = len(norm)
    if length < 5:
        return 0.15
    if length < 15:
        return 0.30
    if length < 30:
        return 0.45
    return 0.55  # 단독 vision/ocr 만으로는 0.55 cap (vision/OCR 비교 없이 high 불가)


def score_image_confidence(
    *,
    ocr_text: Optional[str],
    vision_caption: Optional[str],
    image_pixels: Optional[int] = None,
) -> ImageConfidence:
    """OCR + Vision 통합 신뢰도 점수.

    Args:
        ocr_text: OCR 추출 텍스트 (None 또는 빈 문자열 가능).
        vision_caption: Vision LLM caption (동상).
        image_pixels: 이미지 width*height (decorative 추정용, 선택).

    Returns:
        ImageConfidence — block.metadata 에 직접 저장 가능한 dataclass.
    """
    # 비정상 max_chars (0/음수) 방어 — 최소 64
    max_chars = max(64, _env_int("IMAGE_CONFIDENCE_MAX_TEXT_CHARS", 2048))
    decorative_min_area = max(
        1, _env_int("IMAGE_CONFIDENCE_DECORATIVE_MIN_AREA", 5000)
    )
    thresholds = _resolve_thresholds()

    ocr_clean = (ocr_text or "").strip()
    vis_clean = (vision_caption or "").strip()
    ocr_present = bool(ocr_clean)
    vision_present = bool(vis_clean)

    # decorative 판정 — 둘 다 부재 + (이미지 픽셀 미상 또는 작음)
    # 픽셀 미상 (None) 시 보수적으로 decorative (logo 가능성).
    if not ocr_present and not vision_present:
        is_decorative = (
            image_pixels is None or image_pixels < decorative_min_area
        )
        return ImageConfidence(
            score=0.0,
            label="decorative" if is_decorative else "low",
            ocr_present=False,
            vision_present=False,
            agreement=0.0,
            is_decorative=is_decorative,
            ocr_preview=None,
            vision_preview=None,
            ocr_needs_ref=False,
            vision_needs_ref=False,
            fallback_used=False,
        )

    fallback_used = False
    if ocr_present and vision_present:
        score, agreement, fallback_used = _score_pair(
            ocr_clean, vis_clean, thresholds
        )
    elif ocr_present:
        score = _score_single(ocr_clean)
        agreement = 0.0
    else:
        score = _score_single(vis_clean)
        agreement = 0.0

    # 반올림 일관성 — score 를 먼저 반올림 후 label 판정. 회귀 0.
    score_rounded = round(score, 4)
    if score_rounded >= thresholds["high"]:
        label = "high"
    elif score_rounded >= thresholds["medium"]:
        label = "medium"
    else:
        label = "low"
    score = score_rounded

    ocr_preview, ocr_needs_ref = _build_preview(ocr_clean or None, max_chars)
    vision_preview, vision_needs_ref = _build_preview(vis_clean or None, max_chars)

    return ImageConfidence(
        score=round(score, 4),
        label=label,
        ocr_present=ocr_present,
        vision_present=vision_present,
        agreement=round(agreement, 4),
        is_decorative=False,
        ocr_preview=ocr_preview,
        vision_preview=vision_preview,
        ocr_needs_ref=ocr_needs_ref,
        vision_needs_ref=vision_needs_ref,
        fallback_used=fallback_used,
    )


def to_metadata_dict(
    confidence: ImageConfidence,
    *,
    document_id: Optional[str] = None,
    block_id: Optional[str] = None,
) -> dict:
    """ImageConfidence → block.metadata 에 머지할 dict.

    원문이 max_chars 초과 시 ref key (MinIO path) 만 포함.
    실제 MinIO 업로드는 호출 측 책임 (실패 시 ref=None).
    """
    md: dict = {
        "image_confidence_score": confidence.score,
        "image_confidence_label": confidence.label,
        "image_confidence_agreement": confidence.agreement,
        "is_decorative": confidence.is_decorative,
        "image_confidence_fallback_used": confidence.fallback_used,
    }
    if confidence.ocr_preview is not None:
        md["ocr_extracted_text_preview"] = confidence.ocr_preview
    if confidence.vision_preview is not None:
        md["vision_caption_preview"] = confidence.vision_preview
    prefix = _env_str("IMAGE_CONFIDENCE_REF_PREFIX", _REF_PREFIX_DEFAULT).rstrip("/")
    safe_doc = _sanitize_path_segment(document_id) if document_id else None
    safe_blk = _sanitize_path_segment(block_id) if block_id else None
    if confidence.ocr_needs_ref and safe_doc and safe_blk:
        md["ocr_extracted_text_ref"] = f"{prefix}/{safe_doc}/{safe_blk}-ocr.txt"
    if confidence.vision_needs_ref and safe_doc and safe_blk:
        md["vision_caption_ref"] = f"{prefix}/{safe_doc}/{safe_blk}-vision.txt"
    return md


_SAFE_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _sanitize_path_segment(seg: str, max_len: int = 128) -> str:
    """경로 주입 방지 — 화이트리스트 문자만 + 길이 제한."""
    if not seg:
        return ""
    cleaned = _SAFE_RE.sub("_", str(seg)).strip("_")
    return cleaned[:max_len] if cleaned else ""


def is_enabled() -> bool:
    """env IMAGE_CONFIDENCE_ENABLED (default true) 검사."""
    return _env_bool("IMAGE_CONFIDENCE_ENABLED", True)


# ---------------------------------------------------------------------------
# D48 §4 — progress / ETA 헬퍼 (Document.processing_meta.progress)
# ---------------------------------------------------------------------------


def compute_eta_seconds(
    *,
    estimated_blocks: Optional[int],
    page_count: Optional[int] = None,
    source_format: Optional[str] = None,
) -> int:
    """D44 회귀선 기반 ETA — 포맷별 계수 (PDF/PPT).

    Args:
        estimated_blocks: 추정 블록 수. None 시 page_count * per_page_fallback.
        page_count: 페이지/슬라이드 수.
        source_format: "pdf" / "pptx" / "ppt" / ... (대소문자 무관).

    Returns:
        ETA seconds (정수, 1 이상).

    env (모두 override 가능):
        ETA_BASE_SEC / ETA_PER_BLOCK_SEC (PDF)
        ETA_BASE_SEC_PPT / ETA_PER_BLOCK_SEC_PPT (PPT)
        ETA_PER_PAGE_FALLBACK_SEC / ETA_PER_PAGE_FALLBACK_SEC_PPT
    """
    fmt = (source_format or "").strip().lower()
    is_ppt = fmt in ("ppt", "pptx")
    if is_ppt:
        base_sec = _env_float("ETA_BASE_SEC_PPT", 240.0)
        per_block = _env_float("ETA_PER_BLOCK_SEC_PPT", 1.3)
        per_page_fallback = _env_float(
            "ETA_PER_PAGE_FALLBACK_SEC_PPT", _PER_PAGE_FALLBACK_PPT_DEFAULT
        )
    else:
        base_sec = _env_float("ETA_BASE_SEC", 176.0)  # 2.94 분 (D44)
        per_block = _env_float("ETA_PER_BLOCK_SEC", 0.81)
        per_page_fallback = _env_float(
            "ETA_PER_PAGE_FALLBACK_SEC", _PER_PAGE_FALLBACK_PDF_DEFAULT
        )

    if estimated_blocks is not None and estimated_blocks > 0:
        eta = base_sec + per_block * float(estimated_blocks)
    elif page_count is not None and page_count > 0:
        eta = float(page_count) * per_page_fallback
    else:
        eta = base_sec
    return max(1, int(eta))


def build_progress(
    *,
    current_part: int,
    total_parts: int,
    current_stage: str,
    stage_started_at_iso: str,
    elapsed_seconds: int,
    eta_seconds: int,
) -> dict:
    """processing_meta.progress 부분 갱신용 dict."""
    remaining = max(0, eta_seconds - elapsed_seconds)
    return {
        "current_part": int(current_part),
        "total_parts": int(total_parts),
        "current_stage": current_stage,
        "stage_started_at": stage_started_at_iso,
        "elapsed_seconds": int(elapsed_seconds),
        "eta_seconds": int(eta_seconds),
        "estimated_remaining_seconds": int(remaining),
    }


def progress_update_enabled() -> bool:
    """env PIPELINE_PROGRESS_UPDATE_ENABLED (default true)."""
    return _env_bool("PIPELINE_PROGRESS_UPDATE_ENABLED", True)
