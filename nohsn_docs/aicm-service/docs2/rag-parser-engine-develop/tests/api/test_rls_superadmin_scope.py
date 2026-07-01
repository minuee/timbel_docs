"""D34 §5 — superadmin scope 매핑 unit test.

JWT role=super_admin → RLSContext.scope='superadmin' + tenant_id=None.
JWT role=owner/admin/etc → 기존 admin scope 유지 (격하 X).
"""
from __future__ import annotations

import pytest

from src.api.middleware.rls_context_middleware import _build_rls_context


def _build_headers(role: str, tenant_id: str | None) -> dict[bytes, bytes]:
    """JWT 토큰을 직접 생성 → Authorization 헤더 빌드."""
    from src.api.auth.jwt_utils import create_access_token

    sub = "00000000-0000-0000-0000-000000000001"
    tid = tenant_id or "00000000-0000-0000-0000-0000000000ff"
    token = create_access_token(
        subject=sub, tenant_id=tid, role=role, ttl_hours=1
    )
    return {b"authorization": f"Bearer {token}".encode("latin-1")}


def test_super_admin_role_maps_to_superadmin_scope():
    """JWT role=super_admin → scope='superadmin', tenant_id=None."""
    headers = _build_headers(
        role="super_admin",
        tenant_id="00000000-0000-0000-0000-0000000000aa",
    )
    ctx = _build_rls_context(headers, allow_header_fallback=False)
    assert ctx.scope == "superadmin", f"expected superadmin, got {ctx.scope!r}"
    assert ctx.tenant_id is None, (
        f"superadmin scope should have tenant_id=None (cross-tenant), got {ctx.tenant_id!r}"
    )


def test_superadmin_alias_role_maps_same():
    """JWT role=superadmin (alias) → 동일 매핑."""
    headers = _build_headers(
        role="superadmin",
        tenant_id="00000000-0000-0000-0000-0000000000bb",
    )
    ctx = _build_rls_context(headers, allow_header_fallback=False)
    assert ctx.scope == "superadmin"
    assert ctx.tenant_id is None


def test_owner_role_remains_admin():
    """JWT role=owner → admin scope (D33 동작 보존)."""
    headers = _build_headers(
        role="owner",
        tenant_id="00000000-0000-0000-0000-0000000000cc",
    )
    ctx = _build_rls_context(headers, allow_header_fallback=False)
    assert ctx.scope == "admin"
    assert ctx.tenant_id == "00000000-0000-0000-0000-0000000000cc"


def test_admin_role_remains_admin():
    """JWT role=admin → admin scope (D33 동작 보존)."""
    headers = _build_headers(
        role="admin",
        tenant_id="00000000-0000-0000-0000-0000000000dd",
    )
    ctx = _build_rls_context(headers, allow_header_fallback=False)
    assert ctx.scope == "admin"


def test_member_role_remains_admin():
    """JWT role=member → admin scope (D33 동작 보존)."""
    headers = _build_headers(
        role="member",
        tenant_id="00000000-0000-0000-0000-0000000000ee",
    )
    ctx = _build_rls_context(headers, allow_header_fallback=False)
    assert ctx.scope == "admin"


def test_unknown_role_maps_to_empty():
    """JWT role=unknown → scope='' (default-deny)."""
    headers = _build_headers(
        role="random_role_not_recognized",
        tenant_id="00000000-0000-0000-0000-000000000011",
    )
    ctx = _build_rls_context(headers, allow_header_fallback=False)
    assert ctx.scope == ""


@pytest.mark.asyncio
async def test_bind_superadmin_scope_helper():
    """bind_superadmin_scope() async ctxmgr — RLSContext 정상 set."""
    from src.api.middleware.rls_context import (
        RLSContext,
        bind_superadmin_scope,
        get_rls_context,
        reset_rls_context,
        set_rls_context,
    )

    # 사전 admin scope (middleware 가 set 한 상황).
    admin_ctx = RLSContext(
        scope="admin", agent_id=None, tenant_id="00000000-0000-0000-0000-000000000001"
    )
    token = set_rls_context(admin_ctx)
    try:
        async with bind_superadmin_scope(subject="ricky", path="/admin/cross-tenant"):
            inside = get_rls_context()
            assert inside is not None
            assert inside.scope == "superadmin"
            assert inside.tenant_id is None
            assert inside.agent_id is None

        # 종료 후 원복.
        outside = get_rls_context()
        assert outside == admin_ctx
    finally:
        reset_rls_context(token)


def test_superadmin_scope_in_rlsscope_literal():
    """RLSScope literal 에 'superadmin' 포함 검증 (타입 시스템)."""
    from typing import get_args

    from src.api.middleware.rls_context import RLSScope

    args = get_args(RLSScope)
    assert "superadmin" in args
    assert "system" in args
    assert "agent" in args
    assert "admin" in args
