"""Account groups router — company/business 활성화 + 비활성화 통합 테스트.

흐름:
- signup → personal scope 멤버십 + user_groups=['personal']
- POST /api/v1/account/groups (company) → 새 tenant + 멤버십 + user_groups +=['company']
- GET 으로 조회
- 두 번째 회사 추가 (같은 group, 다른 tenant) → OK
- DELETE 한 멤버십 → user_groups 의 company 유지 (다른 활성 있음)
- DELETE 마지막 → user_groups 에서 company 제거
- personal 비활성화 시도 → 400
- business 도 같은 흐름
- signup 거부 그룹(admin) 은 외부 로직 — 여기서는 검증 X
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.main import app
from src.api.routers import auth_v2
from src.api.routers import account_groups as ag


TEST_PREFIX = "phase_t3_groups_"


def _email(suffix: str) -> str:
    return f"{TEST_PREFIX}{suffix}_{uuid.uuid4().hex[:6]}@example.com"


async def _cleanup() -> None:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts WHERE email LIKE :p"
            ),
            {"p": f"{TEST_PREFIX}%"},
        )
        accs = list(rows)
        for account_id, personal_tid in accs:
            # 본 테스트가 만든 추가 tenant 들을 account_tenants → tenants 순으로 삭제.
            extra_tids = (
                await conn.execute(
                    text(
                        """
                        SELECT tenant_id FROM account_tenants
                         WHERE account_id = :aid AND scope_group != 'personal'
                        """
                    ),
                    {"aid": account_id},
                )
            ).all()
            await conn.execute(
                text("DELETE FROM account_tenants WHERE account_id = :aid"),
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
            for (tid,) in extra_tids:
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :tid"),
                    {"tid": tid},
                )
            if personal_tid:
                await conn.execute(
                    text("DELETE FROM repositories WHERE tenant_id = :tid"),
                    {"tid": personal_tid},
                )
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :tid"),
                    {"tid": personal_tid},
                )


@pytest_asyncio.fixture
async def clean_db():
    await auth_v2._reset_engine_for_tests()
    await ag._reset_engine_for_tests()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await ag._reset_engine_for_tests()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _signup(c: AsyncClient, email: str, groups: list[str] | None = None) -> tuple[str, str]:
    body: dict = {"email": email, "password": "Sup3rSecret!"}
    if groups is not None:
        body["groups"] = groups
    r = await c.post("/auth/v2/signup", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["user"]["id"], data["access_token"]


# ---------------------------------------------------------------------------
# 활성화.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_company_creates_tenant_and_membership(clean_db):
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("activate_company"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Acme Co"},
            headers=h,
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["membership"]["scope_group"] == "company"
    assert body["membership"]["tenant_type"] == "company"
    assert body["membership"]["name"] == "Acme Co"
    assert body["membership"]["role"] == "owner"
    assert body["membership"]["is_active"] is True
    assert "company" in body["user_groups"]
    assert "personal" in body["user_groups"]


@pytest.mark.asyncio
async def test_activate_business_creates_tenant(clean_db):
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("activate_business"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.post(
            "/api/v1/account/groups",
            json={
                "group": "business",
                "tenant_name": "Ricky 카페",
                "description": "주말 카페 사업",
            },
            headers=h,
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["membership"]["scope_group"] == "business"
    assert "business" in body["user_groups"]


@pytest.mark.asyncio
async def test_activate_personal_rejected(clean_db):
    """personal 은 가입 시 결정 — 본 endpoint 거부."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("activate_personal"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.post(
            "/api/v1/account/groups",
            json={"group": "personal", "tenant_name": "x"},
            headers=h,
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_activate_admin_rejected(clean_db):
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("activate_admin"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.post(
            "/api/v1/account/groups",
            json={"group": "admin", "tenant_name": "system"},
            headers=h,
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_activate_unauthenticated(clean_db):
    async with await _client() as c:
        r = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "x"},
        )
    assert r.status_code in (401, 422)


@pytest.mark.asyncio
async def test_activate_two_companies_independent_rows(clean_db):
    """한 사용자가 회사 A + 회사 B 동시 보유 — 별개 멤버십 row."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("two_companies"))
        h = {"Authorization": f"Bearer {tok}"}
        r1 = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Acme A"},
            headers=h,
        )
        assert r1.status_code == 201
        r2 = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Acme B"},
            headers=h,
        )
        assert r2.status_code == 201, r2.text
        assert r1.json()["membership"]["tenant_id"] != r2.json()["membership"]["tenant_id"]

        listed = await c.get("/api/v1/account/groups", headers=h)
    assert listed.status_code == 200
    names = {m["name"] for m in listed.json()["memberships"]}
    assert {"Acme A", "Acme B"} <= names


# ---------------------------------------------------------------------------
# 조회.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_includes_personal_membership(clean_db):
    """가입 직후 list — personal 멤버십 1건만."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("list_initial"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.get("/api/v1/account/groups", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["memberships"]) == 1
    assert data["memberships"][0]["scope_group"] == "personal"
    assert data["user_groups"] == ["personal"]


