"""Smoke tests for scripts/migrate/seed_activation_samples.py.

컨테이너 내부에서 pytest 가 돌 때, subprocess 로 같은 파이썬 런타임을 써서
seed 스크립트를 --execute 로 호출한다. idempotent 하므로 두 번 돌아도 OK.
"""
from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import text


SEED_SCRIPT = "/app/scripts/migrate/seed_activation_samples.py"


def _run_seed_execute() -> None:
    subprocess.run(
        ["python", SEED_SCRIPT, "--execute"],
        check=True,
        capture_output=True,
    )


def test_seed_inserts_documents(db):
    _run_seed_execute()

    n_pending = db.execute(
        text(
            "SELECT COUNT(*) FROM documents "
            "WHERE status='pending_review' "
            "  AND processing_meta->>'seed_source' = 'activation_samples'"
        )
    ).scalar()
    assert n_pending >= 2, f"pending_review seed docs too few: {n_pending}"

    n_auto = db.execute(
        text(
            "SELECT COUNT(*) FROM documents "
            "WHERE status='active' "
            "  AND processing_meta->>'seed_source' = 'activation_samples'"
        )
    ).scalar()
    assert n_auto >= 2, f"active (auto_approved) seed docs too few: {n_auto}"


def test_seed_inserts_skill_drafts(db):
    _run_seed_execute()

    n_skill = db.execute(
        text(
            "SELECT COUNT(*) FROM skill_drafts "
            "WHERE status_v2='pending_review' "
            "  AND processing_meta->>'seed_source' = 'activation_samples'"
        )
    ).scalar()
    assert n_skill >= 1, f"pending skill_drafts too few: {n_skill}"


def test_mock_hr_api_ccpair_seeded(db):
    _run_seed_execute()

    row = db.execute(
        text(
            """
            SELECT ccp.id, ccp.status, c.name AS cname, cr.name AS crname,
                   ccp.processing_meta
              FROM connector_credential_pairs ccp
              JOIN connectors c ON c.id = ccp.connector_id
              JOIN connector_credentials cr ON cr.id = ccp.credential_id
             WHERE c.name='mock_hr_api'
             LIMIT 1
            """
        )
    ).mappings().first()
    assert row is not None, "mock_hr_api CC-pair not seeded"
    assert row["status"] == "active", f"unexpected ccp status: {row['status']}"


def test_seed_idempotent(db):
    """두 번째 호출해도 행 개수가 증가하지 않아야 한다."""
    _run_seed_execute()
    n1 = db.execute(
        text(
            "SELECT COUNT(*) FROM documents "
            "WHERE processing_meta->>'seed_source' = 'activation_samples'"
        )
    ).scalar()
    _run_seed_execute()
    n2 = db.execute(
        text(
            "SELECT COUNT(*) FROM documents "
            "WHERE processing_meta->>'seed_source' = 'activation_samples'"
        )
    ).scalar()
    assert n1 == n2, f"not idempotent: {n1} -> {n2}"
