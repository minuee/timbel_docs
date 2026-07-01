"""Alembic 030 migration smoke tests — documents.tenant_id 직접 컬럼.

forward-only. 컬럼 존재 + 백필 결과 + 인덱스 존재 검증.
"""
from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

ALEMBIC_INI = "/app/alembic.ini"


@pytest.fixture
def alembic_upgraded_to_030():
    cfg = Config(ALEMBIC_INI)
    command.upgrade(cfg, "030")
    yield


pytestmark = pytest.mark.usefixtures("alembic_upgraded_to_030")


def test_documents_has_tenant_id_column(db):
    rows = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='documents' AND column_name='tenant_id'"
        )
    ).mappings().all()
    assert len(rows) == 1, "tenant_id column not found"


def test_existing_active_docs_have_tenant_id(db):
    """기존 active documents 가 백필됐는지 — repositories 통한 lookup."""
    n = db.execute(
        text(
            "SELECT COUNT(*) FROM documents d "
            "WHERE d.status='active' AND d.tenant_id IS NULL"
        )
    ).scalar()
    assert n == 0, f"{n} active documents still have NULL tenant_id"


def test_idx_documents_tenant_status(db):
    row = db.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname='idx_documents_tenant_status'"
        )
    ).mappings().first()
    assert row is not None, "idx_documents_tenant_status missing"
