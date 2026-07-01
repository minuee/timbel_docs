"""inbox_summary realtime emit 테스트 — DB INSERT happy path + cadence skip."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from src.agent_framework.workers import feed_compose, inbox_summary
from src.api.routers import auth_v2


TEST_EMAIL_PREFIX = "p3_inbox_summary_"


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
                text("DELETE FROM feed_events WHERE account_id = :aid"),
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
    await feed_compose._reset_engine_for_tests()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await feed_compose._reset_engine_for_tests()


async def _create_account(email: str) -> tuple[str, str]:
    from httpx import ASGITransport, AsyncClient

    from src.api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Sup3rSecret!", "name": "T"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        return body["user"]["id"], body["user"]["tenant_id"]


async def _set_prefs(account_id: str, prefs: dict) -> None:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "UPDATE accounts SET preferences = CAST(:p AS JSONB) WHERE id = :aid"
            ),
            {"p": json.dumps(prefs), "aid": account_id},
        )


@pytest.mark.asyncio
async def test_emit_realtime_inserts_feed_event(clean_db):
    aid, tid = await _create_account(_email("rt"))
    eng = feed_compose._get_engine()
    msg = {
        "id": "m1",
        "sender": "alice@example.com",
        "subject": "Hello world",
    }
    fid = await inbox_summary.emit_realtime(eng, aid, tid, msg)
    assert fid is not None
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT title, kind FROM feed_events WHERE id = :fid"
                ),
                {"fid": fid},
            )
        ).first()
    assert row is not None
    assert "alice@example.com" in row[0]
    assert row[1] == "inbox_summary"


@pytest.mark.asyncio
async def test_emit_realtime_skips_when_disabled(clean_db):
    aid, tid = await _create_account(_email("dis"))
    await _set_prefs(
        aid, {"feed_cadence": {"inbox_summary": {"enabled": False}}}
    )
    eng = feed_compose._get_engine()
    fid = await inbox_summary.emit_realtime(
        eng, aid, tid, {"id": "x", "sender": "s", "subject": "t"}
    )
    assert fid is None
