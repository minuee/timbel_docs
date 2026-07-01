"""Add Phase 2 tables and api_keys.usage_count column.

Tables: webhook_configs, webhook_dead_letters, sync_sources, sync_mappings, tenant_synonyms.
Columns: api_keys.usage_count.

Revision ID: 003_phase2_tables
Revises: 002_users_rbac
Create Date: 2026-04-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "003_phase2_tables"
down_revision: Union[str, None] = "002_users_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Phase 2 테이블을 생성하고 기존 테이블에 컬럼을 추가한다."""

    # === api_keys.usage_count 컬럼 추가 ===
    op.add_column(
        "api_keys",
        sa.Column("usage_count", sa.Integer(), server_default="0", nullable=False),
    )

    # === webhook_configs ===
    op.create_table(
        "webhook_configs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("events", ARRAY(sa.String), nullable=False),
        sa.Column("secret", sa.String(256), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("failure_count", sa.Integer(), default=0, server_default="0"),
        sa.Column(
            "last_triggered_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # === webhook_dead_letters ===
    op.create_table(
        "webhook_dead_letters",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "webhook_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_body", sa.String, nullable=False),
        sa.Column("last_error", sa.String(2000), nullable=True),
        sa.Column(
            "retry_count", sa.Integer(), default=0, server_default="0"
        ),
        sa.Column(
            "last_retry_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # === sync_sources ===
    op.create_table(
        "sync_sources",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "repository_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column(
            "config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "schedule_cron",
            sa.String(100),
            nullable=False,
            server_default="*/5 * * * *",
        ),
        sa.Column(
            "last_synced_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_status",
            sa.String(20),
            nullable=False,
            server_default="idle",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "total_synced", sa.Integer(), default=0, server_default="0"
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # === sync_mappings ===
    op.create_table(
        "sync_mappings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "sync_source_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("remote_id", sa.String(500), nullable=False, index=True),
        sa.Column("remote_name", sa.String(500), nullable=False),
        sa.Column(
            "remote_modified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "document_id", UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # === tenant_synonyms ===
    op.create_table(
        "tenant_synonyms",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column("term", sa.String(200), nullable=False),
        sa.Column("synonyms", ARRAY(sa.String), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "term", name="uq_tenant_synonyms_tenant_term"),
    )


def downgrade() -> None:
    """Phase 2 테이블을 역순으로 삭제하고 추가 컬럼을 제거한다."""
    op.drop_table("tenant_synonyms")
    op.drop_table("sync_mappings")
    op.drop_table("sync_sources")
    op.drop_table("webhook_dead_letters")
    op.drop_table("webhook_configs")
    op.drop_column("api_keys", "usage_count")
