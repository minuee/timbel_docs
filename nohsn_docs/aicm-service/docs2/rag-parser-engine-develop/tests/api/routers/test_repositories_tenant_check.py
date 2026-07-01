"""Fix C (2026-05-19) — repositories.py path tenant_id 검증 helper 단위 테스트.

``GET/POST /tenants/{tenant_id}/repositories`` 의 path tenant_id 가 인증된
principal 의 tenant_id 와 일치하지 않으면 403 으로 차단되는지 검증.

4 시나리오:
1. 무인증 모드 (LUCAS_AUTH_DISABLED) — path tenant 자유 진입.
2. 인증 모드 + path == authed → 통과.
3. 인증 모드 + path != authed → 403.
4. admin role + cross-tenant → 403 (super admin 시나리오 별도).

PATCH/DELETE 는 ``get_current_tenant_id`` dependency 가 tenant_id 를 직접 주입
하므로 path 와 dependency 가 동일 → 별도 검증 불필요.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.api.routers.repositories import _assert_tenant_match


_TENANT_A = uuid4()
_TENANT_B = uuid4()


def test_auth_disabled_bypass_allows_any_path_tenant():
    """무인증 모드 (LUCAS_AUTH_DISABLED) — path tenant 자유 진입 → 통과."""
    principal = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "role": "admin",
        "auth_v2": False,
        "auth_disabled": True,
    }
    # 의도적으로 다른 tenant 진입 — 무인증 모드이므로 통과.
    _assert_tenant_match(_TENANT_A, principal)


def test_authed_path_match_ok():
    """인증 모드 + path == authed tenant → 통과."""
    principal = {
        "user_id": str(uuid4()),
        "tenant_id": str(_TENANT_A),
        "role": "member",
        "auth_v2": True,
    }
    _assert_tenant_match(_TENANT_A, principal)


def test_authed_path_mismatch_raises_403():
    """인증 모드 + path != authed tenant → 403."""
    principal = {
        "user_id": str(uuid4()),
        "tenant_id": str(_TENANT_A),
        "role": "member",
        "auth_v2": True,
    }
    with pytest.raises(HTTPException) as exc_info:
        _assert_tenant_match(_TENANT_B, principal)
    assert exc_info.value.status_code == 403
    assert "불일치" in str(exc_info.value.detail)
    assert str(_TENANT_B) in str(exc_info.value.detail)
    assert str(_TENANT_A) in str(exc_info.value.detail)


def test_admin_role_cross_tenant_still_blocked():
    """admin role 도 자기 tenant 만 — cross-tenant 진입 차단.

    Super admin 시나리오 (모든 tenant 접근) 는 별도 endpoint 권장 — 이 helper
    는 단일 tenant scope 전제.
    """
    principal = {
        "user_id": str(uuid4()),
        "tenant_id": str(_TENANT_A),
        "role": "admin",
        "auth_v2": True,
    }
    with pytest.raises(HTTPException) as exc_info:
        _assert_tenant_match(_TENANT_B, principal)
    assert exc_info.value.status_code == 403


def test_no_authed_tenant_skip_check():
    """인증된 tenant_id 가 None → 추가 차단 없이 통과 (회귀 0).

    이 경우 ``get_current_tenant_id`` 등 다른 dependency 가 별도로 enforce 하므로
    helper 단계에서 추가 가드 불필요. (PATCH/DELETE 처럼 별도 dependency 가 처리.)
    """
    principal = {
        "user_id": None,
        "tenant_id": None,
        "role": "viewer",
        "auth_v2": False,
    }
    # path tenant 자유 진입 — 추가 차단 없음.
    _assert_tenant_match(_TENANT_A, principal)
