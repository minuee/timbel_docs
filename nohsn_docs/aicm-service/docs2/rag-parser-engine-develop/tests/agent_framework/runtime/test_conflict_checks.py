"""Phase 1.5A Task 4 — ConflictCheck registry + 4 표준 checker 테스트.

mock 기반 단위 테스트. 실제 DB / Redis 미접근.
"""
from __future__ import annotations

import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.agent_framework.runtime.conflict_checks import (
    register,
    get,
    ConflictResult,
    schedule_overlap_check,
    mail_recent_duplicate_check,
    expense_recent_duplicate_check,
    memo_recent_duplicate_check,
)
from src.agent_framework.tools.outcomes import ToolOutcome
from src.agent_framework.runtime.sender_context import SenderContext


@pytest.fixture
def sender():
    return SenderContext(
        tier="verified",
        internal_user_id=uuid4(),
        tenant_id=uuid4(),
        channel_kind="web",
        verified_via="login",
        confirm_token=None,
    )


def test_registry_register_and_get():
    class FakeCheck:
        name = "fake_check"

        async def check(self, tool, args, sender, db, **extra):
            return ConflictResult(
                has_conflict=False, outcome=ToolOutcome.OK, reason=""
            )

    register("fake_check", FakeCheck())
    assert get("fake_check") is not None
    assert get("nonexistent") is None


@pytest.mark.asyncio
async def test_schedule_overlap_no_conflict(sender):
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[])  # 충돌 없음
    db.execute = AsyncMock(return_value=mock_result)

    args = {
        "title": "약속",
        "start_at": datetime(2026, 5, 7, 14, 0, tzinfo=timezone.utc),
        "end_at": datetime(2026, 5, 7, 15, 0, tzinfo=timezone.utc),
    }
    result = await schedule_overlap_check.check(
        "schedule.create", args, sender, db
    )
    assert result.has_conflict is False
    assert result.outcome == ToolOutcome.OK


@pytest.mark.asyncio
async def test_schedule_overlap_with_conflict(sender):
    db = AsyncMock()
    mock_existing = MagicMock()
    mock_existing.start_at = datetime(2026, 5, 7, 14, 30, tzinfo=timezone.utc)
    mock_existing.end_at = datetime(2026, 5, 7, 15, 30, tzinfo=timezone.utc)
    mock_existing.title = "기존 일정"
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[(mock_existing,)])
    db.execute = AsyncMock(return_value=mock_result)

    args = {
        "title": "새 약속",
        "start_at": datetime(2026, 5, 7, 14, 0, tzinfo=timezone.utc),
        "end_at": datetime(2026, 5, 7, 15, 0, tzinfo=timezone.utc),
    }
    result = await schedule_overlap_check.check(
        "schedule.create", args, sender, db
    )
    assert result.has_conflict is True
    assert result.outcome == ToolOutcome.CONFLICT
    assert result.reason == "schedule_overlap"


@pytest.mark.asyncio
async def test_mail_recent_duplicate_via_redis(sender):
    """Redis 캐시 기반 — 60s 내 동일 sender×recipient×subject 차단."""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=1)  # 이미 존재
    args = {"to": ["a@example.com"], "subject": "test", "body": "..."}

    db = AsyncMock()
    result = await mail_recent_duplicate_check.check(
        "mail.send", args, sender, db, redis=redis
    )
    assert result.has_conflict is True
    assert result.outcome == ToolOutcome.COOLDOWN


@pytest.mark.asyncio
async def test_expense_duplicate_within_5min(sender):
    db = AsyncMock()
    mock_recent = MagicMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[(mock_recent,)])
    db.execute = AsyncMock(return_value=mock_result)

    args = {
        "amount": 5000,
        "category": "식비",
        "spent_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await expense_recent_duplicate_check.check(
        "expense.create", args, sender, db
    )
    assert result.has_conflict is True
    assert result.outcome == ToolOutcome.DUPLICATE


@pytest.mark.asyncio
async def test_memo_duplicate_within_1min(sender):
    db = AsyncMock()
    mock_recent = MagicMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[(mock_recent,)])
    db.execute = AsyncMock(return_value=mock_result)

    args = {"content": "테스트 메모"}
    result = await memo_recent_duplicate_check.check(
        "memo.create", args, sender, db
    )
    assert result.has_conflict is True
    assert result.outcome == ToolOutcome.DUPLICATE
