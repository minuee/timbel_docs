"""Add life_context and corporate_context tables (Phase B-5).

Revision ID: 007_context_tables
Revises: 006_block_ontology
Create Date: 2026-04-07

생애 맥락(개인 테넌트용)과 기업 맥락(기업 테넌트용) 테이블을 추가한다.
QueryDecomposer가 검색 리파인먼트에 활용한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "007_context_tables"
down_revision: Union[str, None] = "006_block_ontology"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """life_context, corporate_context 테이블을 생성한다."""

    # --- life_context ---
    op.create_table(
        "life_context",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("context_domain", sa.String(50), nullable=False),
        sa.Column(
            "current_value",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_value", JSONB, nullable=True),
        sa.Column(
            "transition_event_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
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
    op.create_index("ix_life_context_tenant", "life_context", ["tenant_id"])
    op.create_index(
        "ix_life_context_domain", "life_context", ["tenant_id", "context_domain"]
    )

    # --- corporate_context ---
    op.create_table(
        "corporate_context",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("context_domain", sa.String(50), nullable=False),
        sa.Column(
            "current_value",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_value", JSONB, nullable=True),
        sa.Column(
            "transition_event_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_corporate_context_tenant", "corporate_context", ["tenant_id"])


def downgrade() -> None:
    """life_context, corporate_context 테이블을 삭제한다."""
    op.drop_index("ix_corporate_context_tenant", table_name="corporate_context")
    op.drop_table("corporate_context")

    op.drop_index("ix_life_context_domain", table_name="life_context")
    op.drop_index("ix_life_context_tenant", table_name="life_context")
    op.drop_table("life_context")
