"""Batch 8 Task 20 — /agent/activation/* 통합 라우터 integration test.

실제 DB (sync SQLAlchemy connection) 로 documents 에 sample row 를 꽂고
라우터를 통해 pending→approve/reject 전이를 검증.
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


@pytest.fixture
def sample_pending_doc():
    """pending_review 상태 샘플 문서를 생성하고 yield 후 삭제.

    Phase 11: documents.tenant_id NOT NULL — 해당 repository 의 tenant_id 를
    조회해 함께 채움.
    """
    eng = create_engine(_sync_url())
    did = str(uuid.uuid4())
    with eng.begin() as c:
        tid = c.execute(
            text(
                "SELECT tenant_id FROM repositories "
                "WHERE id = '00000000-0000-0000-0000-000000000001'"
            )
        ).scalar()
        c.execute(
            text(
                """
                INSERT INTO documents (id, tenant_id, repository_id, title, status,
                                       version, processing_meta, legal_hold)
                VALUES (CAST(:id AS uuid),
                        :tid,
                        '00000000-0000-0000-0000-000000000001',
                        'activation_router_sample',
                        'pending_review',
                        1,
                        '{"activation":{"overlap_report":{"hits":[]}}}'::jsonb,
                        false)
                """
            ),
            {"id": did, "tid": tid},
        )
    yield did
    with eng.begin() as c:
        c.execute(text("DELETE FROM documents WHERE id=CAST(:id AS uuid)"), {"id": did})


def test_list_pending_returns_sample_doc(client, sample_pending_doc):
    # 합성 데이터 누적 환경에서 LIMIT 페이지네이션 회피 — detail endpoint 로 직접 조회
    r = client.get(f"/agent/activation/document/{sample_pending_doc}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert str(body["id"]) == sample_pending_doc
    assert body["status"] == "pending_review"


def test_approve_transitions_to_active(client, sample_pending_doc):
    r = client.post(
        f"/agent/activation/document/{sample_pending_doc}/approve",
        json={"action": "add", "note": "ok"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 200, r.text
    eng = create_engine(_sync_url())
    with eng.begin() as c:
        status = c.execute(
            text("SELECT status FROM documents WHERE id=CAST(:id AS uuid)"),
            {"id": sample_pending_doc},
        ).scalar()
    assert status == "active"


def test_reject_transitions_to_rejected(client, sample_pending_doc):
    r = client.post(
        f"/agent/activation/document/{sample_pending_doc}/reject",
        json={"reason": "spam"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 200, r.text
    eng = create_engine(_sync_url())
    with eng.begin() as c:
        status = c.execute(
            text("SELECT status FROM documents WHERE id=CAST(:id AS uuid)"),
            {"id": sample_pending_doc},
        ).scalar()
    assert status == "rejected"


def test_stats_returns_counts(client, sample_pending_doc):
    r = client.get("/agent/activation/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pending" in body and "active" in body
    assert body["pending"] >= 1
