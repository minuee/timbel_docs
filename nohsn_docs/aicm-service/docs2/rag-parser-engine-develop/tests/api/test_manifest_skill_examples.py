"""``GET /api/v1/manifest/skill_examples`` — KMS-Plus P0.2.

검증 항목
---------
1. Bearer 누락 → 401/422.
2. 카테고리 1개 이상 반환 (active skill yaml 이 존재한다는 가정 — 시드된 admin
   사용자라면 admin 표시 (``user_groups`` 에 'admin' 포함) 으로 모든 카테고리 노출).
3. business-only 사용자(``user_groups=['business']``) 는 ``personal`` scope skill
   카테고리에 personal-only skill 이 보이지 않는다 (scope 필터링).
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.main import app
from src.api.routers import auth_v2, manifest as manifest_mod
from src.core import database as core_db


TEST_EMAIL_PREFIX = "p02_skill_ex_"


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
    await manifest_mod._reset_engine_for_tests()
    await core_db.engine.dispose()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await manifest_mod._reset_engine_for_tests()
    await core_db.engine.dispose()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _signup_and_get_token(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/v2/signup",
        json={"email": email, "password": "Sup3rSecret!", "name": "ExTester"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"]


async def _set_user_groups(account_id: str, groups: list[str]) -> None:
    eng = auth_v2._get_engine()
    prefs = json.dumps({"user_groups": groups})
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "UPDATE accounts SET preferences = CAST(:p AS jsonb) "
                "WHERE id = :aid"
            ),
            {"p": prefs, "aid": account_id},
        )


# ---------------------------------------------------------------------------
# 1. Bearer 누락
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_examples_requires_bearer(clean_db):
    async with await _client() as c:
        r = await c.get("/api/v1/manifest/skill_examples")
    # FastAPI Header(...) → 422 (missing required header) 또는 본 라우터의 401.
    assert r.status_code in (401, 422), r.text


# ---------------------------------------------------------------------------
# 2. admin 사용자 — 카테고리 반환.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_examples_returns_categories_for_admin(clean_db):
    async with await _client() as c:
        token, aid = await _signup_and_get_token(c, _email("admin"))
        await _set_user_groups(aid, ["admin"])
        r = await c.get(
            "/api/v1/manifest/skill_examples",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    cats = data.get("categories")
    assert isinstance(cats, dict)
    # admin 은 모든 scope 의 skill 노출 — yaml 디렉토리에 active skill 이 있다면
    # 적어도 1개 카테고리.
    assert len(cats) >= 1
    # 각 카테고리의 example shape 검증.
    for cat_name, items in cats.items():
        assert isinstance(cat_name, str) and cat_name
        assert isinstance(items, list)
        for it in items:
            assert "skill_id" in it and "text" in it
            assert isinstance(it["skill_id"], str) and it["skill_id"]
            assert isinstance(it["text"], str) and it["text"]


# ---------------------------------------------------------------------------
# 3. scope filtering — personal-only skill 은 business-only 사용자에게 안 보임.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_examples_scope_filtered(clean_db):
    """admin / business-only 두 사용자의 카테고리 키 집합 차이 검증.

    admin 응답에는 'personal' 카테고리가 들어있을 것 (yaml 에 personal scope
    skill 이 다수 존재). business-only 사용자에게는 'personal' 카테고리가
    빈/누락 — scope 필터가 작동하면 personal skill 이 노출되지 않는다.
    """
    async with await _client() as c:
        # admin (모든 scope)
        token_a, aid_a = await _signup_and_get_token(c, _email("a_admin"))
        await _set_user_groups(aid_a, ["admin"])
        r_a = await c.get(
            "/api/v1/manifest/skill_examples",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_a.status_code == 200
        cats_a = r_a.json().get("categories", {})

        # business-only
        token_b, aid_b = await _signup_and_get_token(c, _email("b_biz"))
        await _set_user_groups(aid_b, ["business"])
        r_b = await c.get(
            "/api/v1/manifest/skill_examples",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r_b.status_code == 200
        cats_b = r_b.json().get("categories", {})

    # admin 에는 personal 카테고리가 노출 (yaml 에 personal scope skill 다수).
    if "personal" in cats_a:
        # business 사용자에게는 personal skill (skill_id) 이 노출되지 않아야 함.
        # 카테고리 자체가 없거나, 있어도 admin 의 skill 들과 disjoint.
        admin_personal_skills = {
            it["skill_id"] for it in cats_a.get("personal", [])
        }
        biz_personal_skills = {
            it["skill_id"] for it in cats_b.get("personal", [])
        }
        # business-only 가 personal-only skill 을 본다면 누설.
        assert not (admin_personal_skills & biz_personal_skills) or (
            len(biz_personal_skills) == 0
        )


# ---------------------------------------------------------------------------
# 4. role_min 검사 — viewer 사용자에게 role_min=admin skill 누설 차단 (P0.2).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_examples_role_min_blocks_lower_role(clean_db):
    """expense_approval (role_min=admin) 은 viewer 권한 사용자에게 노출되지 않음.

    viewer 사용자 = user_groups 비어있음 + tenant_memberships.role='viewer'.
    role_min=admin skill 의 trigger_examples 가 어느 카테고리에도 들어가면 누설.
    """
    async with await _client() as c:
        token, aid = await _signup_and_get_token(c, _email("viewer"))
        # tenant 멤버십을 viewer 로 다운그레이드. signup 은 owner 로 생성됨.
        eng = auth_v2._get_engine()
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE tenant_memberships SET role = 'viewer' "
                    "WHERE account_id = :aid"
                ),
                {"aid": aid},
            )
        # user_groups 에 admin 이 없도록 명시 — viewer 만.
        await _set_user_groups(aid, [])
        r = await c.get(
            "/api/v1/manifest/skill_examples",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    cats = r.json().get("categories", {})
    # 모든 카테고리의 모든 example 의 skill_id 합집합.
    seen_skills: set[str] = set()
    for items in cats.values():
        for it in items:
            seen_skills.add(it["skill_id"])
    # role_min=admin 인 expense_approval 은 viewer 에게 보이면 안 됨.
    assert "expense_approval" not in seen_skills, (
        f"role_min=admin skill leaked to viewer: seen={seen_skills}"
    )
