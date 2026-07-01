"""``chat_v1.message`` 의 structured_blocks size cap 검증 — KMS-Plus P0.2 hardening.

codex 2차 review (P1) — 무제한 structured_block event 가 chat_messages JSONB
컬럼에 그대로 들어가 worker 메모리/DB row 폭주 가능. cap 도입 검증:

1. block 수 cap — 20개 inject → 최대 16개만 영속.
2. 단일 block size cap — 200KB payload → ``_truncated: true`` sentinel.
3. 전체 size cap — 80KB × 5 = 400KB → 256KB 한도에 의해 일부만 영속.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.agent_framework.api.dependencies import get_agent_engine
from src.api.main import app
from src.api.routers import auth_v2, chat_v1, chat_sessions_v1
from src.core import database as core_db


TEST_EMAIL_PREFIX = "p02_chat_sb_cap_"


def _email(suffix: str) -> str:
    return f"{TEST_EMAIL_PREFIX}{suffix}_{uuid.uuid4().hex[:6]}@example.com"


async def _cleanup() -> None:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts WHERE email LIKE :p"
            ),
            {"p": f"{TEST_EMAIL_PREFIX}%"},
        )
        for account_id, tenant_id in list(rows):
            await conn.execute(
                text(
                    "DELETE FROM chat_messages WHERE session_id IN ("
                    "  SELECT id FROM chat_sessions WHERE account_id = :aid"
                    ")"
                ),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM chat_sessions WHERE account_id = :aid"),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM tenant_memberships WHERE account_id = :aid"),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            )
            if tenant_id:
                await conn.execute(
                    text("DELETE FROM repositories WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :tid"),
                    {"tid": tenant_id},
                )


@pytest_asyncio.fixture
async def clean_db():
    await auth_v2._reset_engine_for_tests()
    await chat_v1._reset_engine_for_tests()
    await chat_sessions_v1._reset_engine_for_tests()
    await core_db.engine.dispose()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await chat_v1._reset_engine_for_tests()
    await chat_sessions_v1._reset_engine_for_tests()
    await core_db.engine.dispose()


class _FakeEngine:
    def __init__(self, events: list[dict]):
        self._events = events

    async def turn(self, session_id: str, tenant_id: str, user_message: str, **kwargs):
        for evt in self._events:
            yield evt


async def _signup(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/v2/signup",
        json={"email": email, "password": "Sup3rSecret!", "name": "Cap"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["user"]["tenant_id"]


async def _drive_chat(c: AsyncClient, token: str, tid: str) -> None:
    async with c.stream(
        "POST",
        "/api/v1/chat/message",
        json={"text": "go", "stream": True},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": tid,
        },
    ) as resp:
        assert resp.status_code == 200, await resp.aread()
        async for _ in resp.aiter_raw():
            pass


async def _read_persisted_blocks(tid: str) -> list[dict]:
    eng = auth_v2._get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT structured_blocks FROM chat_messages "
                    "WHERE role = 'assistant' "
                    "  AND session_id IN ("
                    "    SELECT id FROM chat_sessions WHERE tenant_id = :tid"
                    "  ) "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tid},
            )
        ).first()
    assert row is not None, "assistant row not inserted"
    raw_sb = row[0]
    if isinstance(raw_sb, str):
        raw_sb = json.loads(raw_sb)
    assert isinstance(raw_sb, list)
    return raw_sb


# ---------------------------------------------------------------------------
# 1. count cap — 20 → 16.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_cap_caps_at_max(clean_db):
    """20 개의 structured_block 을 inject → 최대 16 개만 영속."""
    fake_events: list[dict] = [{"event": "intent", "data": {"intents": ["chat"]}}]
    for i in range(20):
        fake_events.append(
            {
                "event": "structured_block",
                "data": {"id": f"sb_{i}", "kind": "context_panel", "payload": {"i": i}},
            }
        )
    fake_events.append({"event": "token", "data": {"text": "ok"}})
    fake_events.append({"event": "done", "data": {}})

    app.dependency_overrides[get_agent_engine] = lambda: _FakeEngine(fake_events)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            token, tid = await _signup(c, _email("count"))
            await _drive_chat(c, token, tid)
        sb = await _read_persisted_blocks(tid)
        assert len(sb) == chat_v1.STRUCTURED_BLOCKS_MAX_COUNT == 16
        # 처음 16개 (i=0..15) 가 보존되어야 함.
        assert sb[0]["id"] == "sb_0"
        assert sb[-1]["id"] == "sb_15"
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)


# ---------------------------------------------------------------------------
# 2. per-block size cap — 200KB payload → _truncated: true.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_block_size_cap_truncates_payload(clean_db):
    """단일 block 의 payload 가 64KB 초과 → ``_truncated: true`` sentinel."""
    big_payload = {"big": "x" * 200_000}  # 약 200KB
    fake_events: list[dict] = [
        {"event": "intent", "data": {"intents": ["chat"]}},
        {
            "event": "structured_block",
            "data": {"id": "huge", "kind": "context_panel", "payload": big_payload},
        },
        {"event": "token", "data": {"text": "ok"}},
        {"event": "done", "data": {}},
    ]
    app.dependency_overrides[get_agent_engine] = lambda: _FakeEngine(fake_events)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            token, tid = await _signup(c, _email("big"))
            await _drive_chat(c, token, tid)
        sb = await _read_persisted_blocks(tid)
        assert len(sb) == 1
        b = sb[0]
        # 메타 (id/kind) 보존, payload 만 sentinel 로 치환.
        assert b["id"] == "huge"
        assert b["kind"] == "context_panel"
        assert isinstance(b["payload"], dict)
        assert b["payload"].get("_truncated") is True
        assert b["payload"].get("_original_bytes", 0) > 64 * 1024
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)


# ---------------------------------------------------------------------------
# 3. total size cap — 80KB × 5 = 400KB → 256KB 한도 → 일부만.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_size_cap_kicks_in(clean_db):
    """80KB × 5 inject → 총 한도 256KB 도달 시 중단. 5 미만만 영속."""
    # 80KB 는 per-block 64KB 초과라 truncate 됨 → sentinel 로 줄어듦.
    # truncate 된 sentinel 은 작아 모두 들어갈 수 있음 → 의도된 시나리오는
    # per-block 한도 미만 (<64KB) 인데 합산이 초과하는 케이스로 잡아야 함.
    # 60KB × 5 = 300KB → 256KB 한도에 의해 일부만 영속.
    fake_events: list[dict] = [{"event": "intent", "data": {"intents": ["chat"]}}]
    for i in range(5):
        fake_events.append(
            {
                "event": "structured_block",
                "data": {
                    "id": f"sb_{i}",
                    "kind": "context_panel",
                    "payload": {"text": "y" * 60_000},  # ≈60KB
                },
            }
        )
    fake_events.append({"event": "token", "data": {"text": "ok"}})
    fake_events.append({"event": "done", "data": {}})

    app.dependency_overrides[get_agent_engine] = lambda: _FakeEngine(fake_events)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            token, tid = await _signup(c, _email("total"))
            await _drive_chat(c, token, tid)
        sb = await _read_persisted_blocks(tid)
        # 256KB / 60KB ≈ 4.27 → 4개 이하 영속.
        assert len(sb) < 5, f"expected total cap to drop blocks, got {len(sb)}"
        # 영속된 block 들은 sentinel 이 아니라 원본 payload 여야 함 (각각 64KB 미만).
        for b in sb:
            assert isinstance(b["payload"], dict)
            assert b["payload"].get("_truncated") is not True
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)
