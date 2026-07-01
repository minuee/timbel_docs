"""Stage B-Core-3 — AgentEngine.turn() session-aware intent routing.

SkillRegistry 로 account 별 enabled label 조회 → classifier 에 주입 →
sentinel (_no_skills_available / unsupported) 처리 흐름 검증.

테스트는 SkillRegistry / classifier / session_store / skill_router / tool_loop 를
모두 AsyncMock / MagicMock 으로 stub — 실제 DB / Redis / vLLM 에 닿지 않는다.
"""
from __future__ import annotations

import structlog
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.schema import (
    Skill,
    SkillMeta,
    StateDef,
    Trigger,
)
from src.agent_framework.runtime.session_store import SessionState


def _make_skill(
    sid: str, intent: str, description: str = "테스트 스킬"
) -> Skill:
    """Trigger intent 1개짜리 최소 skill — router 가 인식 가능한 형태."""
    return Skill(
        skill=SkillMeta(
            id=sid, version="0.1", domain="test", description=description
        ),
        triggers=[Trigger(intent=intent)],
        initial_state="s0",
        states=[StateDef(id="s0")],
    )


class _FakeStore:
    """SessionStore 대체 — 메모리 dict."""

    def __init__(self, seeded: dict[str, SessionState] | None = None):
        self._data: dict[str, SessionState] = seeded or {}
        self.put_calls: list[SessionState] = []

    async def get(self, session_id: str) -> SessionState | None:
        return self._data.get(session_id)

    async def put(self, state: SessionState) -> None:
        self._data[state.session_id] = state
        self.put_calls.append(state)


def _session(
    session_id: str,
    account_id: str | None = "11111111-1111-1111-1111-111111111111",
) -> SessionState:
    return SessionState(
        session_id=session_id,
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="tenant-x",
        identity=None,
        account_id=account_id,
    )


