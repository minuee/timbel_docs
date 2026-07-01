"""Batch 8 Task 21 — legacy /api/v1/documents/{id}/apply_classification 가
activation service 를 shim 호출해 status=active + activation.approved_by 기록.
"""
from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.api.main import app


def _sync_url() -> str:
    return (
        os.environ["DATABASE_URL"]
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )


def test_legacy_apply_classification_also_activates():
    c = TestClient(app)
    did = str(uuid.uuid4())
    eng = create_engine(_sync_url())
    with eng.begin() as conn:
        # Phase 11: documents.tenant_id NOT NULL — repo 의 tenant 로 채움.
        tid = conn.execute(
            text(
                "SELECT tenant_id FROM repositories "
                "WHERE id = '00000000-0000-0000-0000-000000000001'"
            )
        ).scalar()
        conn.execute(
            text(
                """
                INSERT INTO documents (id, tenant_id, repository_id, title, status,
                                       version, processing_meta, legal_hold)
                VALUES (CAST(:id AS uuid),
                        :tid,
                        '00000000-0000-0000-0000-000000000001',
                        'legacy_shim_test',
                        'pending_review', 1,
                        CAST(:meta AS jsonb),
                        false)
                """
            ),
            {
                "id": did,
                "tid": tid,
                "meta": (
                    '{"activation":{},'
                    '"auto_classification":{'
                    '"suggested_repository_name":"legacy_shim_repo",'
                    '"suggested_document_type":"manual",'
                    '"confidence":0.9'
                    "}}"
                ),
            },
        )

    try:
        r = c.post(
            f"/api/v1/documents/{did}/apply_classification",
            json={},
            headers={
                "X-User-Id": "u_shim",
                "X-Tenant-Id": "00000000-0000-0000-0000-000000000000",
            },
        )
        # 레거시 구현 세부는 그대로 — 200/204 성공이면 OK.
        assert r.status_code in (200, 204), r.text

        with eng.begin() as conn:
            meta = conn.execute(
                text("SELECT processing_meta FROM documents WHERE id=CAST(:i AS uuid)"),
                {"i": did},
            ).scalar()
        # shim 동작 OK — activation.approved_by == "u_shim"
        assert meta.get("activation", {}).get("approved_by") == "u_shim", meta
    finally:
        with eng.begin() as conn:
            conn.execute(
                text("DELETE FROM documents WHERE id=CAST(:i AS uuid)"), {"i": did}
            )
