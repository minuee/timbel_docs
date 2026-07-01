"""ActivationService — KnowledgeOverlapAnalyzer wire-up 테스트.

`approve(document, ...)` 시 주입된 overlap_analyzer.analyze 가 호출되어
processing_meta.activation.overlap 에 기록되는지 검증.
미주입 시는 skip 하고 활성화는 정상 진행되어야 한다 (graceful degrade).
"""

from __future__ import annotations

import json as _json
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from src.agent_framework.activation.service import ActivationService
from src.agent_framework.activation.overlap_analyzer import OverlapReport


_TEST_REPO_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def doc_id_with_summary(db):
    did = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO documents (id, tenant_id, repository_id, title, status, processing_meta)
            VALUES (CAST(:id AS uuid),
                    CAST('00000000-0000-0000-0000-000000000000' AS uuid),
                    CAST(:rid AS uuid), 'KB 적금 240603 약관', 'pending_review',
                    CAST(:m AS jsonb))
            """
        ),
        {
            "id": did,
            "rid": _TEST_REPO_ID,
            "m": _json.dumps({"activation": {}, "summary": "KB 적금 2024-06 신규 약관 요약"}),
        },
    )
    db.commit()
    yield did
    db.execute(text("DELETE FROM documents WHERE id=CAST(:id AS uuid)"), {"id": did})
    db.commit()


def _make_analyzer_with_report(report: OverlapReport) -> MagicMock:
    analyzer = MagicMock()

    async def _analyze(*, tenant_id, new_doc_id, new_summary):
        _analyze.last_call = {
            "tenant_id": tenant_id,
            "new_doc_id": new_doc_id,
            "new_summary": new_summary,
        }
        return report

    analyzer.analyze = _analyze
    return analyzer


def test_approve_document_invokes_overlap_analyzer(db, doc_id_with_summary):
    report = OverlapReport(
        summary="KB 적금 2024-06 신규 약관 요약",
        hits=[
            {
                "doc_id": "11111111-2222-3333-4444-555555555555",
                "title": "KB 적금 2023-12 약관",
                "snippet": "구버전",
                "relation": "supersedes_existing",
                "confidence": 0.92,
                "evidence": "발효일 차이",
                "suggested_action": "replace",
            }
        ],
        suggested_action="approve_and_archive:11111111-2222-3333-4444-555555555555",
        requires_human=False,
        analyzed_at="2026-04-25T00:00:00+00:00",
    )
    analyzer = _make_analyzer_with_report(report)
    svc = ActivationService(db, overlap_analyzer=analyzer)
    res = svc.approve(
        artifact_type="document",
        artifact_id=doc_id_with_summary,
        user_id="u_test",
        action="add",
    )
    assert res["status"] == "active"
    row = db.execute(
        text("SELECT processing_meta FROM documents WHERE id=CAST(:i AS uuid)"),
        {"i": doc_id_with_summary},
    ).mappings().first()
    overlap = row["processing_meta"]["activation"]["overlap"]
    assert overlap["suggested_action"].startswith("approve_and_archive:")
    assert overlap["hits"][0]["relation"] == "supersedes_existing"
    # analyzer 호출 페이로드 확인
    assert analyzer.analyze.last_call["new_doc_id"] == doc_id_with_summary
    assert analyzer.analyze.last_call["new_summary"] == "KB 적금 2024-06 신규 약관 요약"


def test_approve_document_without_analyzer_is_graceful(db, doc_id_with_summary):
    svc = ActivationService(db)  # analyzer 미주입
    res = svc.approve(
        artifact_type="document",
        artifact_id=doc_id_with_summary,
        user_id="u_test",
        action="add",
    )
    assert res["status"] == "active"
    row = db.execute(
        text("SELECT processing_meta FROM documents WHERE id=CAST(:i AS uuid)"),
        {"i": doc_id_with_summary},
    ).mappings().first()
    act = row["processing_meta"]["activation"]
    assert "overlap" not in act or act["overlap"] is None
