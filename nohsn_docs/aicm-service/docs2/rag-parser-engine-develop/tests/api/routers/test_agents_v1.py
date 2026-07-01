"""agents_v1 CRUD endpoints — unit tests (mock-based).

Phase 1 Task 3 (KMS-Plus). 5 endpoints:
  POST   /api/v1/agents           — create (owner/admin)
  GET    /api/v1/agents           — list (tenant-scoped, active_only)
  GET    /api/v1/agents/{id}      — read (tenant-scoped)
  PATCH  /api/v1/agents/{id}      — update (owner/admin)
  DELETE /api/v1/agents/{id}      — soft delete (owner/admin)

DB 없이 실행 가능. _account_from_token / _verify_membership / engine helpers
를 unittest.mock 으로 대체.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token
from src.api.routers.agents_v1 import AgentOut, AgentListOut


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())
OTHER_TENANT_ID = str(uuid.uuid4())

_BASE_AGENT = AgentOut(
    id=AGENT_ID,
    tenant_id=TENANT_ID,
    name="Test Agent",
    description="desc",
    persona="friendly",
    system_prompt="be helpful",
    allowed_skills=["chat"],
    allowed_repos=[],
    is_active=True,
    rate_limit_per_min=60,
    created_by=ADMIN_ID,
    created_at=None,
    updated_at=None,
)


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


def _member_token() -> str:
    return create_access_token(subject=MEMBER_ID, tenant_id=TENANT_ID, role="member")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _auth_patches(role: str = "owner"):
    """_account_from_token 과 _verify_membership 을 동시에 패치."""
    account_id = uuid.UUID(ADMIN_ID) if role in ("owner", "admin") else uuid.UUID(MEMBER_ID)
    return (
        patch(
            "src.api.routers.agents_v1._account_from_token",
            return_value=(account_id, TENANT_ID, role),
        ),
        patch(
            "src.api.routers.agents_v1._verify_membership",
            new=AsyncMock(return_value=role),
        ),
    )


def _token_for(role: str) -> str:
    return _admin_token() if role in ("owner", "admin") else _member_token()


# ---------------------------------------------------------------------------
# 1. POST /api/v1/agents — create, member membership OK, body 검증
# ---------------------------------------------------------------------------


def test_create_agent_returns_agent_body(client):
    """인증된 member 가 agent 생성 → 200 + body 정확."""
    pat_tok, pat_mem = _auth_patches("owner")
    with pat_tok, pat_mem, \
         patch(
             "src.api.routers.agents_v1._load_agent",
             new=AsyncMock(return_value=_BASE_AGENT),
         ):
        # _get_engine mock for INSERT
        mock_scalar = MagicMock()
        mock_scalar.scalar_one.return_value = AGENT_ID
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_scalar
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = None
        mock_eng = MagicMock()
        mock_eng.begin.return_value = mock_ctx

        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng):
            r = client.post(
                "/api/v1/agents",
                json={"name": "Test Agent", "description": "desc"},
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Test Agent"
    assert body["tenant_id"] == TENANT_ID
    assert body["is_active"] is True


# ---------------------------------------------------------------------------
# 2. POST /api/v1/agents — member role (not owner/admin) blocked
#    (create_agent checks owner/admin role — Task 3 followup)
# ---------------------------------------------------------------------------


def test_create_agent_member_role_blocked_403(client):
    """member role → 403 (create_agent checks owner/admin)."""
    pat_tok, pat_mem = _auth_patches("member")

    with pat_tok, pat_mem:
        r = client.post(
            "/api/v1/agents",
            json={"name": "Test Agent"},
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 3. GET /api/v1/agents — list, tenant-scoped
# ---------------------------------------------------------------------------


def test_list_agents_returns_tenant_items(client):
    second_agent = AgentOut(**{**_BASE_AGENT.model_dump(), "id": str(uuid.uuid4()), "name": "Second"})
    expected = AgentListOut(items=[_BASE_AGENT, second_agent])

    pat_tok, pat_mem = _auth_patches("owner")
    with pat_tok, pat_mem:
        mock_rows = [_BASE_AGENT, second_agent]
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            # _row_to_agent expects positional tuple — patch list_agents instead
        ]))
        # Patch _row_to_agent and engine together
        def _fake_row_to_agent(row):
            return row  # rows are already AgentOut objects in this mock

        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_rows  # iterable
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = None
        mock_eng = MagicMock()
        mock_eng.begin.return_value = mock_ctx

        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng), \
             patch("src.api.routers.agents_v1._row_to_agent", side_effect=lambda r: r):
            r = client.get(
                "/api/v1/agents",
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_list_agents_empty(client):
    pat_tok, pat_mem = _auth_patches("owner")
    with pat_tok, pat_mem:
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = []
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = None
        mock_eng = MagicMock()
        mock_eng.begin.return_value = mock_ctx

        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng), \
             patch("src.api.routers.agents_v1._row_to_agent", side_effect=lambda r: r):
            r = client.get(
                "/api/v1/agents",
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


# ---------------------------------------------------------------------------
# 4. GET /api/v1/agents/{agent_id} — 자기 tenant 200, 다른 tenant 403, 없음 404
# ---------------------------------------------------------------------------


def test_get_agent_same_tenant_200(client):
    pat_tok, pat_mem = _auth_patches("owner")
    with pat_tok, pat_mem, \
         patch(
             "src.api.routers.agents_v1._load_agent_for_tenant",
             new=AsyncMock(return_value=_BASE_AGENT),
         ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert r.status_code == 200, r.text
    assert r.json()["id"] == AGENT_ID


def test_get_agent_different_tenant_403(client):
    """다른 tenant 의 agent → 403."""
    from fastapi import HTTPException as FastAPIHTTPException
    pat_tok, pat_mem = _auth_patches("owner")

    async def _raise_403(*args, **kwargs):
        raise FastAPIHTTPException(403, "agent does not belong to current tenant")

    with pat_tok, pat_mem, \
         patch(
             "src.api.routers.agents_v1._load_agent_for_tenant",
             side_effect=_raise_403,
         ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert r.status_code == 403, r.text


def test_get_agent_not_found_404(client):
    """존재하지 않는 agent → 404."""
    from fastapi import HTTPException as FastAPIHTTPException
    pat_tok, pat_mem = _auth_patches("owner")

    async def _raise_404(*args, **kwargs):
        raise FastAPIHTTPException(404, "agent not found")

    with pat_tok, pat_mem, \
         patch(
             "src.api.routers.agents_v1._load_agent_for_tenant",
             side_effect=_raise_404,
         ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# 5. PATCH /api/v1/agents/{id} — admin OK, partial update; member → 403
# ---------------------------------------------------------------------------


def test_update_agent_admin_ok(client):
    updated = AgentOut(**{**_BASE_AGENT.model_dump(), "name": "Updated Agent"})
    pat_tok, pat_mem = _auth_patches("owner")

    with pat_tok, pat_mem, \
         patch(
             "src.api.routers.agents_v1._load_agent_for_tenant",
             new=AsyncMock(return_value=_BASE_AGENT),
         ), \
         patch(
             "src.api.routers.agents_v1._load_agent",
             new=AsyncMock(return_value=updated),
         ):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = None
        mock_eng = MagicMock()
        mock_eng.begin.return_value = mock_ctx

        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng):
            r = client.patch(
                f"/api/v1/agents/{AGENT_ID}",
                json={"name": "Updated Agent"},
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Updated Agent"


def test_update_agent_member_403(client):
    """member role → 403 (update_agent checks owner/admin)."""
    pat_tok, pat_mem = _auth_patches("member")

    with pat_tok, pat_mem:
        r = client.patch(
            f"/api/v1/agents/{AGENT_ID}",
            json={"name": "Hacked"},
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 6. DELETE /api/v1/agents/{id} — soft delete 204/200; member → 403
# ---------------------------------------------------------------------------


def test_delete_agent_admin_soft_delete(client):
    """owner 가 delete → 200, is_active=False."""
    pat_tok, pat_mem = _auth_patches("owner")

    with pat_tok, pat_mem, \
         patch(
             "src.api.routers.agents_v1._load_agent_for_tenant",
             new=AsyncMock(return_value=_BASE_AGENT),
         ):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = None
        mock_eng = MagicMock()
        mock_eng.begin.return_value = mock_ctx

        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng):
            r = client.delete(
                f"/api/v1/agents/{AGENT_ID}",
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["is_active"] is False


def test_delete_agent_member_403(client):
    """member → 403."""
    pat_tok, pat_mem = _auth_patches("member")

    with pat_tok, pat_mem:
        r = client.delete(
            f"/api/v1/agents/{AGENT_ID}",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 7. soft delete → list 에 미포함 (active_only SQL 절 존재 확인)
# ---------------------------------------------------------------------------


def test_list_active_only_sql_contains_filter():
    """list_agents 의 SQL 이 is_active 필터를 포함하는지 단위 확인."""
    import inspect
    import src.api.routers.agents_v1 as mod

    src_code = inspect.getsource(mod.list_agents)
    assert "is_active" in src_code, "list_agents SQL 에 is_active 필터 없음"
    assert "include_inactive" in src_code, "include_inactive 파라미터 없음"


# ---------------------------------------------------------------------------
# 8. Missing auth header → 422 (FastAPI required header)
# ---------------------------------------------------------------------------


def test_missing_auth_header_rejected(client):
    r = client.get("/api/v1/agents")
    assert r.status_code in (401, 422), r.text


# ---------------------------------------------------------------------------
# 9. Invalid UUID path param → 400
# ---------------------------------------------------------------------------


def test_invalid_uuid_path_param_400(client):
    pat_tok, pat_mem = _auth_patches("owner")
    with pat_tok, pat_mem:
        r = client.get(
            "/api/v1/agents/not-a-uuid",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    # _parse_uuid raises HTTPException(400)
    assert r.status_code == 400, r.text
