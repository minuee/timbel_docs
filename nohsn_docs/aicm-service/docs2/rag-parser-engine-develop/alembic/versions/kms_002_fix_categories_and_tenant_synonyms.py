"""Fix: add missing categories columns + ensure tenant_synonyms table exists.

Revision ID: kms_002_fix_categories_and_tenant_synonyms
Revises: kms_001_fix_missing_orm_columns
Create Date: 2026-05-26

Missing items discovered (2026-05-26):
- categories.synonyms   — in ORM (ARRAY(String)), never added via migration
- categories.embedding  — in ORM (JSONB), never added via migration
- categories.auto_classify — in ORM (Boolean), never added via migration
- tenant_synonyms table — created by migration 003, but missing on create_all
  deployments (no ORM model existed). Now added as ORM + idempotent CREATE.

Root cause:
  On alembic-managed DBs (migration 001 → 081), categories was created by 001
  (id, repo_id, name, description, parent_id, sort_order, is_active, created_at)
  and extended by 009 (version, effective_from, deprecated_at, successor_id).
  synonyms/embedding/auto_classify were added to the ORM but no migration was
  written, so INSERT fails with "column does not exist" -> 500.

  On create_all deployments, init_db.py creates categories with all ORM columns
  (no issue) but skips tenant_synonyms because no ORM model existed.

All operations use IF NOT EXISTS — safe to re-run on any DB state.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "kms_002_fix_categories_and_tenant_synonyms"
down_revision: Union[str, None] = "kms_001_fix_missing_orm_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- categories: 온톨로지 확장 컬럼 (ORM에 있으나 마이그레이션 누락) ---
    op.execute(
        "ALTER TABLE categories "
        "ADD COLUMN IF NOT EXISTS synonyms text[],"
        "ADD COLUMN IF NOT EXISTS embedding jsonb,"
        "ADD COLUMN IF NOT EXISTS auto_classify boolean NOT NULL DEFAULT true"
    )

    # --- tenant_synonyms: create_all 경로에서 누락된 테이블 보정 ---
    # migration 003 에서 이미 생성된 경우 IF NOT EXISTS 로 무시됨.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_synonyms (
            id          UUID    NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id   UUID    NOT NULL REFERENCES tenants(id),
            term        VARCHAR(200) NOT NULL,
            synonyms    TEXT[]  NOT NULL,
            is_active   BOOLEAN NOT NULL DEFAULT true,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_tenant_synonyms_tenant_term UNIQUE (tenant_id, term)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tenant_synonyms_tenant_id "
        "ON tenant_synonyms (tenant_id)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE categories "
        "DROP COLUMN IF EXISTS auto_classify,"
        "DROP COLUMN IF EXISTS embedding,"
        "DROP COLUMN IF EXISTS synonyms"
    )
    # tenant_synonyms 는 데이터 보존 우선 — downgrade 시 삭제하지 않음.
