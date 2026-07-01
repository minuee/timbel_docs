"""State machine auto-advance + on_enter/on_exit 중복 방지 회귀 테스트.

user 실 대화에서 관찰된 3대 버그 방지:
  1) list_doctors_state transitions 가 무조건 greet 으로 복귀해
     예약 의도 밝힌 사용자도 greet 로 돌아가던 문제.
  2) on_exit 스트림 + next state on_enter 스트림 이중 렌더링 (중복 greeting).
  3) 전이 후 새 state 의 tool 이 같은 턴에 실행 안 되어 rag_consult 가
     묵묵부답이던 문제 (다음 turn 까지 대기).

테스트는 실 YAML (appointment_derm) + 실 StateMachine 을 쓰고 LLM 은
AsyncMock 으로 stub 한다. redis_client fixture (DB 2) 는 conftest 제공.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.llm.fallback_router import FallbackDecision
from src.agent_framework.runtime.engine import AgentEngine, MAX_AUTO_HOPS
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools import calendar_mock
from src.agent_framework.tools.registry import ToolRegistry


def _make_response_gen(token_log: list[str]):
    """response_generator stub — 호출 시 템플릿 이름을 token_log 에 기록,
    가짜 token 1개 yield."""
    async def stream(tpl, ctx, **kwargs):
        token_log.append(tpl)
        yield f"<{tpl}>"
    gen = MagicMock()
    gen.stream = stream
    return gen


@pytest.mark.asyncio
async def test_on_exit_rendered_skips_next_on_enter(redis_client):
    """list_doctors_state.on_exit (select_doctor.md) 가 렌더되면
    전이 후 greet.on_enter (greet_derm.md) 는 같은 턴에 스킵되어야 한다.

    list_doctors_state → (ask_doctors 없음, book/treatment 없음, llm_fallback 없음)
    → unconditional `to: greet` 기본 경로 채택.
    한 턴에 select_doctor.md 만 렌더, greet_derm.md 는 스킵 기대.
    """
    calendar_mock._reset()

    intent = AsyncMock()
    # 기존 세션 재개 시나리오 — first turn 에 ask_doctors 로 list_doctors_state 진입해둔 것처럼.
    # 바로 이 테스트는 list_doctors_state 에 이미 들어가 있고, 추가 질문 없는 애매한 발화.
    intent.classify_multi = AsyncMock(return_value=[])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    token_log: list[str] = []
    response_gen = _make_response_gen(token_log)
    fallback = AsyncMock()
    # fallback_router.decide 가 유효한 FallbackDecision 반환하도록 stub
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    engine = AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
                "calendar.list_doctors": calendar_mock.list_doctors,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    # 세션을 list_doctors_state 에 미리 앉혀둔다 (두 번째 턴을 시뮬레이션)
    from src.agent_framework.runtime.session_store import SessionState
    await engine.session_store.put(
        SessionState(
            session_id="sid_listdoc",
            skill_id="appointment_derm",
            current_state="list_doctors_state",
            slots={},
            history=[],
            tenant_id="derm1",
            identity=None,
        )
    )

    async for _ in engine.turn("sid_listdoc", "derm1", "음 그래?"):
        pass

    # on_exit (select_doctor.md) 는 반드시 렌더
    assert "select_doctor.md" in token_log
    # greet.on_enter (greet_derm.md) 는 같은 턴에 렌더 안 되어야
    assert "greet_derm.md" not in token_log, (
        f"이중 렌더 감지 — token_log: {token_log}"
    )


@pytest.mark.asyncio
async def test_auto_advance_to_tool_state_same_turn(redis_client):
    """greet → rag_consult (tool 만 있음) 전이 시 같은 턴에 tool 실행 + on_exit 렌더.

    ask_treatment intent → greet.on_enter 렌더 (skill 첫 진입) → rag_consult 전이 →
    kms_rag.search tool 실행 → rag_answer_derm.md (on_exit) 는 이미 렌더된 상태 이므로
    skip 되지만 tool 은 실행되어 tool_result 이벤트는 발행되어야 한다.
    """
    calendar_mock._reset()

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["ask_treatment"])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    token_log: list[str] = []
    response_gen = _make_response_gen(token_log)
    fallback = AsyncMock()
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    # kms_rag.search mock — 가짜 hits 반환
    async def fake_rag_search(args: dict):
        return {"hits": [{"text": "레이저 시술 안내", "score": 0.9}]}

    engine = AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
                "calendar.list_doctors": calendar_mock.list_doctors,
                "kms_rag.search": fake_rag_search,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    events: list[dict] = []
    async for evt in engine.turn("sid_rag", "derm1", "레이저 시술 알려줘"):
        events.append(evt)

    # rag_consult 까지 자동 진행됐어야 (state event 에 있어야)
    states = [e["data"].get("state") for e in events if e["event"] == "state"]
    assert "rag_consult" in states, f"rag_consult 전이 누락. states: {states}"

    # kms_rag.search tool_result 이벤트 발생했어야 (같은 턴 tool 실행)
    tool_results = [e for e in events if e["event"] == "tool_result"]
    assert any(t["data"].get("tool") == "kms_rag.search" for t in tool_results), (
        f"rag_consult tool 같은 턴 실행 실패. tool_results: {tool_results}"
    )


@pytest.mark.asyncio
async def test_list_doctors_state_with_book_intent_goes_to_collect_datetime(
    redis_client,
):
    """버그 1 회귀 — list_doctors_state 에서 book_appointment intent 감지되면
    greet 가 아닌 collect_datetime 으로 전이되어야 한다.
    """
    calendar_mock._reset()

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["book_appointment"])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    token_log: list[str] = []
    response_gen = _make_response_gen(token_log)
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
                "calendar.list_doctors": calendar_mock.list_doctors,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )

    # list_doctors_state 에서 시작 (이전 턴에서 ask_doctors 로 진입한 상태 simulation)
    from src.agent_framework.runtime.session_store import SessionState
    await engine.session_store.put(
        SessionState(
            session_id="sid_book_from_list",
            skill_id="appointment_derm",
            current_state="list_doctors_state",
            slots={},
            history=[],
            tenant_id="derm1",
            identity=None,
        )
    )

    events: list[dict] = []
    async for evt in engine.turn(
        "sid_book_from_list", "derm1", "내일 레이저 시술 예약하고 싶어"
    ):
        events.append(evt)

    # collect_datetime 전이 확인
    states = [e["data"].get("state") for e in events if e["event"] == "state"]
    assert "collect_datetime" in states, (
        f"book_appointment intent 인데 collect_datetime 으로 못 감. states: {states}"
    )
    # greet 로 복귀 안 했어야
    assert states[-1] != "greet", f"예약 의도 있는데 greet 복귀 감지. states: {states}"


@pytest.mark.asyncio
async def test_auto_advance_circuit_breaker_max_hops(redis_client):
    """MAX_AUTO_HOPS 상한 sanity — 3 hop 초과 체인은 중단.

    정상 YAML 로는 3 hop 에 도달하지 않지만, 상한이 3 으로 박혀있음을 확인.
    """
    assert MAX_AUTO_HOPS == 3, "MAX_AUTO_HOPS 상한이 변경됨 — 테스트/코드 동기화 필요"
