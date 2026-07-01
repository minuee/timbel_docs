"""Task 15 Layer 1 — /agent/chat SSE grammar contract tests.

Fakes AgentEngine via dependency_overrides so tests are fast + hermetic.
Each test hits the real FastAPI app + chat_session.py route + SSE serializer.
Asserts the exact byte format that frontend consumes.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from src.agent_framework.api.dependencies import get_agent_engine
from src.api.main import app


def _parse_sse_stream(raw: bytes) -> list[dict]:
    """Parse raw SSE bytes into list of {event, data} dicts."""
    events: list[dict] = []
    for chunk in raw.decode("utf-8").strip().split("\n\n"):
        if not chunk.strip():
            continue
        evt: dict = {}
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                evt["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                evt["data"] = json.loads(line[len("data:"):].strip())
        if evt:
            events.append(evt)
    return events


class _FakeEngine:
    """Configurable engine stub that yields a predefined event sequence."""

    def __init__(self, events: list[dict]):
        self._events = events

    async def turn(self, session_id: str, tenant_id: str, user_message: str, **kwargs):
        for evt in self._events:
            yield evt


async def _call_chat(events: list[dict], *, payload: dict | None = None) -> list[dict]:
    app.dependency_overrides[get_agent_engine] = lambda: _FakeEngine(events)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            body = payload or {"session_id": "s1", "tenant_id": "t1", "message": "hi"}
            async with c.stream("POST", "/agent/chat", json=body) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                raw = b""
                async for chunk in resp.aiter_raw():
                    raw += chunk
        return _parse_sse_stream(raw)
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)


# ===== Test 1: Minimal happy path — intent -> skill_routed -> done =====


@pytest.mark.asyncio
async def test_sse_minimal_happy_path():
    events = [
        {"event": "intent", "data": {"intents": ["book_appointment"]}},
        {"event": "state", "data": {"skill_id": "appointment_derm", "state": "greet"}},
        {"event": "token", "data": {"text": "안녕하세요"}},
        {"event": "state", "data": {"state": "greet"}},
        {"event": "done", "data": {}},
    ]
    parsed = await _call_chat(events)
    # shape
    assert [e["event"] for e in parsed] == ["intent", "state", "token", "state", "done"]
    # intent payload
    assert parsed[0]["data"] == {"intents": ["book_appointment"]}
    # first state payload has skill_id
    assert parsed[1]["data"]["skill_id"] == "appointment_derm"
    assert parsed[1]["data"]["state"] == "greet"
    # final state no skill_id (just current state)
    assert "state" in parsed[3]["data"]


# ===== Test 2: No-match path — intent then direct done =====


@pytest.mark.asyncio
async def test_sse_no_skill_match_path():
    """intent 가 아무 스킬과도 매칭 안 되면 token + done 만 나옴."""
    events = [
        {"event": "intent", "data": {"intents": ["unknown_intent"]}},
        {"event": "token", "data": {"text": "무슨 도움이 필요하신가요?"}},
        {"event": "done", "data": {}},
    ]
    parsed = await _call_chat(events)
    assert [e["event"] for e in parsed] == ["intent", "token", "done"]
    assert "도움" in parsed[1]["data"]["text"]


# ===== Test 3: Fallback path — intent -> state -> token(fallback) -> state =====


@pytest.mark.asyncio
async def test_sse_fallback_path():
    events = [
        {"event": "intent", "data": {"intents": []}},
        # skill already routed in prior turn — no new skill_id announcement
        {"event": "token", "data": {"text": "죄송합니다, 다시 말씀해 주실래요?"}},
        {"event": "state", "data": {"state": "greet"}},
        {"event": "done", "data": {}},
    ]
    parsed = await _call_chat(events)
    assert parsed[0]["event"] == "intent"
    assert parsed[1]["event"] == "token"
    assert "죄송" in parsed[1]["data"]["text"] or "다시" in parsed[1]["data"]["text"]


# ===== Test 4: Booking completion (slot_update + tool_result) =====


@pytest.mark.asyncio
async def test_sse_slot_filling_then_tool_result_sequence():
    events = [
        {"event": "intent", "data": {"intents": ["book_appointment"]}},
        {"event": "slot_update", "data": {"name": "preferred_date", "value": "2026-04-25"}},
        {
            "event": "tool_result",
            "data": {"tool": "calendar.check_availability", "keys": ["available"]},
        },
        {"event": "state", "data": {"state": "confirm"}},
        {"event": "token", "data": {"text": "2026-04-25"}},
        {"event": "token", "data": {"text": " 에 예약하시겠어요?"}},
        {"event": "state", "data": {"state": "confirm"}},
        {"event": "done", "data": {}},
    ]
    parsed = await _call_chat(events)
    # ordering invariants
    event_types = [e["event"] for e in parsed]
    assert event_types.index("slot_update") < event_types.index("tool_result")
    assert event_types.index("tool_result") < event_types.index("token")
    assert event_types[-1] == "done"


# ===== Test 5: Unicode (Korean) passes through unmangled =====


@pytest.mark.asyncio
async def test_sse_korean_unicode_passthrough():
    korean_text = "안녕하세요, 예약을 도와드릴까요?"
    events = [
        {"event": "intent", "data": {"intents": []}},
        {"event": "token", "data": {"text": korean_text}},
        {"event": "done", "data": {}},
    ]
    parsed = await _call_chat(events)
    # Korean must round-trip byte-exact through json.dumps(ensure_ascii=False) + SSE + parse
    assert parsed[1]["data"]["text"] == korean_text


# ===== Test 6: Empty data dict is valid (done event) =====


@pytest.mark.asyncio
async def test_sse_empty_data_dict_serializes():
    events = [
        {"event": "intent", "data": {"intents": []}},
        {"event": "done", "data": {}},
    ]
    parsed = await _call_chat(events)
    assert parsed[-1]["event"] == "done"
    assert parsed[-1]["data"] == {}