class _StubResponseGen:
    """ResponseGenerator 대체 — 호출 기록 + 더미 토큰 스트림."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def stream(self, template_name: str, context: dict, **kwargs):
        self.calls.append((template_name, context))

        async def _gen():
            yield f"[MOCK:{template_name}]"

        return _gen()


def _build_engine(
    *,
    classifier: AsyncMock,
    skill_registry: AsyncMock | None = None,
    skills: dict[str, Skill] | None = None,
    session_store: _FakeStore,
    tool_loop: AsyncMock | None = None,
    response_gen=None,
) -> AgentEngine:
    """Engine with stubbed collaborators. No Redis / no LLM."""
    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})
    if response_gen is None:
        response_gen = _StubResponseGen()
    fallback = AsyncMock()

    return AgentEngine(
        session_store=session_store,  # type: ignore[arg-type]
        tool_registry=MagicMock(),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=classifier,
        skills=skills or {},
        tool_loop=tool_loop,
        skill_registry=skill_registry,
    )


@pytest.mark.asyncio
async def test_engine_passes_account_labels_to_classifier():
    """SkillRegistry 가 반환한 labels 가 classifier 로 kwarg 전달되는지."""
    skill = _make_skill("schedule_test", "create_schedule", "일정")
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock(
        return_value=["create_schedule", "log_diary"]
    )

    classifier = AsyncMock()
    # 매칭 intent 반환 → 실제 skill_router 가 찾아감, audit 아님 → tool_loop 로.
    classifier.classify_multi = AsyncMock(return_value=["create_schedule"])

    # tool_loop 는 AsyncMock — .run(...) 이 async iterator 여야 함.
    async def _empty_run(*args, **kwargs):
        if False:
            yield {}

    tool_loop = MagicMock()
    tool_loop.run = _empty_run

    store = _FakeStore({"s1": _session("s1")})
    engine = _build_engine(
        classifier=classifier,
        skill_registry=registry,
        skills={"schedule_test": skill},
        session_store=store,
        tool_loop=tool_loop,
    )

    async for _ in engine.turn("s1", "tenant-x", "일정 좀 잡아줘"):
        pass

    registry.list_available_labels_for_account.assert_awaited_once()
    # classifier 는 (user_message, history) positional + available_labels kwarg
    classifier.classify_multi.assert_awaited_once()
    _, call_kwargs = classifier.classify_multi.await_args
    assert call_kwargs.get("available_labels") == [
        "create_schedule",
        "log_diary",
    ]


@pytest.mark.asyncio
async def test_engine_no_skills_available_returns_guidance():
    """classifier 가 [_no_skills_available] 반환 → 기능 없음 안내 + done."""
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock(return_value=[])

    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(
        return_value=["_no_skills_available"]
    )

    tool_loop = MagicMock()
    tool_loop.run = AsyncMock()  # 절대 호출되지 않아야 함

    store = _FakeStore({"s2": _session("s2")})
    stub_gen = _StubResponseGen()
    engine = _build_engine(
        classifier=classifier,
        skill_registry=registry,
        skills={},
        session_store=store,
        tool_loop=tool_loop,
        response_gen=stub_gen,
    )

    events: list[dict] = []
    async for evt in engine.turn("s2", "tenant-x", "안녕"):
        events.append(evt)

    types = [e["event"] for e in events]
    assert "intent" in types
    assert "token" in types
    assert "done" in types
    # tool_loop.run 호출 없음 — sentinel 경로에서는 skip
    tool_loop.run.assert_not_called()
    # ResponseGenerator 가 전용 템플릿으로 호출됐는지 (정밀 prompt 경로)
    assert any(tpl == "no_skills_available.md" for tpl, _ in stub_gen.calls)
    tpl_name, ctx = stub_gen.calls[0]
    assert tpl_name == "no_skills_available.md"
    assert ctx["user_message"] == "안녕"
    assert ctx["tenant"]["name"] == "tenant-x"
    # session_store.put 1회. user + assistant 양쪽 모두 history 저장 (대화 이력 강화).
    assert len(store.put_calls) == 1
    hist = store.put_calls[0].history
    assert hist[-2]["role"] == "user" and hist[-2]["content"] == "안녕"
    assert hist[-1]["role"] == "assistant"
    assert "[MOCK:no_skills_available.md]" in hist[-1]["content"]


@pytest.mark.asyncio
async def test_engine_unsupported_returns_list_of_available():
    """classifier 가 [unsupported] 반환 → 지원 안 됨 + 사용 가능 기능 나열."""
    skill = _make_skill(
        "schedule_test", "create_schedule", description="개인 일정 등록"
    )
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock(
        return_value=["create_schedule"]
    )

    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(return_value=["unsupported"])

    tool_loop = MagicMock()
    tool_loop.run = AsyncMock()

    store = _FakeStore({"s3": _session("s3")})
    stub_gen = _StubResponseGen()
    engine = _build_engine(
        classifier=classifier,
        skill_registry=registry,
        skills={"schedule_test": skill},
        session_store=store,
        tool_loop=tool_loop,
        response_gen=stub_gen,
    )

    events: list[dict] = []
    async for evt in engine.turn("s3", "tenant-x", "주식 매수 주문해줘"):
        events.append(evt)

    tool_loop.run.assert_not_called()
    # 전용 unsupported 템플릿 호출 + context 에 available_skills 전달 확인
    assert len(stub_gen.calls) == 1
    tpl_name, ctx = stub_gen.calls[0]
    assert tpl_name == "unsupported_request.md"
    assert ctx["user_message"] == "주식 매수 주문해줘"
    assert "개인 일정 등록" in ctx["available_skills"]
    # 히스토리 append + put 발생
    assert len(store.put_calls) == 1


@pytest.mark.asyncio
async def test_engine_legacy_path_when_no_account_id():
    """session.account_id is None → registry 호출 없이 available_labels=None 로 분류."""
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock()  # not called

    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(return_value=[])

    # tool_loop 없음 → legacy fallback 분기 탐 (이 분기도 skill_registry 는 안 본다)
    store = _FakeStore({"s4": _session("s4", account_id=None)})
    engine = _build_engine(
        classifier=classifier,
        skill_registry=registry,
        skills={},
        session_store=store,
        tool_loop=None,
    )

    async for _ in engine.turn("s4", "tenant-x", "안녕하세요"):
        pass

    registry.list_available_labels_for_account.assert_not_called()
    classifier.classify_multi.assert_awaited_once()
    _, call_kwargs = classifier.classify_multi.await_args
    assert call_kwargs.get("available_labels") is None


@pytest.mark.asyncio
async def test_engine_skill_registry_exception_falls_back_to_legacy():
    """SkillRegistry lookup 실패 → 경고 로그 + available_labels=None fallback."""
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock(
        side_effect=RuntimeError("db down")
    )

    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(return_value=[])

    store = _FakeStore({"s5": _session("s5")})
    engine = _build_engine(
        classifier=classifier,
        skill_registry=registry,
        skills={},
        session_store=store,
        tool_loop=None,
    )

    with structlog.testing.capture_logs() as logs:
        async for _ in engine.turn("s5", "tenant-x", "hi"):
            pass

    events = [e["event"] for e in logs]
    assert "skill_registry_lookup_failed" in events
    # classifier 는 여전히 호출되고, available_labels=None
    classifier.classify_multi.assert_awaited_once()
    _, call_kwargs = classifier.classify_multi.await_args
    assert call_kwargs.get("available_labels") is None


@pytest.mark.asyncio
async def test_engine_capability_query_briefs_enabled_skills():
    """classifier 가 [_capability_query] 반환 → 전용 brief 템플릿 + available_skills 전달."""
    sched_skill = _make_skill(
        "schedule_test", "create_schedule", description="개인 일정 등록"
    )
    diary_skill = _make_skill(
        "diary_test", "log_diary", description="개인 일기 기록"
    )
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock(
        return_value=["create_schedule", "log_diary"]
    )

    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(return_value=["_capability_query"])

    tool_loop = MagicMock()
    tool_loop.run = AsyncMock()

    store = _FakeStore({"s6": _session("s6")})
    stub_gen = _StubResponseGen()
    engine = _build_engine(
        classifier=classifier,
        skill_registry=registry,
        skills={"schedule_test": sched_skill, "diary_test": diary_skill},
        session_store=store,
        tool_loop=tool_loop,
        response_gen=stub_gen,
    )

    async for _ in engine.turn("s6", "tenant-x", "뭐 할 수 있어?"):
        pass

    tool_loop.run.assert_not_called()
    assert len(stub_gen.calls) == 1
    tpl_name, ctx = stub_gen.calls[0]
    assert tpl_name == "capability_briefing.md"
    assert ctx["user_message"] == "뭐 할 수 있어?"
    assert set(ctx["available_skills"]) == {"개인 일정 등록", "개인 일기 기록"}
    assert len(store.put_calls) == 1


@pytest.mark.asyncio
async def test_engine_capability_query_legacy_falls_back_to_all_skills():
    """skill_registry 없거나 account_id=None → 엔진에 로드된 전체 skill 소개."""
    sched_skill = _make_skill(
        "schedule_test", "create_schedule", description="개인 일정 등록"
    )
    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(return_value=["_capability_query"])

    tool_loop = MagicMock()
    tool_loop.run = AsyncMock()

    store = _FakeStore({"s7": _session("s7", account_id=None)})
    stub_gen = _StubResponseGen()
    engine = _build_engine(
        classifier=classifier,
        skill_registry=None,
        skills={"schedule_test": sched_skill},
        session_store=store,
        tool_loop=tool_loop,
        response_gen=stub_gen,
    )

    async for _ in engine.turn("s7", "tenant-x", "무슨 기능 있어?"):
        pass

    assert len(stub_gen.calls) == 1
    tpl_name, ctx = stub_gen.calls[0]
    assert tpl_name == "capability_briefing.md"
    # registry 없음 → 전체 skills 로 fallback
    assert ctx["available_skills"] == ["개인 일정 등록"]
