"""Task 14 E2E — appointment_derm 스킬 happy path.

외부 LLM / Redis 는 모두 모킹 (redis 는 conftest fixture 로 실서버 DB 2 사용,
LLM 은 AsyncMock) 해 AgentEngine.turn() 이 스킬을 greet → collect_date 로
전이시키는지 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools import calendar_mock
from src.agent_framework.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_book_happy_path(redis_client):
    calendar_mock._reset()

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(
        side_effect=[
            ["book_appointment"],  # turn 1
            [],
            [],
            [],
        ]
    )

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(
        side_effect=[
            {"preferred_datetime": "2026-04-25T10:00"},
            {"preferred_doctor_id": "dr_kim"},
            {"preferred_service": "laser"},
        ]
    )

    async def stream_response(tpl, ctx, **kwargs):
        yield "응답"

    response_gen = MagicMock()
    response_gen.stream = stream_response

    from src.agent_framework.llm.fallback_router import FallbackDecision

    fallback = AsyncMock()
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    engine = AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    events: list[dict] = []
    async for evt in engine.turn("s1", "derm1", "예약하고 싶어요"):
        events.append(evt)

    states = [e for e in events if e["event"] == "state"]
    # 적어도 greet → collect_datetime 전이가 발생해야 한다 (Task 25-C v0.2)
    assert any(e["data"].get("state") == "collect_datetime" for e in states)


@pytest.mark.asyncio
async def test_skill_entry_silent_greet_advances_to_collect(redis_client):
    """2026-04-28 silent-greet 패턴 회귀.

    Task 14.6 의 옛 회귀(`greet.on_enter` 가 chatty greeting 송출)는 패턴
    불일치 — 한 turn 에 두 메시지(greeting ack + collect 응답) 가 보였고,
    사용자가 모든 정보를 한 발화에 줘도 chatty intro 후에 다시 묻기가
    발생했다. 이제 ``id == "greet"`` state 의 ``on_enter`` 는 엔진 차원에서
    silent dispatch — token 송출 없이 transition 만 평가. 즉 token 이 0개여도
    OK이며, state 전이가 정상이면 패턴 통과.
    """
    calendar_mock._reset()

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["book_appointment"])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    async def stream_response(tpl, ctx, **kwargs):
        # 호출되더라도 OK 지만 silent greet 가 동작하면 호출 자체가 안 일어나야.
        for t in ["안녕", "하세요", "!"]:
            yield t

    response_gen = MagicMock()
    response_gen.stream = stream_response

    from src.agent_framework.llm.fallback_router import FallbackDecision

    fallback = AsyncMock()
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    engine = AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    events: list[dict] = []
    async for evt in engine.turn("entry_s", "derm1", "예약할래"):
        events.append(evt)

    states = [e for e in events if e["event"] == "state"]
    state_names = [s["data"].get("state") for s in states]
    assert "greet" in state_names, f"greet state 진입 없음: {state_names}"
    # greet 는 silent — chatty greeting token 이 없어야 함.
    tokens = [e for e in events if e["event"] == "token"]
    joined = "".join(t["data"]["text"] for t in tokens)
    assert "안녕하세요" not in joined, (
        f"silent-greet 패턴 위반 — greet.on_enter 가 chatty token 송출: {joined}"
    )
