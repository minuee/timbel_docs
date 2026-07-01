"""Task 15 Layer 5 — 엔진 구조화 로그 검증.

structlog 이벤트를 capture 해서 turn() 이 기대한 순서로 로그를 남기는지 확인.

이 프로젝트의 `src/common/logging.py` 는 `structlog.PrintLoggerFactory()` 를
쓰기 때문에 로그가 stdout 으로 바로 나가고 stdlib `logging` 을 통과하지
않는다. 결과적으로 pytest `caplog` 로는 이벤트를 못 잡는다.
대신 `structlog.testing.capture_logs()` 컨텍스트 매니저를 쓴다 — dict 리스트로
모든 이벤트를 모아준다.
"""
from __future__ import annotations

import pytest
import structlog
from unittest.mock import AsyncMock, MagicMock

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools import calendar_mock
from src.agent_framework.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_engine_emits_structured_logs(redis_client):
    """happy path turn() 이 turn_started → intent_classified → skill_routed →
    slot_filled → state_transition → turn_completed 순서의 로그를 남기는지 검증.
    """
    calendar_mock._reset()

    from src.agent_framework.llm.fallback_router import FallbackDecision

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["book_appointment"])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    async def stream_response(tpl, ctx, **kwargs):
        yield "응답"

    response_gen = MagicMock()
    response_gen.stream = stream_response
    fallback = AsyncMock()
    # PR-AA2 — collect_datetime 같이 llm_slot_fill 만 정의된 state 가 같은 turn
    # 에 자동 진입하도록 hop 가드를 완화한 뒤로, slot 추출 실패 시 fallback_router
    # 가 호출됨. 옛 테스트는 fallback 미호출을 가정해 bare AsyncMock 사용 중이라
    # FallbackDecision 명시 stub 으로 보강.
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

    with structlog.testing.capture_logs() as logs:
        async for _evt in engine.turn("s1", "derm1", "예약하고 싶어요"):
            pass

    events = [entry["event"] for entry in logs]
    # 필수 이벤트 존재 확인
    for required in [
        "turn_started",
        "turn_new_session",
        "intent_classified",
        "skill_routed",
        "state_transition",
        "turn_completed",
    ]:
        assert required in events, f"missing log event: {required}\nall events: {events}"

    # turn_started kwargs 검증
    started = next(e for e in logs if e["event"] == "turn_started")
    assert started["session_id"] == "s1"
    assert started["tenant_id"] == "derm1"
    assert started["message_len"] == len("예약하고 싶어요")

    # intent_classified kwargs 검증
    classified = next(e for e in logs if e["event"] == "intent_classified")
    assert classified["count"] == 1
    assert classified["intents"] == ["book_appointment"]

    # skill_routed kwargs 검증
    routed = next(e for e in logs if e["event"] == "skill_routed")
    assert routed["skill_id"] == "appointment_derm"
    assert routed["initial_state"] == "greet"

    # turn_completed 에 duration_ms 있음
    completed = next(e for e in logs if e["event"] == "turn_completed")
    assert "duration_ms" in completed
    assert isinstance(completed["duration_ms"], int)
    assert completed["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_engine_logs_skill_no_match_when_intent_unknown(redis_client):
    """intent 가 어떤 스킬과도 매치 안 되면 skill_no_match 로그."""
    calendar_mock._reset()

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["unknown_intent"])
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

    with structlog.testing.capture_logs() as logs:
        async for _ in engine.turn("s_unknown", "derm1", "날씨 좋네요"):
            pass

    events = [entry["event"] for entry in logs]
    assert "skill_no_match" in events, f"events: {events}"
    no_match = next(e for e in logs if e["event"] == "skill_no_match")
    assert no_match["intents_tried"] == ["unknown_intent"]


@pytest.mark.asyncio
async def test_engine_does_not_log_pii(redis_client):
    """PII (user_message 전체, slot 값, identity) 가 로그에 나타나지 않음을 검증."""
    calendar_mock._reset()

    SENSITIVE_PHONE = "010-9876-5432"
    SENSITIVE_MSG = "내 전화번호는 010-9876-5432 이고 주민번호는 901010-1234567"

    from src.agent_framework.llm.fallback_router import FallbackDecision

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["book_appointment"])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={"contact_phone": SENSITIVE_PHONE})

    async def stream_response(tpl, ctx, **kwargs):
        yield "응답"

    response_gen = MagicMock()
    response_gen.stream = stream_response
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

    with structlog.testing.capture_logs() as logs:
        async for _ in engine.turn("s_pii", "derm1", SENSITIVE_MSG):
            pass

    # 각 로그 엔트리의 value 를 모두 문자열화 해서 PII 가 섞였는지 확인
    log_blob = "\n".join(
        " ".join(f"{k}={v!r}" for k, v in entry.items()) for entry in logs
    )
    assert "010-9876-5432" not in log_blob, f"PII (phone) leaked: {log_blob}"
    assert "901010" not in log_blob, f"PII (SSN) leaked: {log_blob}"
    assert SENSITIVE_MSG not in log_blob, "full user_message leaked"
