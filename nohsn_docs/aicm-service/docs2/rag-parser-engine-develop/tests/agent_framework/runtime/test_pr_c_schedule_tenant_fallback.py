"""PR-C — 일정 등록 손실 root cause 회귀 테스트.

증상: 채팅 LLM 이 "캘린더에 등록했습니다" 라고 응답해도 일정 뷰
(``GET /agent/data/schedules``) 에 안 나타남. 다음 턴에 "이번주 일정"
질의 시 LLM 은 sess.history 의 직전 답변만 보고 있는 듯한 일정을 다시
언급 → 사용자에게는 "등록된 척" 만 노출.

뿌리:
1. ``account_bind_failed`` (varchar(32) phone column 에 UUID 36자 INSERT 실패)
   → ``sess.personal_tenant_id = None``.
2. ``_resolve_args`` 가 ``$personal_tenant_id`` 를 그대로 ``sess.personal_tenant_id``
   로 치환 — None 그대로 schedule.create 호출.
3. KMS 모드는 tenant_id 누락이면 명시 에러 (저장 안 됨), Redis 모드는
   ``args["phone"]`` 키로만 저장 → 일정 뷰가 personal_tenant_id 로 query 시 miss.
4. slot 가드 ``slot_filled(when)`` 만 — title/who/where 가 비어도 create 진행.

PR-C 가 도입하는 가드:
A. ``SessionState.effective_personal_tenant_id`` — 3단 fallback.
B. ``_resolve_args`` 가 위 helper 로 위임 (engine 의 G2 grounding 경로와 동일 source).
C. ``matcher.slots_filled(...)`` — multi-slot AND. ``collect → create`` 가드를
   ``slots_filled(title, when)`` 으로 강화.
D. ``schedule_store.create`` idempotency — 동일 (scope, when, title) 재호출 silent skip
   + tool_result 에 ``duplicate: True`` + 한국어 ``summary``.
E. ``tool_result`` SSE event 에 ``ok``/``summary`` 빌드 (front 의 TraceStrip 노출용).

각 시나리오는 LLM/Redis 미의존 — AsyncMock 으로 stub.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.matcher import MatcherContext, evaluate_when
from src.agent_framework.runtime.session_store import SessionState
from src.agent_framework.tools.registry import ToolRegistry


# ── 공통 fakes ────────────────────────────────────────────────────────


class _FakeStore:
    """Redis 없이 SessionStore 인터페이스만 흉내."""

    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}

    async def get(self, session_id: str) -> SessionState | None:
        return self._data.get(session_id)

    async def put(self, state: SessionState) -> None:
        self._data[state.session_id] = state

    async def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)


def _make_response_gen(token_log: list[str]):
    async def stream(tpl: str, ctx: dict[str, Any], **kwargs):
        token_log.append(tpl)
        yield f"<{tpl}>"

    gen = MagicMock()
    gen.stream = stream
    return gen


def _build_engine(
    *,
    intents: list[str],
    slot_fill_result: dict[str, Any],
    create_handler,
    list_handler=None,
):
    """schedule_personal 시나리오 한 사이클 돌릴 수 있는 최소 엔진."""
    from src.agent_framework.llm.fallback_router import FallbackDecision

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=intents)

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value=slot_fill_result)

    fallback = AsyncMock()
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    response_gen = _make_response_gen([])

    list_handler = list_handler or AsyncMock(return_value={"items": []})
    tools = ToolRegistry(
        {
            "schedule.create": create_handler,
            "schedule.list": list_handler,
        }
    )

    return AgentEngine(
        session_store=_FakeStore(),  # type: ignore[arg-type]
        tool_registry=tools,
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
        tool_loop=MagicMock(
            run=AsyncMock(side_effect=AssertionError("audit path"))
        ),
    )


# ── 1) tenant_id 3단 fallback ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_args_uses_effective_personal_tenant_id_fallback():
    """account_bind_failed 시 sess.personal_tenant_id=None 이어도
    sess.tenant_id 까지 fallback 되어 schedule.create 가 정상 tenant_id 로 호출."""
    captured: dict[str, Any] = {}

    async def fake_create(args: dict[str, Any]):
        captured.update(args)
        return {"id": "doc-1", "success": True}

    engine = _build_engine(
        intents=["create_schedule"],
        slot_fill_result={
            "title": "윤찬우 친구 만남",
            "when": "2026-04-28T18:00",
            "where": "엔타워 3층",
            "recurrence": None,
        },
        create_handler=fake_create,
    )

    # sess 생성을 우리가 통제 — account_bind_failed 시뮬레이션.
    # AgentEngine.turn 은 새 세션에서 get_or_create_account 시도.
    # 그걸 monkey-stub: account_bind_failed 시 personal_tenant_id=None 설정.
    fake_tenant = "11111111-1111-4111-8111-111111111111"

    # SessionState 직접 주입 — 실패 fallback 경로를 "이미 발생" 상태로 설정.
    pre = SessionState(
        session_id="sid-fb",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id=fake_tenant,
        identity={"phone": "010-9999"},
        account_id=None,
        personal_tenant_id=None,  # ← bind 실패한 상태
    )
    await engine.session_store.put(pre)

    events: list[dict[str, Any]] = []
    async for evt in engine.turn(
        "sid-fb", fake_tenant, "내일 저녁 6시 윤찬우 친구 만남"
    ):
        events.append(evt)

    assert "tenant_id" in captured, f"create 미호출 또는 args 누락: {captured}"
    assert captured["tenant_id"] == fake_tenant, (
        f"effective_personal_tenant_id fallback 실패 — "
        f"got {captured.get('tenant_id')}, expected {fake_tenant}"
    )


# ── 2) 저장 직후 list 가 같은 tenant 로 조회 → 일치 ──────────────────


@pytest.mark.asyncio
async def test_create_then_list_same_tenant_id_round_trip():
    """schedule_store.create 후 list_all 이 동일 scope 로 조회해 1건 반환.

    integration 까지 가지 않고 in-memory store stub 으로 round-trip 만 확인 —
    핵심은 'create 가 받은 tenant_id == list 가 query 한 tenant_id' 일치성.
    """
    fake_tenant = "22222222-2222-4222-8222-222222222222"
    storage: list[dict[str, Any]] = []

    async def fake_create(args: dict[str, Any]):
        storage.append(
            {
                "tenant_id": args["tenant_id"],
                "title": args["title"],
                "when": args["when"],
            }
        )
        return {"id": f"doc-{len(storage)}", "success": True}

    async def fake_list(args: dict[str, Any]):
        tid = args.get("tenant_id")
        return {"items": [s for s in storage if s["tenant_id"] == tid]}

    # 1차 turn — create
    engine_create = _build_engine(
        intents=["create_schedule"],
        slot_fill_result={
            "title": "엔타워 3층 미팅",
            "when": "2026-04-28T18:00",
            "where": "엔타워 3층",
            "recurrence": None,
        },
        create_handler=fake_create,
        list_handler=fake_list,
    )
    pre = SessionState(
        session_id="sid-rt",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id=fake_tenant,
        identity={"phone": "010-rt"},
        account_id=None,
        personal_tenant_id=None,
    )
    await engine_create.session_store.put(pre)
    async for _ in engine_create.turn(
        "sid-rt", fake_tenant, "내일 저녁 6시 엔타워 3층 미팅"
    ):
        pass

    # 2차 turn — list (새 session)
    list_called: dict[str, Any] = {}

    async def capture_list(args: dict[str, Any]):
        list_called.update(args)
        return await fake_list(args)

    engine_list = _build_engine(
        intents=["list_schedule"],
        slot_fill_result={},
        create_handler=AsyncMock(),
        list_handler=capture_list,
    )
    pre2 = SessionState(
        session_id="sid-rt-list",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id=fake_tenant,
        identity={"phone": "010-rt"},
        account_id=None,
        personal_tenant_id=None,
    )
    await engine_list.session_store.put(pre2)

    async for _ in engine_list.turn("sid-rt-list", fake_tenant, "이번주 일정 알려줘"):
        pass

    assert list_called.get("tenant_id") == fake_tenant
    items = (await fake_list({"tenant_id": fake_tenant}))["items"]
    assert len(items) == 1, f"create 한 일정이 list 에 안 보임: {items}"
    assert items[0]["title"] == "엔타워 3층 미팅"


# ── 3) slots_filled multi-AND — title 누락이면 create 진입 차단 ──────


@pytest.mark.asyncio
async def test_collect_blocks_when_title_missing_multi_slot_guard():
    """when 만 채워졌고 title 비어 있으면 ``slots_filled(title, when)`` 가
    False → create state 미진입. collect 에 머물러 LLM 되묻기."""
    create_called = AsyncMock(return_value={"id": "x", "success": True})
    engine = _build_engine(
        intents=["create_schedule"],
        slot_fill_result={
            "title": None,  # ← 누락
            "when": "2026-04-28T18:00",
            "recurrence": None,
        },
        create_handler=create_called,
    )
    pre = SessionState(
        session_id="sid-mg",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="33333333-3333-4333-8333-333333333333",
        identity={"phone": "010-mg"},
        account_id=None,
        personal_tenant_id=None,
    )
    await engine.session_store.put(pre)

    states: list[str | None] = []
    async for evt in engine.turn(
        "sid-mg", pre.tenant_id, "내일 저녁 6시"
    ):
        if evt.get("event") == "state":
            states.append(evt["data"].get("state"))

    create_called.assert_not_awaited()
    assert "create" not in states, (
        f"title 미충족인데 create 진입 — multi-slot guard 작동 안 함. states: {states}"
    )


def test_matcher_slots_filled_evaluates_AND():
    """matcher 가 ``slots_filled(a, b, c)`` 표현식을 multi-AND 로 평가."""
    ctx_full = MatcherContext(
        user_message="",
        detected_intents=[],
        slots={"title": "x", "when": "2026-04-28", "where": "엔타워"},
        tool_result=None,
        user_intent=None,
    )
    ctx_partial = MatcherContext(
        user_message="",
        detected_intents=[],
        slots={"title": "x", "when": None, "where": "엔타워"},
        tool_result=None,
        user_intent=None,
    )
    assert evaluate_when("slots_filled(title, when)", ctx_full) is True
    assert evaluate_when("slots_filled(title, when)", ctx_partial) is False
    # 빈 문자열도 미충족
    ctx_empty = MatcherContext(
        user_message="",
        detected_intents=[],
        slots={"title": "x", "when": ""},
        tool_result=None,
        user_intent=None,
    )
    assert evaluate_when("slots_filled(title, when)", ctx_empty) is False


# ── 4) idempotency — 동일 키 두 번 호출 시 두 번째는 silent skip ────


@pytest.mark.asyncio
async def test_schedule_create_idempotent_redis_path(monkeypatch):
    """동일 (phone, when, title) 로 두 번 create — 두 번째는
    duplicate=True + summary='이미 등록됨' 으로 응답 + Redis 에 한 줄만 존재."""
    from src.agent_framework.tools import _redis_store as rs
    from src.agent_framework.tools import schedule_store

    # 환경: Redis 경로 사용. 테스트용 in-memory rpush_item / list_items stub.
    monkeypatch.delenv("AGENT_DATA_STORE", raising=False)
    fake_storage: dict[str, list[dict[str, Any]]] = {}

    async def fake_rpush(category: str, phone: str, item: dict[str, Any]):
        key = f"{category}:{phone}"
        fake_storage.setdefault(key, []).append(item)

    async def fake_list(category: str, phone: str):
        return list(fake_storage.get(f"{category}:{phone}", []))

    monkeypatch.setattr(rs, "rpush_item", fake_rpush)
    monkeypatch.setattr(rs, "list_items", fake_list)

    payload = {
        "phone": "010-dup",
        "title": "윤찬우 만남",
        "when": "2026-04-28T18:00",
        "recurrence": None,
    }
    r1 = await schedule_store.create(payload)
    r2 = await schedule_store.create(dict(payload))  # 동일 key

    assert r1["success"] is True
    assert r1.get("duplicate") is not True
    assert r2["success"] is True
    assert r2.get("duplicate") is True, f"두 번째 create 가 dedup 안 됨: {r2}"
    assert "이미 등록" in (r2.get("summary") or ""), (
        f"한국어 summary 누락 — 사용자가 'duplicate' 인지 알 수 없음: {r2}"
    )

    items = await fake_list("schedule", "010-dup")
    assert len(items) == 1, f"redis 에 중복 저장됨: {items}"


# ── 5) tool_result SSE event — ok/summary schema 일관성 ──────────────


@pytest.mark.asyncio
async def test_tool_result_sse_event_has_ok_and_summary():
    """state-machine 경로의 schedule.create 호출 후
    SSE event 'tool_result' 에 ``{tool, ok, summary}`` 가 포함."""
    async def fake_create(args: dict[str, Any]):
        return {"id": "doc-tr", "success": True}

    engine = _build_engine(
        intents=["create_schedule"],
        slot_fill_result={
            "title": "회의",
            "when": "2026-04-28T15:00",
            "where": "회의실 A",
            "recurrence": None,
        },
        create_handler=fake_create,
    )
    pre = SessionState(
        session_id="sid-tr",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="44444444-4444-4444-8444-444444444444",
        identity={"phone": "010-tr"},
        account_id=None,
        personal_tenant_id=None,
    )
    await engine.session_store.put(pre)

    tool_results: list[dict[str, Any]] = []
    async for evt in engine.turn("sid-tr", pre.tenant_id, "내일 3시 회의"):
        if evt.get("event") == "tool_result":
            tool_results.append(evt["data"])

    # 정확히 한 번 송출
    assert len(tool_results) == 1, f"tool_result 송출 횟수 이상: {tool_results}"
    data = tool_results[0]
    assert data.get("tool") == "schedule.create"
    assert data.get("ok") is True, f"ok 키 누락 또는 falsy: {data}"
    assert isinstance(data.get("summary"), str) and len(data["summary"]) > 0, (
        f"summary 키 누락 또는 빈 문자열: {data}"
    )
