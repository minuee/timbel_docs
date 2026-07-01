"""Task 19 — scheduled_init 상태 수동 발화 테스트.

CronRunner 실시간 발화는 `test_cron_runner.py` 에서 interval로 커버.
여기서는 _fire_scheduled_skill 이 구독자 뉴스 요약 tool 을 실행하는지 확인.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools.registry import ToolRegistry
from src.agent_framework.tools import news_store


@pytest.mark.asyncio
async def test_scheduled_fire_executes_news_fetch(redis_client):
    news_store._reset()
    # 구독자 1명 시뮬레이션 (Redis 경로)
    await news_store.add_subscription({"phone": "010-subscriber", "topic": "AI 스타트업"})

    intent = AsyncMock()
    slot_filler = AsyncMock()
    response_gen = MagicMock()
    fallback = AsyncMock()

    engine = AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry({
            "news.add_subscription": news_store.add_subscription,
            "news.fetch_and_summarize": news_store.fetch_and_summarize,
        }),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    # 직접 _fire_scheduled_skill 호출 (cron 생략)
    await engine._fire_scheduled_skill("news_daily_report")

    # 구독자의 _RECENT_REPORTS 에 엔트리 1개 추가됐어야 함
    reports = await news_store.list_recent_reports({"phone": "010-subscriber"})
    assert len(reports["reports"]) == 1
    assert "AI 스타트업" in reports["reports"][0]["topics"]


@pytest.mark.asyncio
async def test_scheduled_fire_skips_skill_without_scheduled_init_state(redis_client):
    """appointment_derm 은 scheduled_init state 없음 → 경고 로그 + 무동작."""
    intent = AsyncMock()
    slot_filler = AsyncMock()
    response_gen = MagicMock()
    fallback = AsyncMock()

    engine = AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry({}),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    # 예외 없이 반환해야 함 (로그만 남김)
    await engine._fire_scheduled_skill("appointment_derm")
