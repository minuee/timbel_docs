"""Phase 11 — 테넌트 격리 e2e 회귀.

T-medical 의 사용자가 T-finance 의 documents 를 못 본다.
documents.tenant_id 직접 컬럼 (migration 030) 으로 격리되는지 확인.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text


def _sync_url() -> str:
    return (
        os.environ["DATABASE_URL"]
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )


@pytest.fixture
def db():
    eng = create_engine(_sync_url(), future=True)
    with eng.begin() as conn:
        yield conn
    eng.dispose()


def _mk_doc(db, tenant_id: str, repository_id: str, title: str) -> str:
    did = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO documents
              (id, tenant_id, repository_id, title, status, version,
               processing_meta, legal_hold)
            VALUES
              (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:rid AS uuid),
               :t, 'active', 1, '{}'::jsonb, false)
            """
        ),
        {"id": did, "tid": tenant_id, "rid": repository_id, "t": title},
    )
    return did


def test_tenant_filter_isolates(db):
    """다른 tenant 의 documents 가 tenant_id 필터에 안 잡힘."""
    rid = "00000000-0000-0000-0000-000000000001"  # default repo
    t1 = str(uuid.uuid4())
    t2 = str(uuid.uuid4())
    d1 = _mk_doc(db, t1, rid, "T1 doc")
    d2 = _mk_doc(db, t2, rid, "T2 doc")

    try:
        # T1 의 documents 만 보임
        rows = db.execute(
            text("SELECT id FROM documents WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": t1},
        ).mappings().all()
        ids = {str(r["id"]) for r in rows}
        assert d1 in ids
        assert d2 not in ids

        # T2 도 동일하게 격리
        rows2 = db.execute(
            text("SELECT id FROM documents WHERE tenant_id = CAST(:tid AS uuid)"),
            {"tid": t2},
        ).mappings().all()
        ids2 = {str(r["id"]) for r in rows2}
        assert d2 in ids2
        assert d1 not in ids2
    finally:
        db.execute(
            text(
                "DELETE FROM documents WHERE id IN "
                "(CAST(:a AS uuid), CAST(:b AS uuid))"
            ),
            {"a": d1, "b": d2},
        )
