"""``get_current_principal`` JWT 우선 + legacy fallback 테스트 — Phase 9.

- JWT Bearer 헤더 → auth_v2=True + role/tenant_id 추출.
- X-Tenant-Id 만 (헤더 X) → auth_v2=False, role=viewer.
- 잘못된/만료 JWT → fallback 으로 viewer (헤더 우선 X).
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api.auth.jwt_utils import create_access_token, create_refresh_token
from src.api.dependencies import get_current_principal, get_current_user_id


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(principal: dict = Depends(get_current_principal)):
        return principal

    @app.get("/uid")
    async def uid(user_id=Depends(get_current_user_id)):
        return {"user_id": str(user_id) if user_id else None}

    return app


def test_jwt_bearer_takes_priority():
    app = _build_app()
    token = create_access_token(
        subject="acct-1", tenant_id="tnt-1", role="admin"
    )
    client = TestClient(app)
    r = client.get(
        "/who",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "ignore-me"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["auth_v2"] is True
    assert data["user_id"] == "acct-1"
    assert data["tenant_id"] == "tnt-1"
    assert data["role"] == "admin"


def test_no_auth_returns_viewer_with_optional_tenant_header():
    app = _build_app()
    client = TestClient(app)
    r = client.get("/who", headers={"X-Tenant-Id": "tnt-legacy"})
    assert r.status_code == 200
    data = r.json()
    assert data["auth_v2"] is False
    assert data["user_id"] is None
    assert data["tenant_id"] == "tnt-legacy"
    assert data["role"] == "viewer"


def test_invalid_bearer_falls_back_to_legacy():
    app = _build_app()
    client = TestClient(app)
    r = client.get(
        "/who",
        headers={
            "Authorization": "Bearer this.is.not.a.valid.jwt",
            "X-Tenant-Id": "tnt-fallback",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["auth_v2"] is False
    assert data["tenant_id"] == "tnt-fallback"


def test_refresh_token_not_accepted_as_access():
    """type=refresh 토큰은 access 경로에서 거부되어 fallback."""
    app = _build_app()
    refresh = create_refresh_token("acct-r")
    client = TestClient(app)
    r = client.get(
        "/who", headers={"Authorization": f"Bearer {refresh}"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["auth_v2"] is False  # refresh 는 access 가 아님 → fallback.


def test_get_current_user_id_with_uuid_subject():
    """JWT sub 가 UUID 면 UUID 로 변환되어 반환."""
    app = _build_app()
    uuid_str = "11111111-1111-1111-1111-111111111111"
    token = create_access_token(subject=uuid_str, role="member")
    client = TestClient(app)
    r = client.get("/uid", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user_id"] == uuid_str


def test_get_current_user_id_with_non_uuid_subject_falls_back_none():
    """JWT sub 가 UUID 가 아니면 None — 기존 routers 호환."""
    app = _build_app()
    token = create_access_token(subject="not-a-uuid", role="member")
    client = TestClient(app)
    r = client.get("/uid", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user_id"] is None
