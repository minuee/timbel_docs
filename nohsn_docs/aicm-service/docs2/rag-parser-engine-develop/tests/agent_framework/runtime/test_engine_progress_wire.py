"""Wave D P0 — ProgressEmitter wire-up in tool_loop iteration.

`engine.turn()` 의 tool_loop 경로에서 evt 처리 직전 _maybe_progress 가
호출되어 임계 (3s/7s/15s) 초과 시 SSE event=progress 가 yield 되는지 검증.

실 `time.perf_counter` 대신 monkeypatch 해 가짜 시간 흐름을 만든다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.schema import Skill, SkillMeta, StateDef, Trigger
from src.agent_framework.runtime.session_store import SessionState


def _make_skill(sid: str, intent: str) -> Skill:
    return Skill(
        skill=SkillMeta(id=sid, version="0.1", domain="test", description="테스트"),
        triggers=[Trigger(intent=intent)],
        initial_state="s0",
        states=[StateDef(id="s0")],
    )


class _FakeStore:
    def __init__(self, seeded: dict[str, SessionState] | None = None):
        self._data = seeded or {}
        self.put_calls: list[SessionState] = []

    async def get(self, session_id: str):
        return self._data.get(session_id)

    async def put(self, state: SessionState) -> None:
        self._data[state.session_id] = state
        self.put_calls.append(state)


def _session(sid: str) -> SessionState:
    return SessionState(
        session_id=sid,
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="tenant-x",
        identity=None,
        account_id="11111111-1111-1111-1111-111111111111",
    )


class _StubResponseGen:
    def stream(self, template_name, context, **kwargs):
        async def _gen():
            yield f"[MOCK:{template_name}]"
        return _gen()


def _build_engine(*, tool_loop, classifier=None) -> AgentEngine:
    if classifier is None:
        classifier = AsyncMock()
        classifier.classify_multi = AsyncMock(return_value=["create_schedule"])
    skill = _make_skill("schedule_test", "create_schedule")
    registry = AsyncMock()
    registry.list_available_labels_for_account = AsyncMock(
        return_value=["create_schedule"]
    )
    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})
    return AgentEngine(
        session_store=_FakeStore({"s_progress_1": _session("s_progress_1")}),
        tool_registry=MagicMock(),
        slot_filler=slot_filler,
        response_generator=_StubResponseGen(),
        fallback_router=AsyncMock(),
        intent_classifier=classifier,
        skills={"schedule_test": skill},
        tool_loop=tool_loop,
        skill_registry=registry,
    )


@pytest.mark.asyncio
async def test_progress_event_emitted_when_tool_loop_slow(monkeypatch):
    """tool_loop 가 첫 evt 직전에 4 초 경과 → progress(임계 3s) 1회 yield."""
    # 가상 perf_counter — 호출 시점마다 점프해 tool_loop evt 발생 시점에 4초 경과 시뮬.
    fake_t = [0.0]

    def _next_t():
        # 첫 호출(t0) 은 0, 이후엔 큰 폭으로 점프
        fake_t[0] += 4.0
        return fake_t[0]

    import src.agent_framework.runtime.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "perf_counter", _next_t)

    async def _slow_run(*args, **kwargs):
        # 첫 evt 직전 시간이 흘렀다고 가정 — 호출되면 token 1개만 yield
        yield {"type": "token", "text": "hi"}
        yield {"type": "done"}

    tool_loop = MagicMock()
    tool_loop.run = _slow_run

    engine = _build_engine(tool_loop=tool_loop)

    events: list[dict] = []
    async for evt in engine.turn("s_progress_1", "tenant-x", "일정 잡아줘"):
        events.append(evt)

    # progress 이벤트가 한 번 이상 발생
    progress_evts = [e for e in events if e["event"] == "progress"]
    assert len(progress_evts) >= 1
    assert "검색" in progress_evts[0]["data"]["text"] or "분석" in progress_evts[0]["data"]["text"]


@pytest.mark.asyncio
async def test_no_progress_event_when_fast(monkeypatch):
    """tool_loop 가 빠르게 끝나면 progress 발화 X (임계 3s 미달)."""
    fake_t = [0.0]

    def _next_t():
        # 매 호출 +0.05s — 모든 evt 통과해도 1초 미만
        fake_t[0] += 0.05
        return fake_t[0]

    import src.agent_framework.runtime.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "perf_counter", _next_t)

    async def _fast_run(*args, **kwargs):
        yield {"type": "token", "text": "ok"}
        yield {"type": "done"}

    tool_loop = MagicMock()
    tool_loop.run = _fast_run

    engine = _build_engine(tool_loop=tool_loop)
    events: list[dict] = []
    async for evt in engine.turn("s_progress_1", "tenant-x", "일정 잡아줘"):
        events.append(evt)

    assert not any(e["event"] == "progress" for e in events)
