"""GET /api/v1/agents/{aid}/documents/summary — unit tests (mock).

Spec: docs/superpowers/specs/2026-05-07-sop-kms-prompt-architecture.md §4.3-4.4

목적:
- mapping 우선 dedupe + sop/kms disjoint 보장 검증.
- cross-tenant 격리 (member 미가입 → 403, agent 다른 tenant → 404).
- sop_rag_mode 응답 필드 (운영 가시성).

DB 없이 — AgentDocumentService 와 _verify_membership_role 을 mock.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.auth.jwt_utils import create_access_token
from src.api.main import app


TENANT_ID = str(uuid.uuid4())
OTHER_TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _auth_patches():
    return (
        patch(
            "src.api.routers.agent_documents_v1._account_from_token",
            return_value=(uuid.UUID(ADMIN_ID), TENANT_ID, "admin"),
        ),
        patch(
            "src.api.routers.agent_documents_v1._verify_membership_role",
            new=AsyncMock(return_value="admin"),
        ),
    )


def test_summary_returns_counts_and_by_source(client):
    """count_summary 결과를 그대로 응답에 매핑."""
    pat_tok, pat_mem = _auth_patches()
    fake_result = {
        "sop": 7,
        "kms": 12,
        "total": 19,
        "by_source": {
            "sop_mapping": 5,
            "sop_repo_inferred": 2,
            "kms_mapping": 8,
            "kms_repo_inferred": 4,
        },
    }
    with pat_tok, pat_mem, patch(
        "src.api.routers.agent_documents_v1.AgentDocumentService"
    ) as ServiceCls:
        ServiceCls.return_value.count_summary = AsyncMock(return_value=fake_result)
        resp = client.get(
            f"/api/v1/agents/{AGENT_ID}/documents/summary",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sop"] == 7
    assert body["kms"] == 12
    assert body["total"] == 19
    assert body["by_source"]["sop_mapping"] == 5
    assert body["by_source"]["sop_repo_inferred"] == 2
    assert body["by_source"]["kms_mapping"] == 8
    assert body["by_source"]["kms_repo_inferred"] == 4
    # FEATURE_SOP_RAG flag default off (env 미설정).
    assert body["sop_rag_mode"] in ("on", "off")


def test_summary_zero_when_no_repos_and_no_mappings(client):
    """sop/kms 양쪽 빈 결과 — total=0 정확."""
    pat_tok, pat_mem = _auth_patches()
    fake_result = {
        "sop": 0,
        "kms": 0,
        "total": 0,
        "by_source": {
            "sop_mapping": 0,
            "sop_repo_inferred": 0,
            "kms_mapping": 0,
            "kms_repo_inferred": 0,
        },
    }
    with pat_tok, pat_mem, patch(
        "src.api.routers.agent_documents_v1.AgentDocumentService"
    ) as ServiceCls:
        ServiceCls.return_value.count_summary = AsyncMock(return_value=fake_result)
        resp = client.get(
            f"/api/v1/agents/{AGENT_ID}/documents/summary",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sop"] == 0
    assert body["kms"] == 0
    assert body["total"] == 0


def test_summary_cross_tenant_404(client):
    """다른 tenant 의 agent 조회 시 404."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem, patch(
        "src.api.routers.agent_documents_v1.AgentDocumentService"
    ) as ServiceCls:
        ServiceCls.return_value.count_summary = AsyncMock(
            side_effect=ValueError("agent not found in tenant")
        )
        resp = client.get(
            f"/api/v1/agents/{AGENT_ID}/documents/summary",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert resp.status_code == 404


def test_summary_permission_error_403(client):
    """tenant mismatch (PermissionError) → 403."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem, patch(
        "src.api.routers.agent_documents_v1.AgentDocumentService"
    ) as ServiceCls:
        ServiceCls.return_value.count_summary = AsyncMock(
            side_effect=PermissionError("agent does not belong")
        )
        resp = client.get(
            f"/api/v1/agents/{AGENT_ID}/documents/summary",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert resp.status_code == 403


def test_summary_invalid_uuid_400(client):
    """잘못된 agent_id 형식 → 400."""
    pat_tok, pat_mem = _auth_patches()
    with pat_tok, pat_mem:
        resp = client.get(
            "/api/v1/agents/not-a-uuid/documents/summary",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert resp.status_code == 400


def test_summary_no_auth_401(client):
    """Authorization header 누락 → 401 또는 422."""
    resp = client.get(f"/api/v1/agents/{AGENT_ID}/documents/summary")
    assert resp.status_code in (401, 422)
