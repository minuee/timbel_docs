"""``feed_compose`` worker — daily brief INSERT 검증.

PR P3 (KMS-Plus). DB 만 사용, LLM/외부 호출 없음.

검증 항목
---------
1. 활성 account 한 개에 대해 1건 INSERT.
2. 같은 날 두 번 호출하면 2번째는 중복 방지로 0건 추가.
3. ``feed_cadence.daily_briefing.enabled=False`` → skip.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from src.agent_framework.workers import feed_compose
from src.api.routers import auth_v2


TEST_EMAIL_PREFIX = "p3_feed_compose_"


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
    """signup → (account_id, tenant_id) 반환."""
    from httpx import ASGITransport, AsyncClient

    from src.api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Sup3rSecret!", "name": "FeedTester"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        return body["user"]["id"], body["user"]["tenant_id"]


async def _set_prefs(account_id: str, prefs: dict) -> None:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "UPDATE accounts SET preferences = CAST(:p AS JSONB) "
                " WHERE id = :aid"
            ),
            {"p": json.dumps(prefs), "aid": account_id},
        )


@pytest.mark.asyncio
async def test_compose_inserts_one_event_per_account(clean_db):
    aid, _tid = await _create_account(_email("a"))
    eng = feed_compose._get_engine()
    n = await feed_compose.compose_for_all(eng=eng)
    assert n >= 1
    # 해당 account row 가 실제로 들어갔는가.
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM feed_events "
                    " WHERE account_id = :aid AND kind = :k"
                ),
                {"aid": aid, "k": "daily_briefing"},
            )
        ).first()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_compose_dedupes_same_day(clean_db):
    aid, _tid = await _create_account(_email("dup"))
    eng = feed_compose._get_engine()
    n1 = await feed_compose.compose_for_all(eng=eng)
    n2 = await feed_compose.compose_for_all(eng=eng)
    # 2번째 호출은 같은 날이라 중복 방지로 0.
    assert n1 >= 1
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM feed_events "
                    " WHERE account_id = :aid AND kind = :k"
                ),
                {"aid": aid, "k": "daily_briefing"},
            )
        ).first()
    assert row[0] == 1
    # 두 번째 콜에서는 *이 account 에 대해* 새 row 추가 X.
    assert n2 < n1 or n2 == 0


@pytest.mark.asyncio
async def test_compose_respects_disabled_cadence(clean_db):
    aid, _tid = await _create_account(_email("dis"))
    await _set_prefs(
        aid, {"feed_cadence": {"daily_briefing": {"enabled": False}}}
    )
    eng = feed_compose._get_engine()
    await feed_compose.compose_for_all(eng=eng)
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM feed_events "
                    " WHERE account_id = :aid AND kind = :k"
                ),
                {"aid": aid, "k": "daily_briefing"},
            )
        ).first()
    assert row[0] == 0
