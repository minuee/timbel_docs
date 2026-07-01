"""schedule_alert worker — schedules 테이블 미존재 시에도 graceful 0 반환.

설계상 schedules 테이블 컬럼은 환경에 따라 다를 수 있어 worker 가
information_schema 로 자동 탐지. 테이블이 아예 없으면 0 반환.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from src.agent_framework.workers import feed_compose, schedule_alert
from src.api.routers import auth_v2


@pytest_asyncio.fixture
async def reset_engine():
    """각 테스트 시작/종료 시 engine 을 reset — pool/event_loop 분리 보장."""
    await auth_v2._reset_engine_for_tests()
    await feed_compose._reset_engine_for_tests()
    yield
    await auth_v2._reset_engine_for_tests()
    await feed_compose._reset_engine_for_tests()


@pytest.mark.asyncio
async def test_run_once_no_schedules_table(reset_engine):
    """schedules 가 없거나 컬럼 매칭 실패 → 0 반환 (예외 X)."""
    n = await schedule_alert.run_once()
    assert isinstance(n, int)
    assert n >= 0


@pytest.mark.asyncio
async def test_schedule_alert_tick_returns_int(reset_engine):
    n = await schedule_alert.schedule_alert_tick()
    assert isinstance(n, int)
