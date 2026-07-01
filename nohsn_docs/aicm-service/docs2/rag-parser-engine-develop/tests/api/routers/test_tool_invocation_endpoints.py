"""Phase 1 (KMS-Plus) 델타 #5 — tool_invocation approve/reject 엔드포인트.

pending_confirm 상태 invocation 을 사용자 승인 → pending_resume 전이,
사용자 거절 → canceled 전이를 확인.
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
def pending_invocation():
    """pending_confirm 상태 tool_invocation row 를 직접 INSERT 하고 yield, 끝나면 정리."""
    eng = create_engine(_sync_url())
    inv_id = f"inv_{uuid.uuid4().hex[:16]}"
    token = "tok_" + uuid.uuid4().hex[:24]
    with eng.begin() as c:
        c.execute(
            text(
                """
                INSERT INTO tool_invocations
                  (id, tenant_id, session_id, turn_id, skill_id, cc_pair_id,
                   tool_name, input_args, status, resume_token, dry_run)
                VALUES (:id, 't1', 's1', NULL, 'sk1', NULL,
                        'noop', '{}'::jsonb, 'pending_confirm', :tok, FALSE)
                """
            ),
            {"id": inv_id, "tok": token},
        )
    yield {"id": inv_id, "resume_token": token}
    with eng.begin() as c:
        c.execute(text("DELETE FROM tool_invocations WHERE id=:i"), {"i": inv_id})


def test_approve_tool_invocation_transitions_to_pending_resume(
    client, pending_invocation
):
    inv_id = pending_invocation["id"]
    expected_token = pending_invocation["resume_token"]
    r = client.post(
        f"/agent/activation/tool_invocation/{inv_id}/approve",
        json={"note": "ok by user"},
        headers={"X-User-Id": "u1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending_resume"
    assert body["resume_token"] == expected_token

    # DB 측 검증
    eng = create_engine(_sync_url())
    with eng.begin() as c:
        row = c.execute(
            text(
                "SELECT status, confirmed_by_user, confirmed_by_user_id "
                "FROM tool_invocations WHERE id=:i"
            ),
            {"i": inv_id},
        ).mappings().first()
    assert row["status"] == "pending_resume"
    assert row["confirmed_by_user"] is True
    assert row["confirmed_by_user_id"] == "u1"


def test_reject_tool_invocation_transitions_to_canceled(client, pending_invocation):
    inv_id = pending_invocation["id"]
    r = client.post(
        f"/agent/activation/tool_invocation/{inv_id}/reject",
        json={"reason": "user said no"},
        headers={"X-User-Id": "u2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "canceled"

    eng = create_engine(_sync_url())
    with eng.begin() as c:
        row = c.execute(
            text(
                "SELECT status, error, confirmed_by_user, confirmed_by_user_id "
                "FROM tool_invocations WHERE id=:i"
            ),
            {"i": inv_id},
        ).mappings().first()
    assert row["status"] == "canceled"
    assert row["error"] == "user said no"
    assert row["confirmed_by_user"] is True
    assert row["confirmed_by_user_id"] == "u2"