# ---------------------------------------------------------------------------
# 비활성화.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_removes_group_when_last(clean_db):
    """company 1개 → 비활성화 시 user_groups 에서 제거."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("deactivate_last"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Solo Co"},
            headers=h,
        )
        tenant_id = r.json()["membership"]["tenant_id"]

        d = await c.delete(f"/api/v1/account/groups/{tenant_id}", headers=h)
    assert d.status_code == 200, d.text
    body = d.json()
    assert "company" not in body["user_groups"]
    # personal 은 그대로.
    assert "personal" in body["user_groups"]
    # 활성 멤버십에서도 사라짐.
    assert all(m["scope_group"] != "company" for m in body["memberships"])


@pytest.mark.asyncio
async def test_deactivate_keeps_group_when_other_active(clean_db):
    """회사 A + B 보유 → A 비활성화해도 group=company 는 user_groups 에 유지."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("deactivate_one_of_two"))
        h = {"Authorization": f"Bearer {tok}"}
        r1 = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Acme A"},
            headers=h,
        )
        await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Acme B"},
            headers=h,
        )
        tid_a = r1.json()["membership"]["tenant_id"]

        d = await c.delete(f"/api/v1/account/groups/{tid_a}", headers=h)
    assert d.status_code == 200
    body = d.json()
    assert "company" in body["user_groups"]
    names = {m["name"] for m in body["memberships"]}
    assert "Acme B" in names
    assert "Acme A" not in names


@pytest.mark.asyncio
async def test_deactivate_personal_rejected(clean_db):
    """personal scope 비활성화는 거부 — 사용자 단독 데이터."""
    async with await _client() as c:
        aid, tok = await _signup(c, _email("deactivate_personal"))
        h = {"Authorization": f"Bearer {tok}"}
        # personal tenant id 조회.
        eng = auth_v2._get_engine()
        async with eng.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT personal_tenant_id::text FROM accounts WHERE id = :aid"
                    ),
                    {"aid": aid},
                )
            ).first()
            personal_tid = row[0]

        d = await c.delete(f"/api/v1/account/groups/{personal_tid}", headers=h)
    assert d.status_code == 400


@pytest.mark.asyncio
async def test_deactivate_unknown_membership_404(clean_db):
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("deactivate_unknown"))
        h = {"Authorization": f"Bearer {tok}"}
        d = await c.delete(
            f"/api/v1/account/groups/{uuid.uuid4()}", headers=h
        )
    assert d.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_idempotent(clean_db):
    """이미 비활성화된 멤버십 재호출 — 200."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("idempotent"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Idem Co"},
            headers=h,
        )
        tid = r.json()["membership"]["tenant_id"]
        d1 = await c.delete(f"/api/v1/account/groups/{tid}", headers=h)
        d2 = await c.delete(f"/api/v1/account/groups/{tid}", headers=h)
    assert d1.status_code == 200
    assert d2.status_code == 200
    # 두 번째 호출에도 인덱스/상태 안정.
    assert "company" not in d2.json()["user_groups"]


# ---------------------------------------------------------------------------
# manifest endpoint 와의 통합 — 새 tenant 가 manifest.tenants 에 노출되는가.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_toggle_enable_sole_proprietor(clean_db):
    """가입 후에 sole_proprietor scope 활성화 가능."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("scope_enable"))
        h = {"Authorization": f"Bearer {tok}"}
        # 가입 시 personal 만
        r0 = await c.get("/api/v1/account/groups", headers=h)
        assert r0.json()["user_groups"] == ["personal"]
        # toggle ON
        r = await c.patch(
            "/api/v1/account/groups/scope",
            json={"scope": "sole_proprietor", "enabled": True},
            headers=h,
        )
    assert r.status_code == 200, r.text
    assert "sole_proprietor" in r.json()["user_groups"]
    assert "personal" in r.json()["user_groups"]


@pytest.mark.asyncio
async def test_scope_toggle_disable_sole_proprietor(clean_db):
    """sole_proprietor 비활성화 — personal 은 그대로."""
    async with await _client() as c:
        _aid, tok = await _signup(
            c, _email("scope_disable"), groups=["personal", "sole_proprietor"]
        )
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.patch(
            "/api/v1/account/groups/scope",
            json={"scope": "sole_proprietor", "enabled": False},
            headers=h,
        )
    assert r.status_code == 200
    assert "sole_proprietor" not in r.json()["user_groups"]
    assert "personal" in r.json()["user_groups"]


@pytest.mark.asyncio
async def test_scope_toggle_personal_rejected(clean_db):
    """personal 은 toggle 거부 — 잠금."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("scope_personal"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.patch(
            "/api/v1/account/groups/scope",
            json={"scope": "personal", "enabled": False},
            headers=h,
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scope_toggle_company_rejected(clean_db):
    """company 는 별도 endpoint — toggle 거부."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("scope_company"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.patch(
            "/api/v1/account/groups/scope",
            json={"scope": "company", "enabled": True},
            headers=h,
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scope_toggle_admin_rejected(clean_db):
    """admin 은 platform 영역 — toggle 거부."""
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("scope_admin"))
        h = {"Authorization": f"Bearer {tok}"}
        r = await c.patch(
            "/api/v1/account/groups/scope",
            json={"scope": "admin", "enabled": True},
            headers=h,
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_manifest_reflects_activated_company(clean_db):
    async with await _client() as c:
        _aid, tok = await _signup(c, _email("manifest_company"))
        h = {"Authorization": f"Bearer {tok}"}
        await c.post(
            "/api/v1/account/groups",
            json={"group": "company", "tenant_name": "Beta Co"},
            headers=h,
        )
        m = await c.get("/api/v1/manifest", headers=h)
    assert m.status_code == 200
    data = m.json()
    tenants = data["tenants"]
    scopes = {t["scope_group"] for t in tenants}
    assert "personal" in scopes
    assert "company" in scopes
    user_groups = data["user"].get("user_groups") or []
    # 회사 추가됐으니 company 도메인 (yaml: [company]) 노출.
    domain_ids = {d["id"] for d in data["domains"]}
    assert "company" in domain_ids
    assert "company" in user_groups
