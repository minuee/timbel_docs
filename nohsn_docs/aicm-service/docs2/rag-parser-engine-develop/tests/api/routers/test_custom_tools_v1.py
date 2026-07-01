"""custom_tools_v1 CRUD + test endpoint — 단위 테스트 (mock-based).

DB 없이 실행 가능. _account_from_token / _get_engine 을 unittest.mock 으로 대체.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())
TOOL_ID = str(uuid.uuid4())

NOW_ISO = datetime.now(tz=timezone.utc).isoformat()

_BASE_ROW = {
    "id": TOOL_ID,
    "tenant_id": TENANT_ID,
    "name": "custom.weather_api",
    "description": "외부 날씨 서비스 webhook",
    "category": "custom",
    "endpoint_url": "https://api.example.com/weather",
    "method": "POST",
    "input_schema": {},
    "output_schema": {},
    "is_active": True,
    "created_at": NOW_ISO,
    "updated_at": NOW_ISO,
}


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


def _member_token() -> str:
    return create_access_token(subject=MEMBER_ID, tenant_id=TENANT_ID, role="member")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _patch_token(role: str = "admin"):
    account_id = uuid.UUID(ADMIN_ID) if role in ("owner", "admin") else uuid.UUID(MEMBER_ID)
    tenant_id = TENANT_ID
    return patch(
        "src.api.routers.custom_tools_v1._account_from_token",
        return_value=(account_id, tenant_id, role),
    )


def _patch_engine(rows=None, rowcount: int = 1):
    """_get_engine() 를 mock — execute 결과 반환."""
    engine_mock = MagicMock()
    conn_mock = AsyncMock()

    # context manager 체인 — engine.begin() / engine.connect()
    engine_mock.begin.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    engine_mock.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine_mock.connect.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    engine_mock.connect.return_value.__aexit__ = AsyncMock(return_value=False)

    result_mock = MagicMock()
    if rows is not None:
        # mappings().all() 또는 mappings().first()
        mappings_mock = MagicMock()
        mappings_mock.all.return_value = rows
        mappings_mock.first.return_value = rows[0] if rows else None
        result_mock.mappings.return_value = mappings_mock
    result_mock.rowcount = rowcount
    conn_mock.execute = AsyncMock(return_value=result_mock)

    return patch("src.api.routers.custom_tools_v1._get_engine", return_value=engine_mock)


# ---------------------------------------------------------------------------
# 1. POST /api/v1/custom-tools — 등록
# ---------------------------------------------------------------------------


def test_create_tool_success(client):
    """admin 이 tool 등록 → 201 + body."""
    returned_row = dict(_BASE_ROW)

    with _patch_token("admin"), _patch_engine(rows=[returned_row]):
        with patch("src.api.routers.custom_tools_v1.encrypt_dict", return_value=b"encrypted"):
            resp = client.post(
                "/api/v1/custom-tools",
                json={
                    "name": "custom.weather_api",
                    "description": "외부 날씨 서비스 webhook",
                    "endpoint_url": "https://api.example.com/weather",
                },
                headers={"Authorization": f"Bearer {_admin_token()}"},
            )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "custom.weather_api"
    assert "auth_headers" not in body  # 보안: 노출 X


def test_create_tool_member_forbidden(client):
    """member 는 등록 불가 — 403."""
    with _patch_token("member"):
        resp = client.post(
            "/api/v1/custom-tools",
            json={
                "name": "custom.test",
                "description": "some description here",
                "endpoint_url": "https://example.com/hook",
            },
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 403


def test_create_tool_missing_bearer(client):
    """Authorization 헤더 없으면 401."""
    resp = client.post(
        "/api/v1/custom-tools",
        json={"name": "x", "description": "y", "endpoint_url": "https://a.b/c"},
    )
    # FastAPI 422 (missing required header) or 401
    assert resp.status_code in (401, 422)


# ---------------------------------------------------------------------------
# 2. GET /api/v1/custom-tools — 목록
# ---------------------------------------------------------------------------


def test_list_tools_returns_array(client):
    """member 도 목록 조회 가능."""
    with _patch_token("member"), _patch_engine(rows=[_BASE_ROW]):
        resp = client.get(
            "/api/v1/custom-tools",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "custom.weather_api"


def test_list_tools_empty(client):
    """tool 없으면 빈 배열."""
    with _patch_token("member"), _patch_engine(rows=[]):
        resp = client.get(
            "/api/v1/custom-tools",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# 3. GET /api/v1/custom-tools/{id} — 단건
# ---------------------------------------------------------------------------


def test_get_tool_by_id(client):
    with _patch_token("member"), _patch_engine(rows=[_BASE_ROW]):
        resp = client.get(
            f"/api/v1/custom-tools/{TOOL_ID}",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 200
    assert resp.json()["id"] == TOOL_ID


def test_get_tool_not_found(client):
    """없으면 404."""
    with _patch_token("member"), _patch_engine(rows=[]):
        resp = client.get(
            f"/api/v1/custom-tools/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. PATCH /api/v1/custom-tools/{id} — 수정
# ---------------------------------------------------------------------------


def test_patch_tool_description(client):
    """admin 이 description 수정 → 200 + 업데이트된 row."""
    updated_row = dict(_BASE_ROW, description="새 설명입니다")

    with _patch_token("admin"), _patch_engine(rows=[_BASE_ROW, updated_row]):
        resp = client.patch(
            f"/api/v1/custom-tools/{TOOL_ID}",
            json={"description": "새 설명입니다"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert resp.status_code == 200


def test_patch_tool_no_fields(client):
    """업데이트 필드 없으면 400 — 엔진 mock 필수 (fetch_tool_row 전에 patch 체크)."""
    # patch 체크는 _fetch_tool_row 보다 앞이므로 engine 호출 발생 전 400 반환.
    # 그러나 현재 구현은 먼저 _fetch_tool_row 호출 후 400 체크 순서.
    # engine mock 주입해 404 대신 200 row 반환 후 400 체크 통과시킴.
    with _patch_token("admin"), _patch_engine(rows=[_BASE_ROW]):
        resp = client.patch(
            f"/api/v1/custom-tools/{TOOL_ID}",
            json={},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert resp.status_code == 400


def test_patch_tool_member_forbidden(client):
    """member 는 수정 불가 — 403."""
    with _patch_token("member"):
        resp = client.patch(
            f"/api/v1/custom-tools/{TOOL_ID}",
            json={"description": "변경 시도"},
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5. DELETE /api/v1/custom-tools/{id} — soft delete
# ---------------------------------------------------------------------------


def test_delete_tool_success(client):
    """admin soft delete → 204."""
    with _patch_token("admin"), _patch_engine(rows=None, rowcount=1):
        resp = client.delete(
            f"/api/v1/custom-tools/{TOOL_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert resp.status_code == 204


def test_delete_tool_not_found(client):
    """이미 비활성이거나 없으면 404."""
    with _patch_token("admin"), _patch_engine(rows=None, rowcount=0):
        resp = client.delete(
            f"/api/v1/custom-tools/{TOOL_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 6. POST /api/v1/custom-tools/{id}/test — 테스트 호출
# ---------------------------------------------------------------------------


def test_test_endpoint_success(client):
    """테스트 호출 성공 → ok=True."""
    active_row = dict(_BASE_ROW, is_active=True)

    mock_result = {"ok": True, "tool": "custom.weather_api", "status_code": 200, "data": {}}

    with _patch_token("admin"), _patch_engine(rows=[active_row]):
        with patch(
            "src.agent_framework.tools.webhook_caller.call_custom_tool",
            new=AsyncMock(return_value=mock_result),
        ):
            with patch("sqlalchemy.ext.asyncio.AsyncSession.__aenter__", new=AsyncMock(return_value=MagicMock())):
                with patch("sqlalchemy.ext.asyncio.AsyncSession.__aexit__", new=AsyncMock(return_value=False)):
                    resp = client.post(
                        f"/api/v1/custom-tools/{TOOL_ID}/test",
                        json={"input_data": {"city": "Seoul"}},
                        headers={"Authorization": f"Bearer {_admin_token()}"},
                    )

    assert resp.status_code == 200


def test_test_endpoint_inactive_tool(client):
    """비활성 tool 테스트 → 400."""
    inactive_row = dict(_BASE_ROW, is_active=False)

    with _patch_token("admin"), _patch_engine(rows=[inactive_row]):
        resp = client.post(
            f"/api/v1/custom-tools/{TOOL_ID}/test",
            json={"input_data": {}},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )

    assert resp.status_code == 400


def test_test_endpoint_member_forbidden(client):
    """member 는 테스트 불가 — 403."""
    with _patch_token("member"):
        resp = client.post(
            f"/api/v1/custom-tools/{TOOL_ID}/test",
            json={"input_data": {}},
            headers={"Authorization": f"Bearer {_member_token()}"},
        )

    assert resp.status_code == 403
