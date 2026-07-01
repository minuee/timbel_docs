import pytest
import pytest_asyncio

from src.agent_framework.runtime.session_store import (
    SessionState, SessionStore,
)


@pytest.mark.asyncio
async def test_put_get_roundtrip(redis_client):
    store = SessionStore(redis_client, ttl_s=60)
    sid = "sess-1"
    s = SessionState(
        session_id=sid,
        skill_id="echo_bot",
        current_state="s_greet",
        slots={"a": 1},
        history=[],
        tenant_id="t1",
        identity=None,
    )
    await store.put(s)
    got = await store.get(sid)
    assert got is not None
    assert got.skill_id == "echo_bot"
    assert got.slots["a"] == 1


@pytest.mark.asyncio
async def test_get_missing_returns_none(redis_client):
    store = SessionStore(redis_client, ttl_s=60)
    got = await store.get("nope")
    assert got is None


@pytest.mark.asyncio
async def test_delete(redis_client):
    store = SessionStore(redis_client, ttl_s=60)
    s = SessionState(session_id="s2", skill_id=None, current_state=None,
                     slots={}, history=[], tenant_id="t1", identity=None)
    await store.put(s)
    await store.delete("s2")
    assert await store.get("s2") is None
