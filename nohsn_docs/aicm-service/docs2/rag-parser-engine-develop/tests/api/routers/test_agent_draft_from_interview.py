"""POST /api/v1/agents/draft-from-interview — unit tests (mock-based, no DB / LLM required).

Phase 1.5C Task 18 회귀 가드.

Covers:
  - 정상 흐름: category=restaurant_cafe + answers → markdown + persona 반환
  - 잘못된 category → 400
  - 비어있는 answers → sample SOP 그대로 반환 (LLM 호출 X)
  - LLM 이 카탈로그 외 tool 반환 → suggested_tools 필터링
  - LLM 이 빈 sop_markdown 반환 → 502
  - admin/owner 만 접근 — member → 403
  - body category 누락 → 422 validation
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token
from src.api.schemas.agent import InterviewDraftResponse


TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())


_VALID_LLM_PAYLOAD = {
    "sop_markdown": (
        "# 식당/카페 SOP\n\n"
        "## 페르소나\n따뜻하고 친근한 매장 직원.\n\n"
        "## 응대 시나리오\n### S1. 영업시간 안내\n- 트리거: ...\n\n"
        "## 도구 사용 가이드\n| 도구 | 호출 시점 |\n\n"
        "## 에스컬레이션\n- 알레르기 사고 → 매니저\n\n"
        "## 응답 톤\n- 친절·따뜻\n\n"
        "## 금지 사항\n- 알레르기 정보 미확인 추천 X\n\n"
        "## 실패 응답 패턴\n- 모를 땐 매니저 연결\n"
    ),
    "persona": "따뜻하고 친근한 매장 직원. 알레르기 우선 확인.",
    "suggested_tools": ["kms_rag.search", "schedule.create", "mail.send"],
    "notes": "운영 시간 / 알레르기 정책은 매장 실제 자료로 보완 권장",
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
# Test 1 — 정상 흐름: category=restaurant_cafe + answers → markdown + persona
# ---------------------------------------------------------------------------


def test_draft_from_interview_basic(client):
    """정상 흐름 — answers 가 있으면 LLM 호출 + markdown / persona / suggested_tools 반환."""
    llm_resp = json.dumps(_VALID_LLM_PAYLOAD, ensure_ascii=False)

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=AsyncMock(return_value=llm_resp),
    ):
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={
                "category": "restaurant_cafe",
                "answers": {
                    "rc_cuisine_type": "한식·국밥 전문",
                    "common_business_hours": "평일 11-22시 / 주말 휴무",
                    "rc_allergy_handling": "주문 전 알레르기 사전 확인 필수",
                },
            },
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "## 페르소나" in data["sop_markdown"]
    assert "## 응대 시나리오" in data["sop_markdown"]
    assert "## 실패 응답 패턴" in data["sop_markdown"]
    assert data["persona"].strip() != ""
    assert "kms_rag.search" in data["suggested_tools"]
    # schema validate
    InterviewDraftResponse(**data)


# ---------------------------------------------------------------------------
# Test 2 — 잘못된 category → 400
# ---------------------------------------------------------------------------


def test_draft_invalid_category_rejected(client):
    """category 가 19 화이트리스트에 없으면 400."""
    p_account, p_member = _auth_patches("admin")
    with p_account, p_member:
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={"category": "non_existent_category_xyz", "answers": {}},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 400, resp.text
    assert "invalid category" in resp.text or "non_existent_category_xyz" in resp.text


# ---------------------------------------------------------------------------
# Test 3 — 비어있는 answers → sample SOP 그대로 반환 (LLM 호출 X)
# ---------------------------------------------------------------------------


def test_draft_empty_answers_returns_sample(client):
    """answers 가 비어있으면 sample SOP 그대로 반환 (LLM mock 호출되지 않음)."""
    llm_mock = AsyncMock(return_value=json.dumps(_VALID_LLM_PAYLOAD, ensure_ascii=False))

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=llm_mock,
    ):
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={"category": "restaurant_cafe", "answers": {}},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    # LLM 호출되지 않았어야 함
    llm_mock.assert_not_awaited()
    data = resp.json()
    # sample SOP 반환 → 7 섹션 헤더 보유
    assert "## 페르소나" in data["sop_markdown"]
    assert "## 실패 응답 패턴" in data["sop_markdown"]
    # notes 에 안내 문구 포함
    assert "인터뷰" in (data.get("notes") or "")


# ---------------------------------------------------------------------------
# Test 4 — LLM 이 카탈로그 외 tool 반환 → 필터링
# ---------------------------------------------------------------------------


def test_draft_invented_tool_filtered(client):
    """suggested_tools 의 카탈로그 외 tool 은 제거된다."""
    payload = dict(_VALID_LLM_PAYLOAD)
    payload["suggested_tools"] = [
        "kms_rag.search",
        "fictional.tool.no_exist",  # 카탈로그 외
        "schedule.create",
    ]
    llm_resp = json.dumps(payload, ensure_ascii=False)

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=AsyncMock(return_value=llm_resp),
    ):
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={
                "category": "restaurant_cafe",
                "answers": {"rc_cuisine_type": "한식"},
            },
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    tools = resp.json()["suggested_tools"]
    assert "fictional.tool.no_exist" not in tools
    assert "kms_rag.search" in tools


# ---------------------------------------------------------------------------
# Test 5 — LLM 이 빈 sop_markdown 반환 → 502
# ---------------------------------------------------------------------------


def test_draft_empty_markdown_rejected(client):
    """LLM 응답의 sop_markdown 이 빈 문자열이면 502."""
    bad_payload = dict(_VALID_LLM_PAYLOAD)
    bad_payload["sop_markdown"] = ""
    llm_resp = json.dumps(bad_payload, ensure_ascii=False)

    p_account, p_member = _auth_patches("admin")
    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=AsyncMock(return_value=llm_resp),
    ):
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={
                "category": "restaurant_cafe",
                "answers": {"rc_cuisine_type": "한식"},
            },
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 502
    assert "sop_markdown" in resp.text


# ---------------------------------------------------------------------------
# Test 6 — member 권한 → 403
# ---------------------------------------------------------------------------


def test_draft_member_forbidden(client):
    """member 권한으로는 /draft-from-interview 호출 불가."""
    p_account, p_member = _auth_patches("member")
    with p_account, p_member:
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={"category": "restaurant_cafe", "answers": {}},
            headers={
                "Authorization": f"Bearer {_member_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 7 — body category 누락 → 422 validation
# ---------------------------------------------------------------------------


def test_draft_missing_category_422(client):
    """category 필드가 누락되면 Pydantic validation → 422."""
    p_account, p_member = _auth_patches("admin")
    with p_account, p_member:
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={"answers": {"foo": "bar"}},
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 8 — LLM 호출 실패 → 502
# ---------------------------------------------------------------------------


def test_draft_llm_error_502(client):
    """LLM adapter 가 예외를 던지면 502."""
    p_account, p_member = _auth_patches("admin")

    async def _boom(*args, **kwargs):
        raise RuntimeError("vLLM upstream timeout")

    with p_account, p_member, patch(
        "src.api.routers.agents_v1.VLLMAdapter.complete",
        new=_boom,
    ):
        resp = client.post(
            "/api/v1/agents/draft-from-interview",
            json={
                "category": "restaurant_cafe",
                "answers": {"rc_cuisine_type": "한식"},
            },
            headers={
                "Authorization": f"Bearer {_admin_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 502
    assert "LLM" in resp.text or "호출" in resp.text
