"""Phase 1.5A Task 8c.2 — shared JWT tenant scope helper.

GPT-5.5 deep dive 후속 sweep: ``_tenant_scope.resolve_tenant_id`` 가
JWT claim 만 신뢰함을 검증. 헤더 mismatch → 401.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api.routers._tenant_scope import resolve_tenant_id


_TENANT_A = str(uuid4())
_TENANT_B = str(uuid4())


def test_no_header_returns_jwt_claim():
    """헤더 없음 → JWT claim 그대로."""
    payload = {"sub": "x", "tenant_id": _TENANT_A}
    assert resolve_tenant_id(payload, None) == _TENANT_A


def test_empty_string_header_treated_as_absent():
    """빈 문자열 헤더는 미지정 처리 (FastAPI Header(None) 호환)."""
    payload = {"sub": "x", "tenant_id": _TENANT_A}
    assert resolve_tenant_id(payload, "") == _TENANT_A


def test_header_matches_jwt_claim_ok():
    """헤더 == JWT claim → 통과 (frontend round-trip 호환)."""
    payload = {"sub": "x", "tenant_id": _TENANT_A}
    assert resolve_tenant_id(payload, _TENANT_A) == _TENANT_A


def test_header_mismatches_jwt_claim_401():
    """헤더 != JWT claim → 401 'tenant claim mismatch'.

    핵심 보안 가드 — cross-tenant 위장 차단.
    """
    payload = {"sub": "x", "tenant_id": _TENANT_A}
    with pytest.raises(HTTPException) as exc_info:
        resolve_tenant_id(payload, _TENANT_B)
    assert exc_info.value.status_code == 401
    assert "tenant claim mismatch" in str(exc_info.value.detail)


def test_missing_jwt_claim_401():
    """JWT 에 tenant_id 없음 → 401 'missing tenant claim in JWT'."""
    payload = {"sub": "x"}  # no tenant_id
    with pytest.raises(HTTPException) as exc_info:
        resolve_tenant_id(payload, None)
    assert exc_info.value.status_code == 401
    assert "missing tenant claim" in str(exc_info.value.detail)
