"""Phase 11 — activation router 의 tenant_id 필터 검증.

documents 분기 (/pending, /stats, /inventory) 가 tenant_id 직접 컬럼으로
필터링하는지 + repository_id fallback 도 동작하는지.
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
def two_tenant_pending_docs():
    """서로 다른 tenant 에 속한 pending_review 문서 2건 생성.

    repository 는 한 default repo (id=00...01) 를 공유하지만 documents.tenant_id
    컬럼만 다르게 직접 주입 — Phase 11 의 직접 컬럼 필터 검증용.
    """
    eng = create_engine(_sync_url())
    rid = "00000000-0000-0000-0000-000000000001"
    t1 = str(uuid.uuid4())
    t2 = str(uuid.uuid4())
    d1 = str(uuid.uuid4())
    d2 = str(uuid.uuid4())
    with eng.begin() as c:
        c.execute(
            text(
                """
                INSERT INTO documents
                  (id, tenant_id, repository_id, title, status, version,
                   processing_meta, legal_hold)
                VALUES
                  (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:rid AS uuid),
                   :t, 'pending_review', 1,
                   '{"activation":{"overlap_report":{"hits":[]}}}'::jsonb, false)
                """
            ),
            {"id": d1, "tid": t1, "rid": rid, "t": "phase11_t1_doc"},
        )
        c.execute(
            text(
                """
                INSERT INTO documents
                  (id, tenant_id, repository_id, title, status, version,
                   processing_meta, legal_hold)
                VALUES
                  (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:rid AS uuid),
                   :t, 'pending_review', 1,
                   '{"activation":{"overlap_report":{"hits":[]}}}'::jsonb, false)
                """
            ),
            {"id": d2, "tid": t2, "rid": rid, "t": "phase11_t2_doc"},
        )
    yield {"t1": t1, "t2": t2, "d1": d1, "d2": d2, "rid": rid}
    with eng.begin() as c:
        c.execute(
            text(
                "DELETE FROM documents WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"
            ),
            {"a": d1, "b": d2},
        )


def test_pending_with_tenant_id_filter(client, two_tenant_pending_docs):
    """tenant_id 필터 — t1 doc 만 보이고 t2 doc 안 보임."""
    fx = two_tenant_pending_docs
    r = client.get(f"/agent/activation/pending?type=document&tenant_id={fx['t1']}")
    assert r.status_code == 200, r.text
    ids = [x["artifact_id"] for x in r.json()]
    assert fx["d1"] in ids
    assert fx["d2"] not in ids


def test_pending_with_repository_id_fallback(client, two_tenant_pending_docs):
    """tenant_id 없이 repository_id 만 — legacy 동작 (둘 다 같은 repo 라 둘 다 보임)."""
    fx = two_tenant_pending_docs
    r = client.get(
        f"/agent/activation/pending?type=document&repository_id={fx['rid']}"
    )
    assert r.status_code == 200, r.text
    ids = [x["artifact_id"] for x in r.json()]
    # 같은 repo 라 둘 다 노출 (tenant 격리 없음 — fallback 동작)
    assert fx["d1"] in ids
    assert fx["d2"] in ids
