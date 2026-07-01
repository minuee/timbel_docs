"""RBAC ``require_role`` 단위 테스트 — Phase 9 (KMS-Plus).

3 케이스:
1. 충분한 role 통과.
2. 부족한 role 403.
3. unknown role → ValueError (decorator 정의 시점).
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.auth.rbac import RANK, ROLES, require_role
from src.api.dependencies import get_current_principal


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/admin-only")
    @require_role("admin")
    async def admin_only(current_user: dict = Depends(get_current_principal)):
        return {"ok": True, "role": current_user["role"]}

    @app.get("/member-up")
    @require_role("member")
    async def member_up(current_user: dict = Depends(get_current_principal)):
        return {"ok": True}

    return app


def _override(app: FastAPI, role: str):
    async def _principal():
        return {
            "user_id": "test-user",
            "tenant_id": "test-tenant",
            "role": role,
            "auth_v2": True,
        }

    app.dependency_overrides[get_current_principal] = _principal


def test_sufficient_role_passes():
    app = _build_app()
    _override(app, "owner")
    client = TestClient(app)
    r = client.get("/admin-only")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_insufficient_role_403():
    app = _build_app()
    _override(app, "viewer")
    client = TestClient(app)
    r = client.get("/admin-only")
    assert r.status_code == 403
    assert "admin" in r.json()["detail"]


def test_unknown_role_raises_at_decoration_time():
    with pytest.raises(ValueError, match="unknown role"):

        @require_role("super-duper")
        async def _f():
            return {}


def test_rank_ordering_is_monotonic():
    """viewer < member < admin < owner."""
    assert RANK["viewer"] < RANK["member"] < RANK["admin"] < RANK["owner"]
    assert ROLES == ["viewer", "member", "admin", "owner"]


def test_member_passes_member_threshold():
    app = _build_app()
    _override(app, "member")
    client = TestClient(app)
    assert client.get("/member-up").status_code == 200
    # member 는 admin 미만.
    assert client.get("/admin-only").status_code == 403


# ---------------------------------------------------------------------------
# Wave D (KMS-Plus, 2026-04-25) — require_role_dep (Depends 친화 변형) 단위 테스트.
# router-level dependencies=[Depends(require_role_dep("admin"))] 형태로 끼울
# 수 있어야 한다 — admin 미달은 403, 충분하면 통과 + current_user 반환.
# ---------------------------------------------------------------------------


def _build_app_dep() -> FastAPI:
    """require_role_dep 으로 admin 게이트한 라우터를 가진 앱."""
    from fastapi import APIRouter

    from src.api.auth.rbac import require_role_dep

    app = FastAPI()
    router = APIRouter(dependencies=[Depends(require_role_dep("admin"))])

    @router.get("/secret")
    async def secret() -> dict:
        return {"ok": True}

    app.include_router(router)
    return app


def test_require_role_dep_admin_passes():
    app = _build_app_dep()
    _override(app, "admin")
    client = TestClient(app)
    r = client.get("/secret")
    assert r.status_code == 200, r.text


def test_require_role_dep_viewer_blocked():
    app = _build_app_dep()
    _override(app, "viewer")
    client = TestClient(app)
    r = client.get("/secret")
    assert r.status_code == 403
    assert "admin" in r.json()["detail"]


def test_require_role_dep_unknown_role_at_factory():
    from src.api.auth.rbac import require_role_dep

    with pytest.raises(ValueError, match="unknown role"):
        require_role_dep("super-duper")
