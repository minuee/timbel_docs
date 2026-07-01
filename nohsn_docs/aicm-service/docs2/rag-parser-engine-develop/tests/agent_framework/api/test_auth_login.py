"""``/auth/login`` shim smoke tests (2026-04-24).

로그인 페이지 (/login.html) 가 호출하는 shim 엔드포인트.
내부적으로 ``get_or_create_account`` 를 재사용하므로 idempotent 동작이 핵심.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.agent_framework.core.accounts import (
    _get_engine,
    _reset_engine_for_tests,
)
from src.api.main import app

TEST_PHONE_PREFIX = "010-AUTH-"


async def _cleanup() -> None:
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts WHERE phone LIKE :p"
            ),
            {"p": f"{TEST_PHONE_PREFIX}%"},
        )
        to_wipe = list(rows)
        for account_id, tenant_id in to_wipe:
            await conn.execute(
                text("DELETE FROM tenant_memberships WHERE account_id = :aid"),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            )
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
    await _reset_engine_for_tests()
    await _cleanup()
    yield
    await _cleanup()
    await _reset_engine_for_tests()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_login_creates_account_on_first_call(clean_db):
    """최초 호출 시 account + personal_tenant 생성. session_token 발급."""
    phone = f"{TEST_PHONE_PREFIX}0001"
    async with await _client() as c:
        resp = await c.post("/auth/login", json={"phone": phone, "name": "로그인유저"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["phone"] == phone
    assert data["name"] == "로그인유저"
    assert data["account_id"]
    assert data["personal_tenant_id"]
    assert data["session_token"]
    # session_token 은 UUID 문자열
    assert len(data["session_token"]) == 36


@pytest.mark.asyncio
async def test_login_is_idempotent_for_same_phone(clean_db):
    """동일 phone 재호출 → 동일 account_id / personal_tenant_id 반환.

    session_token 은 매번 새로 발급되므로 달라도 OK.
    """
    phone = f"{TEST_PHONE_PREFIX}0002"
    async with await _client() as c:
        r1 = await c.post("/auth/login", json={"phone": phone, "name": "A"})
        r2 = await c.post("/auth/login", json={"phone": phone, "name": "B-재시도"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()
    d2 = r2.json()
    assert d1["account_id"] == d2["account_id"]
    assert d1["personal_tenant_id"] == d2["personal_tenant_id"]
    # session_token 은 매번 새로 발급 (v1 opaque)
    assert d1["session_token"] != d2["session_token"]
