"""Task 15 Layer 2 — Real LLM end-to-end smoke test.

Runs against live B200 Gemma-4-31b via SSH tunnel at host.docker.internal:7120.
SKIPPED by default. To run:

    KMS_PLUS_LIVE_LLM=1 pytest tests/agent_framework/e2e/test_real_llm_smoke.py -v

Purpose: catch prompt regressions, LLM output format drift, Redis state
corruption under real conditions. Replaces the manual curl verification
done in Task 14.5 smoke.

Note: uses ``asyncio.wait_for`` for per-test timeout (pytest-timeout 는
컨테이너에 설치돼 있지 않음).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from src.agent_framework.llm.fallback_router import FallbackRouter
from src.agent_framework.llm.intent_classifier import MultiLabelIntentClassifier
from src.agent_framework.llm.response_generator import ResponseGenerator
from src.agent_framework.llm.slot_filler import SlotFiller
from src.agent_framework.llm.vllm_adapter import VLLMAdapter
from src.agent_framework.runtime.engine import SKILLS_DIR, AgentEngine
from src.agent_framework.runtime.loader import load_all_skills
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools import calendar_mock
from src.agent_framework.tools.registry import ToolRegistry


pytestmark = pytest.mark.skipif(
    os.environ.get("KMS_PLUS_LIVE_LLM") != "1",
    reason="KMS_PLUS_LIVE_LLM=1 환경변수 설정 시에만 실행 (B200 터널 + vLLM 필요)",
)


def _build_real_engine(redis_client) -> AgentEngine:
    """Construct AgentEngine with real LLM adapter + real skills, in-memory tools."""
    calendar_mock._reset()
    skills = load_all_skills(SKILLS_DIR)
    labels = sorted({t.intent for s in skills.values() for t in s.triggers})

    llm = VLLMAdapter()

    return AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
            }
        ),
        slot_filler=SlotFiller(llm),
        response_generator=ResponseGenerator(llm),
        fallback_router=FallbackRouter(llm),
        intent_classifier=MultiLabelIntentClassifier(llm, labels=labels),
    )


async def _drain_turn(
    engine: AgentEngine, session_id: str, message: str
) -> list[dict]:
    """Run one turn to completion, return all emitted events."""
    events: list[dict] = []
    async for evt in engine.turn(session_id, "derm1_test", message):
        events.append(evt)
    return events


@pytest.mark.asyncio
async def test_real_llm_routes_booking_intent(redis_client):
    """Gemma 가 '예약' 메시지를 받아 book_appointment intent 로 분류하고
    appointment_derm 스킬로 라우팅되는지."""
    engine = _build_real_engine(redis_client)
    events = await asyncio.wait_for(
        _drain_turn(engine, "live_s1", "다음 주 월요일 레이저 예약하고 싶어요"),
        timeout=90,
    )

    event_types = [e["event"] for e in events]
    assert "intent" in event_types
    intent_evt = next(e for e in events if e["event"] == "intent")
    intents = intent_evt["data"]["intents"]
    assert isinstance(intents, list), (
        f"intent 이벤트 data.intents 가 list 아님: {intent_evt}"
    )
    assert "book_appointment" in intents, (
        f"book_appointment intent 미검출: {intents}"
    )

    # appointment_derm 스킬로 라우팅됐는지 state 이벤트에서 확인
    state_events = [e for e in events if e["event"] == "state"]
    assert any(
        e["data"].get("skill_id") == "appointment_derm" for e in state_events
    ), f"appointment_derm 스킬로 라우팅 안됨: {state_events}"

    # 마지막 done
    assert event_types[-1] == "done"


@pytest.mark.asyncio
async def test_real_llm_rejects_casual_chat(redis_client):
    """일상 잡담은 아무 스킬과도 매칭 안 돼야 함 (skill_no_match)."""
    engine = _build_real_engine(redis_client)
    events = await asyncio.wait_for(
        _drain_turn(engine, "live_s2", "오늘 날씨 좋네요"),
        timeout=90,
    )

    event_types = [e["event"] for e in events]
    # intent 는 감지되지만 스킬 진입은 없음
    # done 있어야 함
    assert event_types[-1] == "done"
    # state 이벤트가 있더라도 skill_id 부여된 것은 없음
    state_events = [e for e in events if e["event"] == "state"]
    assert not any(
        e["data"].get("skill_id") == "appointment_derm" for e in state_events
    ), "일상 잡담이 appointment_derm 으로 잘못 라우팅됨"


@pytest.mark.asyncio
async def test_real_llm_multi_turn_booking_progression(redis_client):
    """3턴 대화에서 state 가 단계별로 진행되는지 (greet → collect_date → collect_service → check_slots/confirm)."""
    engine = _build_real_engine(redis_client)
    sid = "live_s3"

    # 턴 1: 예약 의도 → greet 또는 collect_date 진입
    e1 = await asyncio.wait_for(
        _drain_turn(engine, sid, "레이저 예약하고 싶어요"), timeout=90
    )
    assert e1[-1]["event"] == "done", f"턴1 마지막 이벤트가 done 아님: {e1[-1]}"
    assert any(e["event"] == "intent" for e in e1), "턴1 에 intent 이벤트 없음"
    turn1_states = [e["data"].get("state") for e in e1 if e["event"] == "state"]
    assert any(s in ("greet", "collect_date") for s in turn1_states), (
        f"턴1 예약 스킬 greet/collect_date 진입 실패: {turn1_states}"
    )

    # 턴 2: 날짜 제공 → collect_service/check_slots/confirm 으로 진행
    e2 = await asyncio.wait_for(
        _drain_turn(engine, sid, "다음 주 월요일로 부탁해요"), timeout=90
    )
    assert e2[-1]["event"] == "done", f"턴2 마지막 이벤트가 done 아님: {e2[-1]}"
    turn2_states = [e["data"].get("state") for e in e2 if e["event"] == "state"]
    assert any(
        s in ("collect_service", "check_slots", "confirm") for s in turn2_states
    ), f"턴2 에서 collect_service/check_slots/confirm 진행 실패: {turn2_states}"

    # 턴 3: 시술 → check_slots/confirm/book
    e3 = await asyncio.wait_for(
        _drain_turn(engine, sid, "레이저로 해주세요"), timeout=90
    )
    assert e3[-1]["event"] == "done", f"턴3 마지막 이벤트가 done 아님: {e3[-1]}"
    turn3_states = [e["data"].get("state") for e in e3 if e["event"] == "state"]
    assert any(s in ("check_slots", "confirm", "book") for s in turn3_states), (
        f"턴3 에서 check_slots/confirm/book 진행 실패: {turn3_states}"
    )
