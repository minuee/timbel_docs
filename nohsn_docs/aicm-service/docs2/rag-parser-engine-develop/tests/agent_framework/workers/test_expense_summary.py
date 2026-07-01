"""expense_summary worker — 테이블 부재 시 graceful 0 반환."""
from __future__ import annotations

import pytest
import pytest_asyncio

from src.agent_framework.workers import expense_summary, feed_compose
from src.api.routers import auth_v2


@pytest_asyncio.fixture
async def reset_engine():
    await auth_v2._reset_engine_for_tests()
    await feed_compose._reset_engine_for_tests()
    yield
    await auth_v2._reset_engine_for_tests()
    await feed_compose._reset_engine_for_tests()


@pytest.mark.asyncio
async def test_run_once_returns_int(reset_engine):
    n = await expense_summary.run_once()
    assert isinstance(n, int)
    assert n >= 0


@pytest.mark.asyncio
async def test_expense_summary_daily_returns_int(reset_engine):
    n = await expense_summary.expense_summary_daily()
    assert isinstance(n, int)
