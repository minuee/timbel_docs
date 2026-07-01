"""ActivationService — DependencyDiscover wire-up 테스트.

`approve(skill_draft, ...)` 시 주입된 DependencyDiscover.analyze 가 호출되어
processing_meta.activation.dependencies 에 기록되는지 검증.
미주입 (None) 시는 skip 하고 활성화는 정상 진행되어야 한다 (graceful degrade).
"""

from __future__ import annotations

import json as _json
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from src.agent_framework.activation.service import ActivationService
from src.agent_framework.classifier.dependency_discover import DependencyReport


def _seed_skill_draft(db) -> tuple[str, dict]:
    row = db.execute(text(
        "SELECT id, personal_tenant_id FROM accounts ORDER BY created_at LIMIT 1"
    )).mappings().first()
    if not row:
        pytest.skip("no seed accounts available")
    sid = str(uuid.uuid4())
    yaml_text = (
        "name: travel_report\n"
        "description: 출장 복귀 후 HR 제출\n"
        "tools:\n"
        "  - name: hr_api.submit_travel_report\n"
        "    http: {method: POST, path: /travel-report, base: 'mock://hr_api'}\n"
    )
    db.execute(
        text(
            """
            INSERT INTO skill_drafts
              (id, account_id, tenant_id, source_user_message, draft_yaml, draft_title,
               status, status_v2, processing_meta)
            VALUES (CAST(:id AS uuid), :aid, :tid, 'msg', :yaml, 'wire-test-draft',
                    'pending', 'pending_review', CAST(:m AS jsonb))
            """
        ),
        {
            "id": sid,
            "aid": row["id"],
            "tid": row["personal_tenant_id"],
            "yaml": yaml_text,
            "m": _json.dumps({"activation": {}, "tenant_id": "t_test"}),
        },
    )
    db.commit()
    return sid, dict(row)


def _make_discover_with_report(report: DependencyReport) -> MagicMock:
    discover = MagicMock()

    async def _analyze(*, skill_yaml, tenant_id):
        _analyze.last_call = {"skill_yaml": skill_yaml, "tenant_id": tenant_id}
        return report

    discover.analyze = _analyze
    return discover


def test_approve_skill_draft_invokes_dependency_discover(db):
    sid, _ = _seed_skill_draft(db)
    try:
        report = DependencyReport(
            side_effect_level="write_external",
            consequential=True,
            reversible=True,
            required_connectors=[
                {
                    "tool_name": "hr_api.submit_travel_report",
                    "endpoint_hint": "hr_api:mock://hr_api/travel-report",
                    "spec_kind": "custom",
                    "registered": False,
                }
            ],
            unresolved_apis=1,
            reason="POST /travel-report — write external",
        )
        discover = _make_discover_with_report(report)
        svc = ActivationService(db, dependency_discover=discover)
        res = svc.approve(
            artifact_type="skill_draft",
            artifact_id=sid,
            user_id="u_test",
            action="add",
        )
        assert res["status"] == "active"
        row = db.execute(text(
            "SELECT processing_meta FROM skill_drafts WHERE id=CAST(:i AS uuid)"
        ), {"i": sid}).mappings().first()
        deps = row["processing_meta"]["activation"]["dependencies"]
        assert deps["side_effect_level"] == "write_external"
        assert deps["consequential"] is True
        assert deps["unresolved_apis"] == 1
        assert deps["required_connectors"][0]["tool_name"] == "hr_api.submit_travel_report"
    finally:
        db.execute(text("DELETE FROM skill_drafts WHERE id=CAST(:i AS uuid)"), {"i": sid})
        db.commit()


def test_approve_skill_draft_without_discover_is_graceful(db):
    sid, _ = _seed_skill_draft(db)
    try:
        svc = ActivationService(db)  # discover 미주입
        res = svc.approve(
            artifact_type="skill_draft",
            artifact_id=sid,
            user_id="u_test",
            action="add",
        )
        assert res["status"] == "active"
        row = db.execute(text(
            "SELECT processing_meta FROM skill_drafts WHERE id=CAST(:i AS uuid)"
        ), {"i": sid}).mappings().first()
        # dependencies 키가 없거나 None — 활성화는 정상
        act = row["processing_meta"]["activation"]
        assert "dependencies" not in act or act["dependencies"] is None
    finally:
        db.execute(text("DELETE FROM skill_drafts WHERE id=CAST(:i AS uuid)"), {"i": sid})
        db.commit()
