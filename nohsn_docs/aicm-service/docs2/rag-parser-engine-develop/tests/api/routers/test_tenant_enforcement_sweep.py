"""Phase 1.5A Task 8c.2 — cross-tenant 위장 차단 sweep smoke tests.

각 router 의 ``_scope`` / ``_resolve_tenant`` helper 가 헤더 mismatch 를
401 로 거부하는지 검증. (Helper 자체의 단위 테스트는
``test_tenant_scope_helper.py``.)
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.auth.jwt_utils import create_access_token
from src.api.routers.agents_v1 import _resolve_tenant as agents_resolve_tenant
from src.api.routers.chat_sessions_v1 import _scope_from_headers as sessions_scope
from src.api.routers.context_v1 import _scope as context_scope
from src.api.routers.custom_tools_v1 import _resolve_tenant as ct_resolve_tenant
from src.api.routers.inbox import _scope as inbox_scope


_ACCOUNT = str(uuid4())
_TENANT_A = str(uuid4())
_TENANT_B = str(uuid4())


def _bearer(account_id: str, tenant_id: str | None) -> str:
    token = create_access_token(subject=account_id, tenant_id=tenant_id)
    return f"Bearer {token}"


# ---------------------------------------------------------------------------
# 1. chat_sessions_v1._scope_from_headers
# ---------------------------------------------------------------------------


def test_chat_sessions_v1_header_mismatch_401():
    """JWT tenant=A + X-Tenant-ID=B → 401."""
    with pytest.raises(HTTPException) as exc_info:
        sessions_scope(_bearer(_ACCOUNT, _TENANT_A), _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in str(exc_info.value.detail)


def test_chat_sessions_v1_header_match_ok():
    """JWT tenant=A + X-Tenant-ID=A → OK."""
    aid, tid = sessions_scope(_bearer(_ACCOUNT, _TENANT_A), _TENANT_A)
    assert str(aid) == _ACCOUNT
    assert str(tid) == _TENANT_A


# ---------------------------------------------------------------------------
# 2. context_v1._scope
# ---------------------------------------------------------------------------


def test_context_v1_header_mismatch_401():
    with pytest.raises(HTTPException) as exc_info:
        context_scope(_bearer(_ACCOUNT, _TENANT_A), _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in str(exc_info.value.detail)


def test_context_v1_header_match_ok():
    aid, tid, role = context_scope(_bearer(_ACCOUNT, _TENANT_A), _TENANT_A)
    assert str(aid) == _ACCOUNT
    assert str(tid) == _TENANT_A
    assert role == "member"


# ---------------------------------------------------------------------------
# 3. inbox._scope
# ---------------------------------------------------------------------------


def test_inbox_header_mismatch_401():
    with pytest.raises(HTTPException) as exc_info:
        inbox_scope(_bearer(_ACCOUNT, _TENANT_A), _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in str(exc_info.value.detail)


def test_inbox_header_match_ok():
    aid, tid = inbox_scope(_bearer(_ACCOUNT, _TENANT_A), _TENANT_A)
    assert str(aid) == _ACCOUNT
    assert str(tid) == _TENANT_A


# ---------------------------------------------------------------------------
# 4. agents_v1._resolve_tenant
# ---------------------------------------------------------------------------


def test_agents_v1_header_mismatch_401():
    """token tenant=A + X-Tenant-ID=B → 401."""
    with pytest.raises(HTTPException) as exc_info:
        agents_resolve_tenant(_TENANT_A, _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in str(exc_info.value.detail)


def test_agents_v1_header_match_ok():
    tid = agents_resolve_tenant(_TENANT_A, _TENANT_A)
    assert str(tid) == _TENANT_A


# ---------------------------------------------------------------------------
# 5. custom_tools_v1._resolve_tenant
# ---------------------------------------------------------------------------


def test_custom_tools_v1_header_mismatch_401():
    with pytest.raises(HTTPException) as exc_info:
        ct_resolve_tenant(_TENANT_A, _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in str(exc_info.value.detail)


def test_custom_tools_v1_header_match_ok():
    tid = ct_resolve_tenant(_TENANT_A, _TENANT_A)
    assert str(tid) == _TENANT_A
