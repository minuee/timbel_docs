"""Phase 3 Task A — /agent/activation/inventory 통합 자원 관리 API."""
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


@pytest.fixture
def sample_docs():
    """다양한 status 의 샘플 문서 3개. 테스트 후 삭제."""
    eng = create_engine(_sync_url())
    pending_id = str(uuid.uuid4())
    active_id = str(uuid.uuid4())
    archived_id = str(uuid.uuid4())
    with eng.begin() as c:
        for did, status, title in [
            (pending_id, "pending_review", "inv_test_pending"),
            (active_id, "active", "inv_test_active"),
            (archived_id, "archived", "inv_test_archived"),
        ]:
            c.execute(
                text(
                    """
                    INSERT INTO documents (id, tenant_id, repository_id, title, status, version,
                                           processing_meta, legal_hold)
                    VALUES (CAST(:id AS uuid),
                            CAST('00000000-0000-0000-0000-000000000000' AS uuid),
                            CAST('00000000-0000-0000-0000-000000000001' AS uuid),
                            :title, :status, 1,
                            CAST(:meta AS jsonb), false)
                    """
                ),
                {
                    "id": did,
                    "status": status,
                    "title": title,
                    "meta": '{"activation":{"trust_score":0.8}}',
                },
            )
    yield {"pending": pending_id, "active": active_id, "archived": archived_id}
    with eng.begin() as c:
        c.execute(
            text(
                "DELETE FROM documents WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": [pending_id, active_id, archived_id]},
        )


def test_list_inventory_filters_by_status(client, sample_docs):
    r = client.get("/agent/activation/inventory?status=archived&limit=200")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert sample_docs["archived"] in ids
    # active 는 제외돼야 함
    assert sample_docs["active"] not in ids
    # by_status 분포는 필터 무관 — 전체 status 가 다 들어있음
    assert "active" in body["by_status"]
    assert "archived" in body["by_status"]


def test_quota_returns_buckets(client, sample_docs):
    r = client.get("/agent/activation/inventory/quota")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total_size_bytes" in body
    assert "by_status" in body
    assert "by_doc_type" in body
    assert "recent_7d" in body
    assert body["recent_7d"]["added"] >= 3  # 방금 만든 3건 포함
    assert body["by_status"].get("pending_review", 0) >= 1
    assert body["by_status"].get("active", 0) >= 1


def test_bulk_archive_changes_status(client, sample_docs):
    # active 문서를 archive
    r = client.post(
        "/agent/activation/inventory/bulk",
        json={"action": "archive", "artifact_ids": [sample_docs["active"]]},
        headers={"X-User-Id": "u-bulk-test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == 1
    assert body["failed"] == []
    eng = create_engine(_sync_url())
    with eng.begin() as c:
        st = c.execute(
            text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
            {"i": sample_docs["active"]},
        ).scalar()
    assert st == "archived"


def test_bulk_with_invalid_id_partial_success(client, sample_docs):
    bogus = str(uuid.uuid4())
    r = client.post(
        "/agent/activation/inventory/bulk",
        json={
            "action": "archive",
            "artifact_ids": [sample_docs["active"], bogus],
        },
        headers={"X-User-Id": "u-bulk-test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == 1
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == bogus
    assert "error" in body["failed"][0]
