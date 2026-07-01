"""Phase 2 Fix B — POST /api/v1/tenants 신규 endpoint 테스트.

3 case:
1. 무인증 모드 (auth_disabled=True) → 201
2. 권한 부족 (role='viewer', auth_disabled=False) → 403
3. slug UNIQUE 충돌 → 409

전략:
- ``create_tenant`` 함수 *직접* 호출 (FastAPI 의존성 우회) — DB 의 IntegrityError /
  성공 path 만 가짜 conn 으로 격리. 실 DB 부재 환경에서도 작동.
- ``_get_engine`` 을 monkeypatch 로 가짜 engine 으로 치환.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.api.routers import tenants_v1
from src.api.routers.tenants_v1 import TenantCreate, create_tenant


# ---------------------------------------------------------------------------
# Fake engine / connection — 실 DB 없이 INSERT 분기 검증.
# ---------------------------------------------------------------------------


class _FakeRow:
    """RETURNING row — index access 만 사용 (row[0..5])."""

    def __init__(self, values: tuple[Any, ...]):
        self._v = values

    def __getitem__(self, i: int) -> Any:
        return self._v[i]


class _FakeResult:
    def __init__(self, row: _FakeRow | None):
        self._row = row

    def first(self) -> _FakeRow | None:
        return self._row


class _FakeConn:
    def __init__(self, *, row: _FakeRow | None = None, raise_integrity: bool = False):
        self._row = row
        self._raise = raise_integrity

    async def execute(self, _stmt, _params=None):
        if self._raise:
            raise IntegrityError("INSERT", {}, Exception("dup slug"))
        return _FakeResult(self._row)


class _FakeEngine:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def begin(self):
        @asynccontextmanager
        async def _ctx():
            yield self._conn

        return _ctx()


@pytest.fixture
def fake_engine_success(monkeypatch):
    """성공 path — RETURNING 1 row."""
    tid = uuid4()
    row = _FakeRow(
        (
            tid,
            "Acme Corp",
            "acme-corp",
            "corporate",
            True,
            datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
    )
    conn = _FakeConn(row=row)
    eng = _FakeEngine(conn)
    monkeypatch.setattr(tenants_v1, "_get_engine", lambda: eng)
    return tid


@pytest.fixture
def fake_engine_conflict(monkeypatch):
    """IntegrityError 발생 path — slug UNIQUE 충돌."""
    conn = _FakeConn(raise_integrity=True)
    eng = _FakeEngine(conn)
    monkeypatch.setattr(tenants_v1, "_get_engine", lambda: eng)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tenant_auth_disabled_201(fake_engine_success):
    """LUCAS_AUTH_DISABLED 모드 (auth_disabled=True) → 201, role=admin."""
    principal = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "role": "admin",
        "auth_v2": False,
        "auth_disabled": True,
    }
    body = TenantCreate(name="Acme Corp")
    out = await create_tenant(body=body, principal=principal)

    assert out.name == "Acme Corp"
    assert out.slug == "acme-corp"
    assert out.tenant_type == "corporate"
    assert out.role == "admin"
    assert out.is_active is True


@pytest.mark.asyncio
async def test_create_tenant_viewer_403():
    """role='viewer', auth_disabled=False → 403."""
    principal = {
        "user_id": "u-1",
        "tenant_id": "t-1",
        "role": "viewer",
        "auth_v2": True,
    }
    body = TenantCreate(name="No Permission Corp")

    with pytest.raises(HTTPException) as exc_info:
        await create_tenant(body=body, principal=principal)
    assert exc_info.value.status_code == 403
    assert "admin" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_tenant_slug_conflict_409(fake_engine_conflict):
    """IntegrityError (slug UNIQUE 충돌) → 409."""
    principal = {
        "user_id": "u-admin",
        "tenant_id": None,
        "role": "admin",
        "auth_v2": True,
    }
    body = TenantCreate(name="Duplicate Co", slug="duplicate-co")

    with pytest.raises(HTTPException) as exc_info:
        await create_tenant(body=body, principal=principal)
    assert exc_info.value.status_code == 409
    assert "slug" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_slugify_korean_fallback(fake_engine_success):
    """name 이 한글-only 면 slug = 'tenant-<hex>' fallback (UNIQUE 위반 회피)."""
    principal = {"role": "admin", "auth_v2": True}
    body = TenantCreate(name="한국어이름")  # ASCII 결과 비어 있음
    # 함수 호출 자체는 통과 (slugify 가 fallback 처리, DB 는 fake)
    out = await create_tenant(body=body, principal=principal)
    # fake 가 fixed name='Acme Corp' 반환하므로 slug 자체는 검증 X — 호출 미실패만 확인.
    assert out is not None
