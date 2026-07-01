"""058 — agents POST 의 kind 검증.

- 기본 생성은 kind='role'.
- kind='admin' 명시 + 기존 admin 없을 때 → 200.
- kind='admin' 명시 + 기존 admin 있을 때 → 409.
- kind 불법 값 → 400.
- list/read 응답에 kind 필드 노출.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token
from src.api.routers.agents_v1 import AgentOut


TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _auth_patches():
    return (
        patch(
            "src.api.routers.agents_v1._account_from_token",
            return_value=(uuid.UUID(ADMIN_ID), TENANT_ID, "owner"),
        ),
        patch(
            "src.api.routers.agents_v1._verify_membership",
            new=AsyncMock(return_value="owner"),
        ),
    )


def _agent_out(kind: str = "role") -> AgentOut:
    return AgentOut(
        id=AGENT_ID,
        tenant_id=TENANT_ID,
        name="Test Agent",
        description="desc",
        persona="",
        system_prompt="",
        allowed_skills=[],
        allowed_repos=[],
        is_active=True,
        rate_limit_per_min=60,
        created_by=ADMIN_ID,
        kind=kind,
    )


def _engine_mock_for_insert(*, existing_admin: bool = False) -> MagicMock:
    """create_agent 가 (admin 일 때) 1) existing admin SELECT  2) INSERT 두 번
    eng.begin() 사용. role 일 때는 INSERT 1번."""
    # SELECT result
    select_first_result = MagicMock()
    select_first_result.first.return_value = (
        (uuid.uuid4(),) if existing_admin else None
    )
    # INSERT result
    insert_scalar_result = MagicMock()
    insert_scalar_result.scalar_one.return_value = AGENT_ID

    # conn that returns SELECT first time, INSERT second time
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = [select_first_result, insert_scalar_result]

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None

    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx
    return mock_eng


def _engine_mock_for_role_insert() -> MagicMock:
    """role 생성 — INSERT 한 번만."""
    insert_scalar_result = MagicMock()
    insert_scalar_result.scalar_one.return_value = AGENT_ID

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = insert_scalar_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None

    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx
    return mock_eng


def test_create_agent_default_kind_is_role(client):
    """body 에 kind 미주입 → DB INSERT 시 kind='role'."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._load_agent",
        new=AsyncMock(return_value=_agent_out("role")),
    ):
        mock_eng = _engine_mock_for_role_insert()
        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng):
            r = client.post(
                "/api/v1/agents",
                json={"name": "역할 봇"},
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "role"


def test_create_admin_when_no_existing_admin(client):
    """기존 admin 없으면 kind='admin' 생성 통과."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._load_agent",
        new=AsyncMock(return_value=_agent_out("admin")),
    ):
        mock_eng = _engine_mock_for_insert(existing_admin=False)
        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng):
            r = client.post(
                "/api/v1/agents",
                json={"name": "Locus", "kind": "admin"},
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "admin"


def test_create_admin_when_existing_admin_409(client):
    """이미 admin 존재 → 409 conflict."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem:
        mock_eng = _engine_mock_for_insert(existing_admin=True)
        with patch("src.api.routers.agents_v1._get_engine", return_value=mock_eng):
            r = client.post(
                "/api/v1/agents",
                json={"name": "Another Locus", "kind": "admin"},
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert r.status_code == 409, r.text
    assert "admin agent already exists" in r.json().get("detail", "").lower()


def test_create_invalid_kind_400(client):
    """kind in ('admin','role') 외 값 → 400."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem:
        # eng 호출 도달 전 400
        r = client.post(
            "/api/v1/agents",
            json={"name": "X", "kind": "superadmin"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert r.status_code == 400, r.text
    assert "invalid kind" in r.json().get("detail", "").lower()
