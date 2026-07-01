"""Phase 8 — /api/v1/admin/audit/* 라우터 smoke test.

read-only 한 두 endpoint (tool_invocations / freshness_runs) 가 200 응답 +
items 리스트 구조를 반환하는지만 확인. 데이터 row 가 없어도 빈 list 로 OK.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.api.main import app


def _sync_url() -> str:
    return (
        os.environ["DATABASE_URL"]
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_tool_invocations_endpoint_returns_items(client):
    r = client.get("/api/v1/admin/audit/tool_invocations?limit=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)


def test_freshness_runs_endpoint_returns_items(client):
    r = client.get("/api/v1/admin/audit/freshness_runs?limit=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)


def test_combined_endpoint_returns_both(client):
    r = client.get("/api/v1/admin/audit/combined")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "tool_invocations" in body["data"]
    assert "freshness_runs" in body["data"]


def test_status_filter_applied(client):
    """status filter 가 SQL 단에서 적용되는지 — sample row 로 검증."""
    eng = create_engine(_sync_url())
    inv_id = f"inv_test_{uuid.uuid4().hex[:8]}"
    with eng.begin() as c:
        c.execute(
            text(
                """
                INSERT INTO tool_invocations
                  (id, tenant_id, skill_id, tool_name, status, dry_run)
                VALUES (:id, 't1', 'sk_test_audit', 'test.tool',
                        'succeeded', FALSE)
                """
            ),
            {"id": inv_id},
        )
    try:
        r = client.get(
            "/api/v1/admin/audit/tool_invocations"
            "?limit=100&status=succeeded&skill_id=sk_test_audit"
        )
        assert r.status_code == 200, r.text
        ids = [it["id"] for it in r.json()["data"]["items"]]
        assert inv_id in ids
    finally:
        with eng.begin() as c:
            c.execute(text("DELETE FROM tool_invocations WHERE id=:id"), {"id": inv_id})
