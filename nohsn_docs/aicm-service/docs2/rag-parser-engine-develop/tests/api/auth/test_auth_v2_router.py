"""Auth v2 router 통합 테스트 — Phase 9 (KMS-Plus).

5+ 케이스:
1. signup → 200 + JWT pair + user payload.
2. signup 중복 email → 409.
3. login 정상 + JWT 디코드 가능.
4. login wrong password → 401.
5. refresh → 새 access token.
6. /me → JWT 의 sub/role 그대로 반환.
7. /me without bearer → 401/422.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.auth.jwt_utils import decode_token
from src.api.main import app
from src.api.routers import auth_v2


TEST_EMAIL_PREFIX = "phase9_auth_v2_"


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
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_signup_returns_jwt_pair_and_user(clean_db):
    email = _email("signup_ok")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Sup3rSecret!", "name": "테스트"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == email
    assert data["user"]["role"] == "owner"
    # access token 디코드 가능하고 sub == user.id
    payload = decode_token(data["access_token"])
    assert payload["sub"] == data["user"]["id"]
    assert payload["role"] == "owner"


@pytest.mark.asyncio
async def test_signup_duplicate_email_409(clean_db):
    email = _email("dup")
    async with await _client() as c:
        r1 = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Sup3rSecret!"},
        )
        assert r1.status_code == 200, r1.text
        r2 = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Another1234!"},
        )
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_login_success_and_jwt_decodes(clean_db):
    email = _email("login_ok")
    pwd = "VerySecret123!"
    async with await _client() as c:
        await c.post(
            "/auth/v2/signup", json={"email": email, "password": pwd}
        )
        r = await c.post(
            "/auth/v2/login", json={"email": email, "password": pwd}
        )
    assert r.status_code == 200, r.text
    data = r.json()
    payload = decode_token(data["access_token"])
    assert payload["sub"] == data["user"]["id"]
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_login_wrong_password_401(clean_db):
    email = _email("login_bad")
    async with await _client() as c:
        await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "RealPwd123!"},
        )
        r = await c.post(
            "/auth/v2/login",
            json={"email": email, "password": "WrongPwd456!"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_issues_new_access_token(clean_db):
    email = _email("refresh")
    async with await _client() as c:
        s = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Refresh1234!"},
        )
        refresh = s.json()["refresh_token"]
        r = await c.post("/auth/v2/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["access_token"]
    payload = decode_token(data["access_token"])
    assert payload["type"] == "access"
    assert payload["sub"] == s.json()["user"]["id"]


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(clean_db):
    """access token 을 refresh 엔드포인트에 보내면 401 (type 검증)."""
    email = _email("refresh_bad")
    async with await _client() as c:
        s = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Refresh1234!"},
        )
        access = s.json()["access_token"]
        r = await c.post("/auth/v2/refresh", json={"refresh_token": access})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_payload_via_bearer(clean_db):
    email = _email("me_ok")
    async with await _client() as c:
        s = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "MeSecret123!", "name": "이름"},
        )
        access = s.json()["access_token"]
        r = await c.get(
            "/auth/v2/me", headers={"Authorization": f"Bearer {access}"}
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user_id"] == s.json()["user"]["id"]
    assert data["email"] == email
    assert data["role"] == "owner"
    assert data["name"] == "이름"


@pytest.mark.asyncio
async def test_me_without_bearer_rejected(clean_db):
    async with await _client() as c:
        # 헤더 없음 → 422 (FastAPI required header validation)
        r = await c.get("/auth/v2/me")
    assert r.status_code in (401, 422)


# ---------------------------------------------------------------------------
# 그룹 가입 흐름 — personal default + sole_proprietor 옵션 + company/business 거부.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_default_groups_personal(clean_db):
    """groups 미지정 시 default=['personal']."""
    email = _email("group_default")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={"email": email, "password": "Sup3rSecret!"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["groups"] == ["personal"]


@pytest.mark.asyncio
async def test_signup_with_sole_proprietor(clean_db):
    """sole_proprietor 그룹 추가 시 정상 — preferences + account_tenants 반영."""
    email = _email("group_sole")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={
                "email": email,
                "password": "Sup3rSecret!",
                "groups": ["personal", "sole_proprietor"],
            },
        )
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["groups"] == ["personal", "sole_proprietor"]

    # DB 확인 — preferences.user_groups + account_tenants row.
    eng = auth_v2._get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT preferences FROM accounts WHERE id = :aid"
                ),
                {"aid": user["id"]},
            )
        ).first()
        assert row is not None
        prefs = dict(row[0] or {})
        assert prefs.get("user_groups") == ["personal", "sole_proprietor"]

        mems = (
            await conn.execute(
                text(
                    "SELECT scope_group FROM account_tenants "
                    "WHERE account_id = :aid"
                ),
                {"aid": user["id"]},
            )
        ).all()
        # personal scope 멤버십 1건 (sole_proprietor 는 별개 tenant 아님).
        assert [m[0] for m in mems] == ["personal"]


@pytest.mark.asyncio
async def test_signup_omitting_personal_is_auto_added(clean_db):
    """groups 에 personal 누락 시 자동 추가 — 모든 사용자 personal scope 보장."""
    email = _email("group_no_personal")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={
                "email": email,
                "password": "Sup3rSecret!",
                "groups": ["sole_proprietor"],
            },
        )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["groups"] == ["personal", "sole_proprietor"]


@pytest.mark.asyncio
async def test_signup_company_rejected(clean_db):
    """company 는 별도 활성화 endpoint — signup 에서는 거부."""
    email = _email("group_company")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={
                "email": email,
                "password": "Sup3rSecret!",
                "groups": ["personal", "company"],
            },
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_signup_business_rejected(clean_db):
    """business 도 별도 활성화 endpoint — signup 에서는 거부."""
    email = _email("group_business")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={
                "email": email,
                "password": "Sup3rSecret!",
                "groups": ["business"],
            },
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_signup_admin_rejected(clean_db):
    """admin 은 시스템 운영자 — 일반 가입 흐름에서는 절대 거부."""
    email = _email("group_admin")
    async with await _client() as c:
        r = await c.post(
            "/auth/v2/signup",
            json={
                "email": email,
                "password": "Sup3rSecret!",
                "groups": ["admin"],
            },
        )
    assert r.status_code == 422, r.text
