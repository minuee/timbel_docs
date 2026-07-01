"""Fix: add missing ORM columns not covered by prior migrations.

Revision ID: kms_001_fix_missing_orm_columns
Revises: 081
Create Date: 2026-05-21

Missing columns discovered (2026-05-21):
- repositories.search_mode  — in ORM, no migration
- repositories.display_config — in ORM, no migration
- repositories.llm_config   — in ORM, no migration
- repositories.agent_id     — in ORM, covered by 065 but may not have run
- repositories.namespace    — in ORM, covered by 065 but may not have run
- api_keys.created_by       — in ORM, no migration

Root cause: SQLAlchemy INSERT...RETURNING fails at runtime if the DB is
missing a column that the ORM mapping expects in the RETURNING clause.
This causes an unhandled ProgrammingError -> generic 500 response.

All ALTER TABLE use ADD COLUMN IF NOT EXISTS — safe to re-run.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "kms_001_fix_missing_orm_columns"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- repositories: missing columns ---
    op.execute(
        "ALTER TABLE repositories "
        "ADD COLUMN IF NOT EXISTS search_mode VARCHAR(20) NOT NULL DEFAULT 'simple',"
        "ADD COLUMN IF NOT EXISTS display_config JSONB NOT NULL DEFAULT '{}'::jsonb,"
        "ADD COLUMN IF NOT EXISTS llm_config JSONB NOT NULL DEFAULT '{}'::jsonb,"
        "ADD COLUMN IF NOT EXISTS agent_id UUID,"
        "ADD COLUMN IF NOT EXISTS namespace TEXT"
    )

    # --- api_keys: missing column ---
    op.execute(
        "ALTER TABLE api_keys "
        "ADD COLUMN IF NOT EXISTS created_by UUID"
    )

    # --- seed default Lucas-KMS tenant (equiv. 082 for linear branch) ---
    op.execute(
        """
        INSERT INTO tenants (
            id, name, slug, config, plan, tenant_type, context_config, feature_flags
        ) VALUES (
            '00000000-0000-0000-0000-000000000001',
            'Lucas-KMS Default',
            'lucas-kms-default',
            '{}'::jsonb,
            'standard',
            'system',
            '{}'::jsonb,
            '{}'::jsonb
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Removing columns is destructive — only do intentionally.
    op.execute(
        "ALTER TABLE repositories "
        "DROP COLUMN IF EXISTS search_mode,"
        "DROP COLUMN IF EXISTS display_config,"
        "DROP COLUMN IF EXISTS llm_config,"
        "DROP COLUMN IF EXISTS agent_id,"
        "DROP COLUMN IF EXISTS namespace"
    )
    op.execute(
        "ALTER TABLE api_keys DROP COLUMN IF EXISTS created_by"
    )
    op.execute(
        "DELETE FROM tenants WHERE id = '00000000-0000-0000-0000-000000000001'"
    )
