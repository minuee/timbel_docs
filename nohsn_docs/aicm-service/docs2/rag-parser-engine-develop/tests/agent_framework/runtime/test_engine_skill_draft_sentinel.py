"""AgentEngine — _skill_draft_request sentinel routing (Task 34-36 Phase A).

DraftComposer + db_engine 을 AsyncMock / MagicMock 으로 stub. skill_draft_store
모듈 자체는 monkeypatch 로 create 함수를 바꿔 DB 접근 없이 검증.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.session_store import SessionState
from src.agent_framework.storage.skill_draft_store import SkillDraft


class _FakeStore:
    def __init__(self, seeded=None):
        self._data = seeded or {}
        self.put_calls: list[SessionState] = []

    async def get(self, session_id):
        return self._data.get(session_id)

    async def put(self, state):
        self._data[state.session_id] = state
        self.put_calls.append(state)


class _StubResponseGen:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def stream(self, template_name, context, **kwargs):
        self.calls.append((template_name, context))

        async def _gen():
            yield f"[MOCK:{template_name}]"

        return _gen()


def _session() -> SessionState:
    return SessionState(
        session_id="s-draft",
        skill_id=None,
        current_state=None,
        slots={},
        history=[{"role": "user", "content": "안녕"}],
        tenant_id="tenant-x",
        identity=None,
        account_id=str(uuid4()),
        personal_tenant_id=str(uuid4()),
    )


def _engine(
    *,
    classifier,
    draft_composer=None,
    db_engine=None,
    response_gen=None,
    store=None,
) -> AgentEngine:
    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})
    return AgentEngine(
        session_store=store or _FakeStore({}),  # type: ignore[arg-type]
        tool_registry=MagicMock(),
        slot_filler=slot_filler,
        response_generator=response_gen or _StubResponseGen(),
        fallback_router=AsyncMock(),
        intent_classifier=classifier,
        skills={},
        tool_loop=None,
        draft_composer=draft_composer,
        db_engine=db_engine,
    )


@pytest.mark.asyncio
async def test_engine_skill_draft_request_creates_draft_and_announces(monkeypatch):
    """정상 경로: DraftComposer 성공 → store.create 호출 → announce 템플릿 렌더."""
    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(
        return_value=["_skill_draft_request"]
    )

    composer = AsyncMock()
    composer.compose = AsyncMock(
        return_value=SkillDraft(
            title="주식 일일 리포트",
            yaml_text="skill:\n  id: user_defined_daily\n",
            rationale="매일 오전 주식 흐름을 요약해 달라는 요청",
        )
    )

    created_id = uuid4()

    async def _fake_create(engine, draft, **kwargs):
        # draft / kwargs 내용 검증
        assert draft.title == "주식 일일 리포트"
        assert kwargs["source_user_message"].startswith("매일 오전")
        return created_id

    from src.agent_framework.storage import skill_draft_store as sds

    monkeypatch.setattr(sds, "create", _fake_create)

    store = _FakeStore({"s-draft": _session()})
    stub_gen = _StubResponseGen()
    engine = _engine(
        classifier=classifier,
        draft_composer=composer,
        db_engine=MagicMock(),  # placeholder — fake_create 가 engine 사용 안 함
        response_gen=stub_gen,
        store=store,
    )

    events: list[dict] = []
    async for evt in engine.turn(
        "s-draft", "tenant-x", "매일 오전 주식 리포트 보내주는 기능 만들어줘"
    ):
        events.append(evt)

    types = [e["event"] for e in events]
    assert types[0] == "intent"
    assert "token" in types
    assert types[-1] == "done"

    composer.compose.assert_awaited_once()
    assert any(tpl == "skill_draft_announce.md" for tpl, _ in stub_gen.calls)
    _, ctx = stub_gen.calls[0]
    assert ctx["draft_title"] == "주식 일일 리포트"
    assert ctx["draft_id"] == str(created_id)
    assert "매일 오전" in ctx["rationale"]

    # session 저장: user + assistant 누적
    assert len(store.put_calls) == 1
    hist = store.put_calls[0].history
    assert hist[-2]["role"] == "user"
    assert hist[-1]["role"] == "assistant"
    assert "[MOCK:skill_draft_announce.md]" in hist[-1]["content"]


@pytest.mark.asyncio
async def test_engine_skill_draft_request_fallback_on_compose_error(monkeypatch):
    """compose 실패 → 사과성 fallback 메시지, 세션 정상 저장."""
    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(
        return_value=["_skill_draft_request"]
    )

    composer = AsyncMock()
    composer.compose = AsyncMock(side_effect=RuntimeError("draft failed"))

    async def _not_called(*a, **kw):  # pragma: no cover
        raise AssertionError("skill_draft_store.create should not be called")

    from src.agent_framework.storage import skill_draft_store as sds

    monkeypatch.setattr(sds, "create", _not_called)

    store = _FakeStore({"s-err": _session()})
    # session_id 맞춰서 get 가능
    list(store._data.values())[0].session_id = "s-err"
    store._data = {"s-err": list(store._data.values())[0]}
    stub_gen = _StubResponseGen()
    engine = _engine(
        classifier=classifier,
        draft_composer=composer,
        db_engine=MagicMock(),
        response_gen=stub_gen,
        store=store,
    )

    tokens: list[str] = []
    async for evt in engine.turn("s-err", "tenant-x", "막 기능 하나 만들어 줘"):
        if evt["event"] == "token":
            tokens.append(evt["data"]["text"])

    full = "".join(tokens)
    assert "실패" in full or "죄송" in full
    composer.compose.assert_awaited_once()
    # announce 템플릿은 렌더되지 않아야 함 (fallback 경로)
    assert not any(
        tpl == "skill_draft_announce.md" for tpl, _ in stub_gen.calls
    )
    # 세션 저장 (history 누적)
    assert len(store.put_calls) == 1
    hist = store.put_calls[0].history
    assert hist[-2]["role"] == "user"
    assert hist[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_engine_skill_draft_request_without_account_returns_guidance():
    """account_id=None (로그인 전) → 정적 안내 + 세션 저장."""
    classifier = AsyncMock()
    classifier.classify_multi = AsyncMock(
        return_value=["_skill_draft_request"]
    )

    composer = AsyncMock()
    composer.compose = AsyncMock()  # 호출되면 실패

    sess = _session()
    sess.account_id = None
    sess.personal_tenant_id = None
    store = _FakeStore({sess.session_id: sess})

    engine = _engine(
        classifier=classifier,
        draft_composer=composer,
        db_engine=MagicMock(),
        store=store,
    )
    tokens = []
    async for evt in engine.turn(sess.session_id, "tenant-x", "기능 만들어 줘"):
        if evt["event"] == "token":
            tokens.append(evt["data"]["text"])

    full = "".join(tokens)
    assert "로그인" in full
    composer.compose.assert_not_called()
    assert len(store.put_calls) == 1
