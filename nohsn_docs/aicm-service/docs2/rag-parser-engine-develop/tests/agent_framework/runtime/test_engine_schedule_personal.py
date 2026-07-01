"""schedule_personal 이 state-machine 으로 라우팅되는지 + list_schedule 경로 회귀.

2026-04-24 실사용 테스트 4건 버그 수정:
 Bug 1) schedule_personal 이 AUDIT_SKILLS 에 포함 — tool_loop 대신 상태머신.
 Bug 3) list_schedule intent 로 query state 에서 schedule.list 호출.

실제 YAML (schedule_personal.yaml) 을 로드해서 state 전이를 검증한다.
LLM 의존성은 AsyncMock 으로 stub — vLLM / Redis 필요 없음.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.engine import AUDIT_SKILLS, AgentEngine
from src.agent_framework.runtime.session_store import SessionState
from src.agent_framework.tools.registry import ToolRegistry


def test_schedule_personal_is_audit_skill():
    """Bug 1 회귀 — schedule_personal 가 상태머신 경로 대상에 포함."""
    assert "schedule_personal" in AUDIT_SKILLS
    assert "diary_personal" in AUDIT_SKILLS
    assert "appointment_derm" in AUDIT_SKILLS


class _FakeStore:
    def __init__(self):
        self._data: dict[str, SessionState] = {}

    async def get(self, session_id):
        return self._data.get(session_id)

    async def put(self, state):
        self._data[state.session_id] = state


def _make_response_gen(token_log: list[str]):
    async def stream(tpl, ctx, **kwargs):
        token_log.append(tpl)
        yield f"<{tpl}>"

    gen = MagicMock()
    gen.stream = stream
    return gen


@pytest.mark.asyncio
async def test_list_schedule_intent_routes_to_query_state():
    """Bug 3 — list_schedule intent → query state → schedule.list 도구 호출."""
    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["list_schedule"])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    token_log: list[str] = []
    response_gen = _make_response_gen(token_log)
    fallback = AsyncMock()

    list_called_with: dict = {}

    async def fake_list(args: dict):
        list_called_with.update(args)
        return {"items": [{"id": "x1", "title": "윤수석 술 약속", "body": {"when": "2026-04-25 19:00"}}]}

    # tool_loop stub — 호출되면 실패 (audit 경로여야 함)
    tool_loop = MagicMock()
    tool_loop.run = AsyncMock(side_effect=AssertionError(
        "schedule_personal 은 state-machine 경로여야 함 (tool_loop 금지)"
    ))

    engine = AgentEngine(
        session_store=_FakeStore(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(
            {
                "schedule.create": AsyncMock(return_value={"id": "y", "success": True}),
                "schedule.list": fake_list,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
        tool_loop=tool_loop,
    )

    events: list[dict] = []
    async for evt in engine.turn("sid_q", "phone-x", "내일 일정 있어?"):
        events.append(evt)

    # state event 중 query 포함
    states = [e["data"].get("state") for e in events if e["event"] == "state"]
    assert "query" in states, f"query state 전이 누락. states: {states}"

    # schedule.list 도구가 실제로 호출됐어야
    tool_results = [e for e in events if e["event"] == "tool_result"]
    assert any(t["data"].get("tool") == "schedule.list" for t in tool_results), (
        f"schedule.list 호출 누락. tool_results: {tool_results}"
    )

    # schedule_query_answer.md 템플릿으로 응답
    assert "schedule_query_answer.md" in token_log, token_log


@pytest.mark.asyncio
async def test_create_schedule_without_time_blocks_on_collect():
    """Bug 2 — create_schedule intent 인데 slot 미완성이면 create 안 됨.

    slot_filler 가 when=null 을 돌려주면 collect state 의 `slot_filled(when)`
    guard 가 false → create state 로 진행하지 않는다.
    """
    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["create_schedule"])

    slot_filler = AsyncMock()
    # vague 시각 → 모두 null
    slot_filler.fill = AsyncMock(
        return_value={"title": "술 약속", "when": None, "recurrence": None}
    )

    token_log: list[str] = []
    response_gen = _make_response_gen(token_log)
    fallback = AsyncMock()
    from src.agent_framework.llm.fallback_router import FallbackDecision

    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    create_called = AsyncMock(return_value={"id": "should-not-happen", "success": True})
    engine = AgentEngine(
        session_store=_FakeStore(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(
            {
                "schedule.create": create_called,
                "schedule.list": AsyncMock(return_value={"items": []}),
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
        tool_loop=MagicMock(run=AsyncMock(side_effect=AssertionError("audit path"))),
    )

    events: list[dict] = []
    async for evt in engine.turn("sid_c", "phone-x", "내일 저녁에 술 약속"):
        events.append(evt)

    # schedule.create 호출 금지
    create_called.assert_not_awaited()

    # collect state 에 머물러 있어야 (또는 최대 collect 까지만 도달)
    states = [e["data"].get("state") for e in events if e["event"] == "state"]
    assert "create" not in states, f"when 미확정인데 create 진입. states: {states}"
