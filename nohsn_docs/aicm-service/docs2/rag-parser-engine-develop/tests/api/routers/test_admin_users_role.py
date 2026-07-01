"""D36 §3 (#216) admin_users router 단위 test.

권한 검증 (super_admin gate / role whitelist / Option B / self-demote / reason)
+ helper 함수 (reasonRequired / Option B 매핑) + router registration 검증.

실제 DB 통합 (audit_logs INSERT / RLS 정책 통과) 은 후속 phase 의 smoke.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.auth.jwt_utils import create_access_token


# ---------------------------------------------------------------------------
# constants / whitelist
# ---------------------------------------------------------------------------


def test_role_whitelist_module_loaded():
    """role whitelist 6 값 + super_admin alias frozenset 존재."""
    from src.api.routers.admin_users import (
        _ROLE_WHITELIST,
        _SUPER_ADMIN_ROLES,
    )
    assert _ROLE_WHITELIST == frozenset({
        "super_admin", "owner", "admin", "editor", "viewer", "member"
    })
    assert _SUPER_ADMIN_ROLES == frozenset({"super_admin", "superadmin"})


def test_router_registered_in_main():
    """router 가 main.py 에 정상 wire 됨."""
    from src.api.main import app

    paths = {r.path for r in app.routes}
    assert "/api/v1/admin/users" in paths
    # role / role-history 도 존재.
    assert any("/api/v1/admin/users/" in p for p in paths)


def test_router_prefix():
    """router prefix 가 /api/v1/admin/users 인지."""
    from src.api.routers.admin_users import router

    assert router.prefix == "/api/v1/admin/users"


# ---------------------------------------------------------------------------
# _require_super_admin
# ---------------------------------------------------------------------------


def test_require_super_admin_401_no_header():
    """Authorization 헤더 부재 시 401."""
    from src.api.routers.admin_users import _require_super_admin

    with pytest.raises(HTTPException) as exc:
        _require_super_admin(None)
    assert exc.value.status_code == 401


def test_require_super_admin_401_empty():
    from src.api.routers.admin_users import _require_super_admin

    with pytest.raises(HTTPException) as exc:
        _require_super_admin("")
    assert exc.value.status_code == 401


def test_require_super_admin_401_no_bearer():
    from src.api.routers.admin_users import _require_super_admin

    with pytest.raises(HTTPException) as exc:
        _require_super_admin("NoBearer abc")
    assert exc.value.status_code == 401


def test_require_super_admin_401_invalid_token():
    from src.api.routers.admin_users import _require_super_admin

    with pytest.raises(HTTPException) as exc:
        _require_super_admin("Bearer not-a-jwt")
    assert exc.value.status_code == 401


def test_require_super_admin_403_member_role():
    """JWT role=member → 403."""
    from src.api.routers.admin_users import _require_super_admin

    sub = str(uuid4())
    token = create_access_token(subject=sub, tenant_id=str(uuid4()), role="member")
    with pytest.raises(HTTPException) as exc:
        _require_super_admin(f"Bearer {token}")
    assert exc.value.status_code == 403


def test_require_super_admin_403_admin_role():
    """JWT role=admin → 403 (super_admin 만 통과)."""
    from src.api.routers.admin_users import _require_super_admin

    sub = str(uuid4())
    token = create_access_token(subject=sub, tenant_id=str(uuid4()), role="admin")
    with pytest.raises(HTTPException) as exc:
        _require_super_admin(f"Bearer {token}")
    assert exc.value.status_code == 403


def test_require_super_admin_403_owner_role():
    """JWT role=owner → 403."""
    from src.api.routers.admin_users import _require_super_admin

    sub = str(uuid4())
    token = create_access_token(subject=sub, tenant_id=str(uuid4()), role="owner")
    with pytest.raises(HTTPException) as exc:
        _require_super_admin(f"Bearer {token}")
    assert exc.value.status_code == 403


def test_require_super_admin_200_super_admin_role():
    """JWT role=super_admin → 통과 (caller_id, tenant_id 반환)."""
    from src.api.routers.admin_users import _require_super_admin

    sub = str(uuid4())
    tid = str(uuid4())
    token = create_access_token(subject=sub, tenant_id=tid, role="super_admin")
    caller_id, ret_tid = _require_super_admin(f"Bearer {token}")
    assert str(caller_id) == sub
    assert ret_tid == tid


def test_require_super_admin_200_superadmin_alias():
    """JWT role=superadmin (alias) → 통과."""
    from src.api.routers.admin_users import _require_super_admin

    sub = str(uuid4())
    token = create_access_token(subject=sub, tenant_id=str(uuid4()), role="superadmin")
    caller_id, _ = _require_super_admin(f"Bearer {token}")
    assert str(caller_id) == sub


# ---------------------------------------------------------------------------
# reason 필수 조건 helpers
# ---------------------------------------------------------------------------


def test_reason_required_super_admin_grant():
    """new_role='super_admin' → 항상 reason 필수."""
    from src.api.routers.admin_users import _reason_required

    assert _reason_required("member", "super_admin") is True
    assert _reason_required("admin", "super_admin") is True
    assert _reason_required("owner", "super_admin") is True


def test_reason_required_super_admin_revoke():
    """old_role='super_admin' AND new != 'super_admin' → reason 필수."""
    from src.api.routers.admin_users import _reason_required

    assert _reason_required("super_admin", "admin") is True
    assert _reason_required("super_admin", "member") is True


def test_reason_required_promotion():
    """member/viewer/editor → admin/owner: 권한 상승, reason 필수."""
    from src.api.routers.admin_users import _reason_required

    assert _reason_required("member", "admin") is True
    assert _reason_required("viewer", "admin") is True
    assert _reason_required("editor", "owner") is True


def test_reason_required_no_change():
    """동일 role → reason 선택."""
    from src.api.routers.admin_users import _reason_required

    assert _reason_required("member", "member") is False
    assert _reason_required("admin", "admin") is False


def test_reason_required_demotion_not_super():
    """admin → member 같은 일반 강등은 reason 선택."""
    from src.api.routers.admin_users import _reason_required

    assert _reason_required("admin", "member") is False
    assert _reason_required("owner", "viewer") is False


def test_reason_required_lateral():
    """member ↔ viewer 같은 lateral 변경은 reason 선택."""
    from src.api.routers.admin_users import _reason_required

    assert _reason_required("member", "viewer") is False
    assert _reason_required("viewer", "editor") is False


# ---------------------------------------------------------------------------
# is_promotion
# ---------------------------------------------------------------------------


def test_is_promotion_member_to_admin():
    from src.api.routers.admin_users import _is_promotion

    assert _is_promotion("member", "admin") is True
    assert _is_promotion("viewer", "admin") is True
    assert _is_promotion("editor", "owner") is True


def test_is_promotion_negative_cases():
    from src.api.routers.admin_users import _is_promotion

    assert _is_promotion("admin", "member") is False
    assert _is_promotion("member", "member") is False
    assert _is_promotion("super_admin", "admin") is False  # demote, not promote


# ---------------------------------------------------------------------------
# pydantic models
# ---------------------------------------------------------------------------


def test_role_update_body_validation():
    from src.api.routers.admin_users import RoleUpdateBody

    # 정상
    body = RoleUpdateBody(
        tenant_id=str(uuid4()),
        role="super_admin",
        reason="test reason",
    )
    assert body.role == "super_admin"
    assert body.reason == "test reason"


def test_role_update_body_optional_reason():
    from src.api.routers.admin_users import RoleUpdateBody

    body = RoleUpdateBody(tenant_id=str(uuid4()), role="member")
    assert body.reason is None


def test_role_update_response_includes_membership_id():
    from src.api.routers.admin_users import RoleUpdateResponse

    r = RoleUpdateResponse(
        account_id=str(uuid4()),
        tenant_id=str(uuid4()),
        membership_id=str(uuid4()),
        old_role="member",
        new_role="super_admin",
        audit_log_id=None,
    )
    assert r.membership_id is not None


# ---------------------------------------------------------------------------
# response models — UserMembershipItem / RoleHistoryItem
# ---------------------------------------------------------------------------


def test_user_membership_item_optional_fields():
    from src.api.routers.admin_users import UserMembershipItem

    item = UserMembershipItem(
        account_id=str(uuid4()),
        tenant_id=str(uuid4()),
        role="member",
        membership_id=str(uuid4()),
    )
    assert item.email is None
    assert item.name is None
    assert item.is_active is None


def test_role_history_item_optional_fields():
    from src.api.routers.admin_users import RoleHistoryItem

    item = RoleHistoryItem(
        audit_log_id=str(uuid4()),
        actor_id=None,
        old_role=None,
        new_role=None,
        reason=None,
        created_at=None,
        target_tenant_id=None,
    )
    assert item.audit_log_id is not None


# ---------------------------------------------------------------------------
# Endpoint-level — TestClient (DB-free paths: 401/403/422/400)
# ---------------------------------------------------------------------------


def _make_token(role: str, sub: str | None = None, tid: str | None = None) -> str:
    sub = sub or str(uuid4())
    tid = tid or str(uuid4())
    return create_access_token(subject=sub, tenant_id=tid, role=role)


def _client():
    from fastapi.testclient import TestClient
    from src.api.main import app

    return TestClient(app)


def test_endpoint_list_users_401_no_auth():
    """GET /admin/users — Authorization 없음 → 401."""
    c = _client()
    r = c.get("/api/v1/admin/users")
    assert r.status_code == 401


def test_endpoint_list_users_403_admin():
    """GET /admin/users — JWT role=admin → 403 (super_admin 만)."""
    c = _client()
    token = _make_token("admin")
    r = c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_endpoint_list_users_403_member():
    c = _client()
    token = _make_token("member")
    r = c.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_endpoint_role_update_401_no_auth():
    """POST /admin/users/{aid}/role — Authorization 없음 → 401."""
    c = _client()
    r = c.post(
        f"/api/v1/admin/users/{uuid4()}/role",
        json={"tenant_id": str(uuid4()), "role": "member"},
    )
    assert r.status_code == 401


def test_endpoint_role_update_403_admin():
    """POST /admin/users/{aid}/role — JWT role=admin → 403."""
    c = _client()
    token = _make_token("admin")
    r = c.post(
        f"/api/v1/admin/users/{uuid4()}/role",
        json={"tenant_id": str(uuid4()), "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_endpoint_role_update_422_invalid_role():
    """POST /admin/users/{aid}/role — role whitelist 외 → 422."""
    c = _client()
    token = _make_token("super_admin")
    r = c.post(
        f"/api/v1/admin/users/{uuid4()}/role",
        json={"tenant_id": str(uuid4()), "role": "not_a_real_role"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_endpoint_role_update_400_invalid_uuid():
    """POST /admin/users/{aid}/role — invalid UUID → 400."""
    c = _client()
    token = _make_token("super_admin")
    r = c.post(
        "/api/v1/admin/users/not-a-uuid/role",
        json={"tenant_id": str(uuid4()), "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_endpoint_role_history_401_no_auth():
    c = _client()
    r = c.get(f"/api/v1/admin/users/{uuid4()}/role-history")
    assert r.status_code == 401


def test_endpoint_role_history_403_admin():
    c = _client()
    token = _make_token("admin")
    r = c.get(
        f"/api/v1/admin/users/{uuid4()}/role-history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_endpoint_role_history_400_invalid_uuid():
    c = _client()
    token = _make_token("super_admin")
    r = c.get(
        "/api/v1/admin/users/not-a-uuid/role-history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Mock-based tests — DB 의존 path (Option B / self-demote / success) 시뮬레이션.
# core_engine + record_event 모킹으로 실 DB 없이 비즈니스 로직 검증.
# ---------------------------------------------------------------------------


from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


class _MockResultRow:
    """SELECT (.first()) 결과 행 mock."""
    def __init__(self, *cols):
        self.cols = cols

    def __iter__(self):
        return iter(self.cols)

    def __getitem__(self, i):
        return self.cols[i]


class _MockExecuteResult:
    def __init__(self, first_val=None, scalar_val=None, all_val=None):
        self._first = first_val
        self._scalar = scalar_val
        self._all = all_val or []

    def first(self):
        return self._first

    def scalar(self):
        return self._scalar

    def all(self):
        return self._all


def _mock_engine_with_membership(
    *,
    membership_id,
    old_role: str,
    personal_tid,
    target_email: str,
    other_super_count: int = 0,
):
    """core_engine.begin() async ctxmgr 를 mock — execute 는 시퀀스 처리.

    sequence:
    1. SELECT pg_advisory_xact_lock(...) — None.
    2. SELECT membership row — _MockResultRow.
    3. (opt) SELECT count(*) for self-demote check — int.
    4. UPDATE — None.
    """
    conn = MagicMock()
    call_count = {"i": 0}
    membership_row = _MockResultRow(
        membership_id, old_role, personal_tid, target_email
    )

    async def _execute(*_args, **_kwargs):
        call_count["i"] += 1
        # 1: advisory lock
        if call_count["i"] == 1:
            return _MockExecuteResult()
        # 2: membership SELECT
        if call_count["i"] == 2:
            return _MockExecuteResult(first_val=membership_row)
        # 3+: count or update — return 적절히
        # role-history 에선 다른 sequence (count_sql 후 list)
        return _MockExecuteResult(scalar_val=other_super_count, first_val=None)

    conn.execute = _execute

    @asynccontextmanager
    async def _begin():
        yield conn

    eng_mock = MagicMock()
    eng_mock.begin = _begin
    return eng_mock


def test_endpoint_role_update_404_membership_missing():
    """POST /admin/users/{aid}/role — membership row 부재 → 404."""

    @asynccontextmanager
    async def _begin():
        conn = MagicMock()

        async def _execute(*_args, **_kwargs):
            return _MockExecuteResult(first_val=None)

        conn.execute = _execute
        yield conn

    eng_mock = MagicMock()
    eng_mock.begin = _begin

    c = _client()
    token = _make_token("super_admin")

    with patch("src.api.routers.admin_users.core_engine", eng_mock):
        r = c.post(
            f"/api/v1/admin/users/{uuid4()}/role",
            json={"tenant_id": str(uuid4()), "role": "member"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 404


def test_endpoint_role_update_422_option_b_violation():
    """new_role='super_admin' + tenant_id != personal_tenant_id → 422."""
    membership_id = uuid4()
    personal_tid = uuid4()
    target_tenant = uuid4()  # 의도적으로 personal 과 다름.

    eng_mock = _mock_engine_with_membership(
        membership_id=membership_id,
        old_role="member",
        personal_tid=personal_tid,
        target_email="t@t.t",
    )

    c = _client()
    token = _make_token("super_admin")

    with patch("src.api.routers.admin_users.core_engine", eng_mock):
        r = c.post(
            f"/api/v1/admin/users/{uuid4()}/role",
            json={
                "tenant_id": str(target_tenant),
                "role": "super_admin",
                "reason": "elevate",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422
    assert "personal tenant" in r.json().get("detail", "").lower()


def test_endpoint_role_update_422_reason_required_grant():
    """super_admin grant 시 reason 없음 → 422."""
    membership_id = uuid4()
    personal_tid = uuid4()  # Option B 통과: target_tenant == personal_tid.

    eng_mock = _mock_engine_with_membership(
        membership_id=membership_id,
        old_role="member",
        personal_tid=personal_tid,
        target_email="t@t.t",
    )

    c = _client()
    token = _make_token("super_admin")

    with patch("src.api.routers.admin_users.core_engine", eng_mock):
        r = c.post(
            f"/api/v1/admin/users/{uuid4()}/role",
            json={"tenant_id": str(personal_tid), "role": "super_admin"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422
    assert "reason" in r.json().get("detail", "").lower()


def test_endpoint_role_update_200_success():
    """정상 path — record_event 도 mock — 200 + audit_log_id 응답."""
    membership_id = uuid4()
    personal_tid = uuid4()
    caller_id = uuid4()

    eng_mock = _mock_engine_with_membership(
        membership_id=membership_id,
        old_role="member",
        personal_tid=personal_tid,
        target_email="t@t.t",
    )
    audit_mock = AsyncMock(return_value=MagicMock(id=uuid4()))

    c = _client()
    token = _make_token("super_admin", sub=str(caller_id))

    with (
        patch("src.api.routers.admin_users.core_engine", eng_mock),
        patch("src.api.routers.admin_users.record_event", audit_mock),
    ):
        r = c.post(
            f"/api/v1/admin/users/{uuid4()}/role",
            json={
                "tenant_id": str(personal_tid),
                "role": "super_admin",
                "reason": "promote to super_admin",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_role"] == "super_admin"
    assert body["old_role"] == "member"
    assert body["membership_id"] == str(membership_id)
    assert body["audit_log_id"] is not None
    # record_event 호출 검증.
    audit_mock.assert_awaited_once()
    call_kwargs = audit_mock.await_args.kwargs
    assert call_kwargs["actor_tier"] == "superadmin"
    assert call_kwargs["event_kind"] == "tenant_membership.role_update"
    assert call_kwargs["resource_type"] == "tenant_membership"
    assert call_kwargs["owner_scope"] == "admin"
    assert call_kwargs["detail"]["old_role"] == "member"
    assert call_kwargs["detail"]["new_role"] == "super_admin"
    assert call_kwargs["detail"]["reason"] == "promote to super_admin"


def test_endpoint_role_update_409_self_demote_last_super_admin():
    """마지막 super_admin 본인 personal tenant 에서 강등 시도 → 409."""
    membership_id = uuid4()
    caller_id = uuid4()
    personal_tid = uuid4()

    # 사용자가 caller 본인 → target_account = caller. old_role='super_admin'.
    # other_super_count = 0 → 마지막.
    eng_mock = _mock_engine_with_membership(
        membership_id=membership_id,
        old_role="super_admin",
        personal_tid=personal_tid,
        target_email="me@me.me",
        other_super_count=0,
    )

    c = _client()
    token = _make_token("super_admin", sub=str(caller_id))

    with patch("src.api.routers.admin_users.core_engine", eng_mock):
        r = c.post(
            f"/api/v1/admin/users/{caller_id}/role",
            json={
                "tenant_id": str(personal_tid),
                "role": "admin",
                "reason": "step down",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 409
    assert "self-demote" in r.json().get("detail", "").lower()


def test_endpoint_role_update_200_self_demote_with_other_super():
    """다른 super_admin 존재 시 자기 강등 → 200."""
    membership_id = uuid4()
    caller_id = uuid4()
    personal_tid = uuid4()

    eng_mock = _mock_engine_with_membership(
        membership_id=membership_id,
        old_role="super_admin",
        personal_tid=personal_tid,
        target_email="me@me.me",
        other_super_count=2,  # 다른 super_admin 존재.
    )
    audit_mock = AsyncMock(return_value=MagicMock(id=uuid4()))

    c = _client()
    token = _make_token("super_admin", sub=str(caller_id))

    with (
        patch("src.api.routers.admin_users.core_engine", eng_mock),
        patch("src.api.routers.admin_users.record_event", audit_mock),
    ):
        r = c.post(
            f"/api/v1/admin/users/{caller_id}/role",
            json={
                "tenant_id": str(personal_tid),
                "role": "admin",
                "reason": "step down",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text


def test_endpoint_list_users_200_super_admin():
    """GET /admin/users — super_admin → 200 (mock empty result)."""

    @asynccontextmanager
    async def _begin():
        conn = MagicMock()

        async def _execute(*_args, **_kwargs):
            return _MockExecuteResult(all_val=[], scalar_val=0)

        conn.execute = _execute
        yield conn

    eng_mock = MagicMock()
    eng_mock.begin = _begin

    c = _client()
    token = _make_token("super_admin")

    with patch("src.api.routers.admin_users.core_engine", eng_mock):
        r = c.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_endpoint_role_history_200_super_admin():
    """GET /role-history — super_admin → 200 (mock empty)."""

    @asynccontextmanager
    async def _begin():
        conn = MagicMock()

        async def _execute(*_args, **_kwargs):
            return _MockExecuteResult(all_val=[])

        conn.execute = _execute
        yield conn

    eng_mock = MagicMock()
    eng_mock.begin = _begin

    c = _client()
    token = _make_token("super_admin")

    with patch("src.api.routers.admin_users.core_engine", eng_mock):
        r = c.get(
            f"/api/v1/admin/users/{uuid4()}/role-history",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["items"] == []
