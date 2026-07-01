"""Backend feature checklist items — new tables and columns.

Revision ID: 009_backend_features
Revises: 008_lifecycle_feedback
Create Date: 2026-04-07

New tables: llm_usage, dlq_messages
New columns: categories (version, effective_from, deprecated_at, successor_id)
             blocks (legal_hold), documents (legal_hold)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "009_backend_features"
down_revision: Union[str, None] = "008_lifecycle_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """신규 테이블 생성 및 컬럼 추가."""

    # --- llm_usage 테이블 ---
    op.create_table(
        "llm_usage",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("task", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # --- dlq_messages 테이블 ---
    op.create_table(
        "dlq_messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("topic", sa.String(200), nullable=False, index=True),
        sa.Column("offset", sa.Integer, nullable=False, server_default="0"),
        sa.Column("partition", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("error_traceback", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # --- categories: 버전 관리 컬럼 ---
    op.add_column(
        "categories",
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.add_column(
        "categories",
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.add_column(
        "categories",
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "categories",
        sa.Column(
            "successor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("categories.id"),
            nullable=True,
        ),
    )

    # --- blocks: legal_hold ---
    op.add_column(
        "blocks",
        sa.Column("legal_hold", sa.Boolean, nullable=False, server_default="false"),
    )

    # --- documents: legal_hold ---
    op.add_column(
        "documents",
        sa.Column("legal_hold", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """롤백: 추가된 컬럼 및 테이블을 제거한다."""
    op.drop_column("documents", "legal_hold")
    op.drop_column("blocks", "legal_hold")
    op.drop_column("categories", "successor_id")
    op.drop_column("categories", "deprecated_at")
    op.drop_column("categories", "effective_from")
    op.drop_column("categories", "version")
    op.drop_table("dlq_messages")
    op.drop_table("llm_usage")
