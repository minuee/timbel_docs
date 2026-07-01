"""Phase 1.5A Task 8c — chat_v1._scope() JWT tenant claim 강제.

GPT-5.5 deep dive 발견: 기존 _scope() 는 X-Tenant-ID 헤더가 JWT 의
``tenant_id`` claim 보다 *우선* 이었음 → 헤더 위조로 cross-tenant 위장 가능.

이 테스트는 _scope() 가 JWT claim 만 신뢰하고, 헤더 != JWT 일 때 401 을
반환함을 검증.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.auth.jwt_utils import create_access_token
from src.api.routers.chat_v1 import _scope


_ACCOUNT_A = str(uuid4())
_TENANT_A = str(uuid4())
_TENANT_B = str(uuid4())


def _bearer(account_id: str, tenant_id: str | None) -> str:
    token = create_access_token(subject=account_id, tenant_id=tenant_id)
    return f"Bearer {token}"


def test_jwt_only_no_header_ok():
    """JWT tenant=A, no X-Tenant-ID 헤더 → JWT claim 사용."""
    aid, tid = _scope(_bearer(_ACCOUNT_A, _TENANT_A), None)
    assert str(aid) == _ACCOUNT_A
    assert str(tid) == _TENANT_A


def test_header_matches_jwt_ok():
    """JWT tenant=A, header X-Tenant-ID=A → 일치, 통과."""
    aid, tid = _scope(_bearer(_ACCOUNT_A, _TENANT_A), _TENANT_A)
    assert str(aid) == _ACCOUNT_A
    assert str(tid) == _TENANT_A


def test_header_mismatches_jwt_401():
    """JWT tenant=A, header X-Tenant-ID=B → 401 'tenant claim mismatch'.

    이게 핵심 보안 회귀 가드 — 헤더 위조를 막는다.
    """
    with pytest.raises(HTTPException) as exc_info:
        _scope(_bearer(_ACCOUNT_A, _TENANT_A), _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in exc_info.value.detail


def test_no_jwt_unauthorized():
    """missing/invalid Authorization → 401 (기존 동작 sanity)."""
    with pytest.raises(HTTPException) as exc_info:
        _scope("", None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        _scope("NotBearer xxx", None)
    assert exc_info.value.status_code == 401


def test_invalid_token_401():
    """Bearer 인데 서명 깨진 token → 401."""
    with pytest.raises(HTTPException) as exc_info:
        _scope("Bearer not.a.real.jwt.token", None)
    assert exc_info.value.status_code == 401


def test_jwt_no_tenant_no_header_400():
    """JWT 에 tenant_id=None + 헤더 없음 → 400 missing scope (기존 동작)."""
    with pytest.raises(HTTPException) as exc_info:
        _scope(_bearer(_ACCOUNT_A, None), None)
    assert exc_info.value.status_code == 400


def test_jwt_no_tenant_with_header_401():
    """JWT 에 tenant_id=None + 헤더 = B → claim 부재인데 헤더로 권한 상승 시도.

    JWT claim 만 신뢰하는 정책상 거부 (헤더로 tenant 주장 불가).
    """
    with pytest.raises(HTTPException) as exc_info:
        _scope(_bearer(_ACCOUNT_A, None), _TENANT_B)
    # 헤더가 JWT claim (None) 과 다르므로 mismatch 401.
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in exc_info.value.detail
