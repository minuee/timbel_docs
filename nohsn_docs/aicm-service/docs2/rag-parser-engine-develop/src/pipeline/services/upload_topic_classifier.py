"""D48 §1 — 업로드 시점 small/large 큐 분류기.

설계 요약
=========
- 기본 전략: format-aware 우선 규칙 + file_size 임계 (binary MiB).
- text-only (.md/.txt/.csv) → 항상 small (텍스트 비용 낮음).
- scan-style (.tif/.tiff) / 동영상 (.mp4/.mov/.avi) → 항상 large.
- 그 외 포맷 (PDF / PPT / DOCX / XLSX 등) → file_size 임계 기준.
- env `PIPELINE_LARGE_TOPIC_ENABLED=false` 시 legacy `aicm.document.uploaded` 사용
  (rollback path).
- env `PIPELINE_SMALL_SIZE_MB_THRESHOLD` (default 2) 로 임계 조정.

본 모듈은 순수 함수만 노출 — DB / Kafka 의존 없음. 테스트 용이.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.common.constants import (
    TOPIC_DOCUMENT_UPLOADED,
    TOPIC_DOCUMENT_UPLOADED_LARGE,
    TOPIC_DOCUMENT_UPLOADED_SMALL,
)

# 1 MiB (binary). MB 라는 변수명을 유지하지만 비교는 binary MiB.
_MIB = 1_048_576

# 항상 small 로 분류 — 텍스트 처리 비용이 size 와 무관하게 낮음.
_TEXT_ONLY_EXTS = frozenset({".md", ".txt", ".csv", ".log"})

# 항상 large 로 분류 — 스캔/동영상/대형 raster.
_ALWAYS_LARGE_EXTS = frozenset(
    {".tif", ".tiff", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
)


@dataclass(frozen=True)
class UploadTopicDecision:
    """업로드 시점 분류 결과."""

    topic: str
    profile: str  # "small" | "large" | "legacy"
    reason: str
    threshold_mib: float
    file_size_bytes: int


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


def _normalize_ext(source_path: str | None) -> str:
    """파일 확장자를 소문자 정규화."""
    if not source_path:
        return ""
    base = source_path.rsplit("/", 1)[-1]
    if "." not in base:
        return ""
    return "." + base.rsplit(".", 1)[-1].lower()


def classify_upload_topic(
    *,
    file_size_bytes: int | None,
    source_path: str | None,
    source_format: str | None = None,
) -> UploadTopicDecision:
    """업로드 이벤트를 small/large/legacy 토픽으로 분류한다.

    Args:
        file_size_bytes: 업로드 파일 크기 (bytes). None 이면 임계 비교 skip.
        source_path: 원본 파일 경로 (확장자 판정).
        source_format: 파서 식별자 (현재 미사용, 미래 호환).

    Returns:
        UploadTopicDecision — `topic` 으로 Kafka 발행.

    Notes:
        - `PIPELINE_LARGE_TOPIC_ENABLED=false` 시 legacy 토픽 사용 (rollback).
        - file_size 미상 (None / <= 0) 시 보수적으로 small 분류 (legacy 동작 유지).
    """
    threshold_mib = max(0.1, _env_float("PIPELINE_SMALL_SIZE_MB_THRESHOLD", 2.0))
    large_enabled = _env_bool("PIPELINE_LARGE_TOPIC_ENABLED", True)
    size_bytes = max(0, int(file_size_bytes or 0))

    if not large_enabled:
        return UploadTopicDecision(
            topic=TOPIC_DOCUMENT_UPLOADED,
            profile="legacy",
            reason="large_topic_disabled",
            threshold_mib=threshold_mib,
            file_size_bytes=size_bytes,
        )

    ext = _normalize_ext(source_path)

    # 1) 포맷 우선 규칙
    if ext in _TEXT_ONLY_EXTS:
        return UploadTopicDecision(
            topic=TOPIC_DOCUMENT_UPLOADED_SMALL,
            profile="small",
            reason="text_only_format",
            threshold_mib=threshold_mib,
            file_size_bytes=size_bytes,
        )
    if ext in _ALWAYS_LARGE_EXTS:
        return UploadTopicDecision(
            topic=TOPIC_DOCUMENT_UPLOADED_LARGE,
            profile="large",
            reason="scan_or_video_format",
            threshold_mib=threshold_mib,
            file_size_bytes=size_bytes,
        )

    # 2) file_size 임계
    threshold_bytes = int(threshold_mib * _MIB)
    if size_bytes <= 0:
        return UploadTopicDecision(
            topic=TOPIC_DOCUMENT_UPLOADED_SMALL,
            profile="small",
            reason="size_unknown_default_small",
            threshold_mib=threshold_mib,
            file_size_bytes=size_bytes,
        )
    if size_bytes >= threshold_bytes:
        return UploadTopicDecision(
            topic=TOPIC_DOCUMENT_UPLOADED_LARGE,
            profile="large",
            reason="size_above_threshold",
            threshold_mib=threshold_mib,
            file_size_bytes=size_bytes,
        )
    return UploadTopicDecision(
        topic=TOPIC_DOCUMENT_UPLOADED_SMALL,
        profile="small",
        reason="size_below_threshold",
        threshold_mib=threshold_mib,
        file_size_bytes=size_bytes,
    )
