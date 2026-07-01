"""``chat_v1.message`` 가 ``structured_block`` SSE event 를 받으면
``chat_messages.structured_blocks`` JSONB 에 영속화하고, 같은 세션의 restore
endpoint 에서 그대로 반환되는지 검증 — KMS-Plus P0.2.

설계 — 진짜 AgentEngine 대신 _FakeEngine 으로 미리 정의된 event 시퀀스를 yield.
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


TEST_EMAIL_PREFIX = "p02_chat_sb_"


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
    """지정된 SSE event 시퀀스를 yield 하는 stub. 실 AgentEngine 우회."""

    def __init__(self, events: list[dict]):
        self._events = events

    async def turn(self, session_id: str, tenant_id: str, user_message: str, **kwargs):
        for evt in self._events:
            yield evt


async def _signup_and_get_token(c: AsyncClient, email: str) -> tuple[str, str, str]:
    r = await c.post(
        "/auth/v2/signup",
        json={"email": email, "password": "Sup3rSecret!", "name": "SBTester"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"], body["user"]["tenant_id"]


@pytest.mark.asyncio
async def test_structured_blocks_persisted_and_restored(clean_db):
    """structured_block SSE event → DB column → restore 응답 round-trip."""
    sb_payload_a = {"id": "ctx_a", "type": "context_panel", "fields": {"k": 1}}
    sb_payload_b = {"id": "ui_b", "type": "drawer_hint", "fields": {"k": 2}}
    fake_events: list[dict] = [
        {"event": "intent", "data": {"intents": ["chat"]}},
        {"event": "structured_block", "data": sb_payload_a},
        {"event": "token", "data": {"text": "hello"}},
        {"event": "structured_block", "data": sb_payload_b},
        {"event": "token", "data": {"text": " world"}},
        {"event": "done", "data": {}},
    ]

    app.dependency_overrides[get_agent_engine] = lambda: _FakeEngine(fake_events)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            token, _aid, tid = await _signup_and_get_token(c, _email("sb"))
            # /api/v1/chat/message — SSE. 본문을 끝까지 소진해 finally INSERT 발생.
            async with c.stream(
                "POST",
                "/api/v1/chat/message",
                json={"text": "trigger", "stream": True},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Tenant-ID": tid,
                },
            ) as resp:
                assert resp.status_code == 200, await resp.aread()
                async for _ in resp.aiter_raw():
                    pass

            # 직접 DB 조회 — assistant row 의 structured_blocks 컬럼.
            eng = auth_v2._get_engine()
            async with eng.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT structured_blocks FROM chat_messages "
                            "WHERE role = 'assistant' "
                            "  AND session_id IN ("
                            "    SELECT id FROM chat_sessions "
                            "    WHERE tenant_id = :tid"
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
            assert len(raw_sb) == 2
            assert raw_sb[0] == sb_payload_a
            assert raw_sb[1] == sb_payload_b

            # restore endpoint — 같은 payload 가 messages[].structured_blocks 로 노출.
            async with eng.connect() as conn:
                sess_row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM chat_sessions "
                            "WHERE tenant_id = :tid LIMIT 1"
                        ),
                        {"tid": tid},
                    )
                ).first()
            assert sess_row is not None
            sid = str(sess_row[0])

            r = await c.post(
                f"/api/v1/chat/sessions/{sid}/restore",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Tenant-ID": tid,
                },
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assistant_msgs = [m for m in data["messages"] if m["role"] == "assistant"]
            assert assistant_msgs, "no assistant message in restore"
            sb_field = assistant_msgs[-1].get("structured_blocks")
            assert sb_field == [sb_payload_a, sb_payload_b]
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)
