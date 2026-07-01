"""D46-v3 §3-b — merge_worker mark_part_completed transient retry tests.

검증:
- 첫 호출 성공 → 0 retry.
- transient ValueError ("Split job not found") → retry, 3 번째 attempt 성공.
- 모든 attempt transient 실패 → 최종 raise (silent return 0).
- non-transient ValueError → 즉시 raise (retry 무).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


pytestmark = pytest.mark.asyncio


async def test_first_attempt_success_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 경로 — 첫 attempt 에서 성공, retry 없음."""
    from src.pipeline.workers.merge_worker import _try_mark_part_completed_with_retry

    tracker = MagicMock()
    fake_job = MagicMock()
    tracker.mark_part_completed = AsyncMock(return_value=fake_job)

    # asyncio.sleep 을 no-op 으로 모킹 (테스트 속도).
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await _try_mark_part_completed_with_retry(
        tracker, uuid4(), 0, "doc-1"
    )
    assert result is fake_job
    assert tracker.mark_part_completed.await_count == 1


async def test_transient_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """transient ValueError → retry → 3 번째 attempt 성공."""
    from src.pipeline.workers.merge_worker import _try_mark_part_completed_with_retry

    tracker = MagicMock()
    fake_job = MagicMock()
    tracker.mark_part_completed = AsyncMock(
        side_effect=[
            ValueError("Split job not found: doc-2"),
            ValueError("Split job not found: doc-2"),
            fake_job,
        ]
    )
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await _try_mark_part_completed_with_retry(
        tracker, uuid4(), 0, "doc-2"
    )
    assert result is fake_job
    assert tracker.mark_part_completed.await_count == 3


async def test_non_transient_value_error_immediate_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """non-transient ValueError → 즉시 raise (retry 없음)."""
    from src.pipeline.workers.merge_worker import _try_mark_part_completed_with_retry

    tracker = MagicMock()
    tracker.mark_part_completed = AsyncMock(
        side_effect=ValueError("이미 완료된 part: doc-3")
    )
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(ValueError, match="이미 완료"):
        await _try_mark_part_completed_with_retry(
            tracker, uuid4(), 0, "doc-3"
        )
    # 즉시 raise — 1 호출만.
    assert tracker.mark_part_completed.await_count == 1


async def test_all_attempts_transient_final_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모든 8 attempts transient → 최종 raise (silent return X)."""
    from src.pipeline.workers.merge_worker import (
        _MERGE_RETRY_DELAYS_SEC,
        _try_mark_part_completed_with_retry,
    )

    tracker = MagicMock()
    # 8 attempts = initial(1) + retries(7).
    tracker.mark_part_completed = AsyncMock(
        side_effect=ValueError("Split job not found: doc-4")
    )
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(ValueError, match="Split job not found"):
        await _try_mark_part_completed_with_retry(
            tracker, uuid4(), 0, "doc-4"
        )
    # initial(1) + len(retries)(7) = 8 attempts.
    assert tracker.mark_part_completed.await_count == 1 + len(_MERGE_RETRY_DELAYS_SEC)


async def test_metric_incremented_on_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    """transient retry 시 inc_kms_pipeline_merge_part_retry 호출.

    Note: src.common.metrics 모듈은 import 시 Prometheus Counter 들을 등록하므로
    full test suite 환경에서는 이미 import 되어 있음. monkeypatch.setattr 의
    target 으로 sys.modules 캐시 모듈 객체에 직접 setattr.
    """
    import sys
    from src.pipeline.workers.merge_worker import _try_mark_part_completed_with_retry

    tracker = MagicMock()
    fake_job = MagicMock()
    tracker.mark_part_completed = AsyncMock(
        side_effect=[
            ValueError("Split job not found: doc-5"),
            fake_job,
        ]
    )
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    metric_calls: list[int] = []

    def fake_inc() -> None:
        metric_calls.append(1)

    # 이미 import 된 module 객체에 setattr — re-import 시 ValueError 회피.
    metrics_mod = sys.modules.get("src.common.metrics")
    if metrics_mod is None:
        import src.common.metrics as metrics_mod  # type: ignore[no-redef]
    monkeypatch.setattr(metrics_mod, "inc_kms_pipeline_merge_part_retry", fake_inc)

    result = await _try_mark_part_completed_with_retry(
        tracker, uuid4(), 0, "doc-5"
    )
    assert result is fake_job
    assert len(metric_calls) == 1  # 1 transient retry.
