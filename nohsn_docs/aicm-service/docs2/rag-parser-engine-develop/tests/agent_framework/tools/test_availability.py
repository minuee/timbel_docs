# tests/agent_framework/tools/test_availability.py
import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from src.agent_framework.tools.availability import (
    schedule_availability, schedule_suggest_slots,
)
from src.agent_framework.tools.outcomes import ToolOutcome


@pytest.mark.asyncio
async def test_availability_yes():
    """그 시간 비어있으면 available=true."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[])  # 충돌 record 없음
    db.execute = AsyncMock(return_value=mock_result)

    result = await schedule_availability(
        db=db, tenant_id=uuid4(),
        start=datetime(2026, 5, 7, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 7, 15, 0, tzinfo=timezone.utc),
        target_user_id=None,
    )
    assert result.success is True
    assert result.meta.outcome == ToolOutcome.OK
    assert result.items == [{"available": True}]


@pytest.mark.asyncio
async def test_availability_no():
    """그 시간 충돌 있으면 available=false."""
    db = AsyncMock()
    mock_existing = MagicMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[(mock_existing,)])
    db.execute = AsyncMock(return_value=mock_result)

    result = await schedule_availability(
        db=db, tenant_id=uuid4(),
        start=datetime(2026, 5, 7, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 7, 15, 0, tzinfo=timezone.utc),
        target_user_id=None,
    )
    assert result.success is True
    assert result.items == [{"available": False}]


@pytest.mark.asyncio
async def test_suggest_slots_returns_2_random():
    """빈 슬롯 5개 발견 → 무작위 2개만 반환 (n_suggestions=2)."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[])  # 모든 슬롯 비어있음
    db.execute = AsyncMock(return_value=mock_result)

    result = await schedule_suggest_slots(
        db=db, tenant_id=uuid4(),
        start=datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc),
        duration_minutes=60,
        target_user_id=None,
        n_suggestions=2,
    )
    assert result.success is True
    assert result.meta.outcome == ToolOutcome.OK
    assert len(result.items) == 2  # 정확히 2개


@pytest.mark.asyncio
async def test_suggest_slots_saturated():
    """모든 슬롯이 다 차있으면 outcome=saturated, items=[]."""
    db = AsyncMock()
    # mock — start..end 의 모든 시간대가 충돌 record 있음

    async def fake_execute(stmt):
        m = MagicMock()
        # 항상 record 있음
        m.all = MagicMock(return_value=[(MagicMock(),)])
        return m
    db.execute = AsyncMock(side_effect=fake_execute)

    result = await schedule_suggest_slots(
        db=db, tenant_id=uuid4(),
        start=datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc),
        duration_minutes=60,
        n_suggestions=2,
    )
    assert result.success is True
    assert result.meta.outcome == ToolOutcome.SATURATED
    assert result.items == []


@pytest.mark.asyncio
async def test_suggest_slots_partial():
    """1개만 가능 → outcome=partial, items=1."""
    db = AsyncMock()
    call_count = [0]
    async def fake_execute(stmt):
        m = MagicMock()
        # 첫 호출만 비어있음, 나머지는 충돌
        if call_count[0] == 0:
            m.all = MagicMock(return_value=[])
        else:
            m.all = MagicMock(return_value=[(MagicMock(),)])
        call_count[0] += 1
        return m
    db.execute = AsyncMock(side_effect=fake_execute)

    result = await schedule_suggest_slots(
        db=db, tenant_id=uuid4(),
        start=datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc),
        duration_minutes=60,
        n_suggestions=2,
    )
    assert result.success is True
    assert result.meta.outcome == ToolOutcome.PARTIAL
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_suggest_slots_default_duration():
    """duration_minutes=None → SOP 미공급 시 default 30."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=mock_result)

    result = await schedule_suggest_slots(
        db=db, tenant_id=uuid4(),
        start=datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
        duration_minutes=None,
        n_suggestions=2,
    )
    assert result.success is True
    # 30분 단위 기본 → 9-12 사이 6 슬롯, 2 개 노출
    assert len(result.items) == 2
