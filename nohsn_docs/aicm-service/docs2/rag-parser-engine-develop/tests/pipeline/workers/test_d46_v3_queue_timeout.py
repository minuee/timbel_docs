"""D46-v3 §3-a — pipeline_queue_timeout 비례 (clamp + size=0 fallback) tests.

회귀 가드:
- None / empty path → MIN_SEC (1800).
- OSError (non-existent) → MIN_SEC fallback.
- size=0 (lazy MinIO/S3) → MIN_SEC fallback.
- 작은 파일 → min-clamp to MIN_SEC.
- 큰 파일 → max-clamp to MAX_SEC.
- 중간 파일 → 비례 적용 (clamp 내).
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_compute_queue_timeout_none_returns_min() -> None:
    from src.pipeline.workers.main import (
        PIPELINE_QUEUE_TIMEOUT_MIN_SEC,
        _compute_queue_timeout,
    )
    assert _compute_queue_timeout(None) == PIPELINE_QUEUE_TIMEOUT_MIN_SEC


def test_compute_queue_timeout_empty_returns_min() -> None:
    from src.pipeline.workers.main import (
        PIPELINE_QUEUE_TIMEOUT_MIN_SEC,
        _compute_queue_timeout,
    )
    assert _compute_queue_timeout("") == PIPELINE_QUEUE_TIMEOUT_MIN_SEC


def test_compute_queue_timeout_nonexistent_path_returns_min() -> None:
    """OSError 경로 — fallback to MIN_SEC."""
    from src.pipeline.workers.main import (
        PIPELINE_QUEUE_TIMEOUT_MIN_SEC,
        _compute_queue_timeout,
    )
    assert (
        _compute_queue_timeout("/non/existent/path/zzz.pdf")
        == PIPELINE_QUEUE_TIMEOUT_MIN_SEC
    )


def test_compute_queue_timeout_zero_size_returns_min(tmp_path: Path) -> None:
    """size=0 (lazy key 시뮬레이션) → MIN_SEC fallback."""
    from src.pipeline.workers.main import (
        PIPELINE_QUEUE_TIMEOUT_MIN_SEC,
        _compute_queue_timeout,
    )
    empty_file = tmp_path / "empty.bin"
    empty_file.write_bytes(b"")
    assert (
        _compute_queue_timeout(str(empty_file))
        == PIPELINE_QUEUE_TIMEOUT_MIN_SEC
    )


def test_compute_queue_timeout_small_file_clamps_to_min(tmp_path: Path) -> None:
    """1KB → BASE+per_page 결과 < MIN_SEC → min-clamp."""
    from src.pipeline.workers.main import (
        PIPELINE_QUEUE_TIMEOUT_MIN_SEC,
        _compute_queue_timeout,
    )
    small = tmp_path / "small.txt"
    small.write_bytes(b"x" * 1024)  # 1KB
    # BASE 600 + (0.001 MB × 5 pages × 30s) ≈ 600.15 → clamp to MIN 1800.
    assert (
        _compute_queue_timeout(str(small))
        == PIPELINE_QUEUE_TIMEOUT_MIN_SEC
    )


def test_compute_queue_timeout_large_file_clamps_to_max(tmp_path: Path) -> None:
    """100MB → 7500+ → max-clamp to MAX_SEC."""
    from src.pipeline.workers.main import (
        PIPELINE_QUEUE_TIMEOUT_MAX_SEC,
        _compute_queue_timeout,
    )
    large = tmp_path / "large.bin"
    # 100 MB 짜리 파일 — write with seek (sparse) 또는 truncate.
    with open(large, "wb") as f:
        f.truncate(100 * 1024 * 1024)
    # BASE 600 + (100 × 5 × 30) = 15600 → clamp MAX 7200.
    assert (
        _compute_queue_timeout(str(large))
        == PIPELINE_QUEUE_TIMEOUT_MAX_SEC
    )


def test_compute_queue_timeout_medium_file_proportional(tmp_path: Path) -> None:
    """10MB → 600 + (10 × 5 × 30) = 2100 → clamp 내, 그대로."""
    from src.pipeline.workers.main import _compute_queue_timeout
    medium = tmp_path / "med.bin"
    with open(medium, "wb") as f:
        f.truncate(10 * 1024 * 1024)
    val = _compute_queue_timeout(str(medium))
    # 600 + 1500 = 2100 (between MIN 1800 and MAX 7200).
    assert 2000 <= val <= 2200, f"got {val}"
