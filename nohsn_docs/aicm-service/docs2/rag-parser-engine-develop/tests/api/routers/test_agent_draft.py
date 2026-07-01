"""POST /api/v1/agents/draft — unit tests (mock-based, no DB / LLM required).

Covers:
  - 기본 자연어 설명 → AgentDraftResponse 반환
  - category_id 명시 → 템플릿 yaml prefill 적용
  - LLM 이 카탈로그 외 tool 반환 → 필터링 (화이트리스트 외 제거)
  - LLM 이 invalid knowledge_isolation 반환 → 502 에러
  - admin/owner 만 접근 가능 (member → 403)
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token
from src.api.schemas.agent import AgentDraftResponse

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())

_VALID_LLM_PAYLOAD = {
    "goal": "병원 전화 상담 봇 — 진료 예약 및 시술 문의를 처리한다.",
    "guidelines_md": (
        "## rules\n- 존댓말 사용\n\n"
        "## slot_completeness_rules\n- 예약 시 환자명/일자/시술명 확인\n\n"
        "## escalation_rules\n- 진단은 의료진 연결"
    ),
    "knowledge_isolation": "strict",
    "allowed_tools": ["kms_rag.search", "schedule.create", "sms.send"],
    "done_when": "schedule.create 완료 또는 사용자 종료",
    "notes": "의료 컴플라이언스 주의",
}


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


def _member_token() -> str:
    return create_access_token(subject=MEMBER_ID, tenant_id=TENANT_ID, role="member")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _auth_patches(role: str = "admin"):
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


# ---------------------------------------------------------------------------
# Test 1 — 단순 자연어 설명 → LLM mock → AgentDraftResponse 반환
# ---------------------------------------------------------------------------


def test_draft_basic_description(client):
    """단순 자연어 설명 → LLM mock → 정상 AgentDraftResponse."""
    llm_resp = json.dumps(_VALID_LLM_PAYLOAD, ensure_ascii=False)

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=AsyncMock(return_value=llm_resp),
    ):
        resp = client.post(
            "/api/v1/agents/draft",
            json={"description": "병원 전화 상담 봇"},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["goal"] == _VALID_LLM_PAYLOAD["goal"]
    assert data["knowledge_isolation"] == "strict"
    assert "kms_rag.search" in data["allowed_tools"]
    assert "schedule.create" in data["allowed_tools"]
    # schema validate
    AgentDraftResponse(**data)


# ---------------------------------------------------------------------------
# Test 2 — category_id 명시 → 템플릿 yaml prefill 적용 (prompt 에 포함 여부)
# ---------------------------------------------------------------------------


def test_draft_with_category_prefill(client):
    """category_id 명시 시 템플릿 yaml prefill 이 user prompt 에 포함된다."""
    llm_resp = json.dumps(_VALID_LLM_PAYLOAD, ensure_ascii=False)

    captured_prompts: list[tuple[str, str]] = []

    async def _mock_complete(self, system, user, *, response_format=None, model=None):
        captured_prompts.append((system, user))
        return llm_resp

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=_mock_complete,
    ):
        resp = client.post(
            "/api/v1/agents/draft",
            json={"description": "병원 전화 상담 봇", "category_id": "health_medical"},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    # user prompt 에 템플릿 카테고리 힌트가 포함됐는지 확인
    assert captured_prompts, "LLM complete 가 호출되지 않았습니다"
    _, user_prompt = captured_prompts[0]
    assert "health_medical" in user_prompt or "병원" in user_prompt


# ---------------------------------------------------------------------------
# Test 3 — LLM 이 카탈로그 외 tool 반환 → 필터링
# ---------------------------------------------------------------------------


def test_draft_invented_tool_filtered(client):
    """LLM 이 카탈로그 외 tool 을 반환하면 결과에서 제거된다."""
    payload_with_fake = dict(_VALID_LLM_PAYLOAD)
    payload_with_fake["allowed_tools"] = [
        "kms_rag.search",
        "invented.tool.xyz",   # 카탈로그 외 — 제거되어야 함
        "schedule.create",
    ]
    llm_resp = json.dumps(payload_with_fake, ensure_ascii=False)

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=AsyncMock(return_value=llm_resp),
    ):
        resp = client.post(
            "/api/v1/agents/draft",
            json={"description": "병원 전화 상담 봇"},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    tools = resp.json()["allowed_tools"]
    assert "invented.tool.xyz" not in tools
    assert "kms_rag.search" in tools
    assert "schedule.create" in tools


# ---------------------------------------------------------------------------
# Test 4 — LLM 이 invalid knowledge_isolation 반환 → 502
# ---------------------------------------------------------------------------


def test_draft_invalid_isolation_rejected(client):
    """LLM 이 유효하지 않은 knowledge_isolation 을 반환하면 502 에러."""
    bad_payload = dict(_VALID_LLM_PAYLOAD)
    bad_payload["knowledge_isolation"] = "ultra_strict_secret"  # 유효하지 않은 값
    llm_resp = json.dumps(bad_payload, ensure_ascii=False)

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=AsyncMock(return_value=llm_resp),
    ):
        resp = client.post(
            "/api/v1/agents/draft",
            json={"description": "테스트 봇입니다"},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 502
    assert "knowledge_isolation" in resp.text


# ---------------------------------------------------------------------------
# Test 5 — member 권한 → 403
# ---------------------------------------------------------------------------


def test_draft_member_forbidden(client):
    """member 권한으로는 /draft 에 접근할 수 없다."""
    p_account, p_member = _auth_patches("member")
    with p_account, p_member:
        resp = client.post(
            "/api/v1/agents/draft",
            json={"description": "병원 전화 상담 봇"},
            headers={
                "Authorization": f"Bearer {_member_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 6 — description 너무 짧음 → 422 validation error
# ---------------------------------------------------------------------------


def test_draft_description_too_short(client):
    """description 이 5자 미만이면 422 반환."""
    p_account, p_member = _auth_patches("admin")
    with p_account, p_member:
        resp = client.post(
            "/api/v1/agents/draft",
            json={"description": "봇"},   # 2자 — min_length=5 위반
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 422
