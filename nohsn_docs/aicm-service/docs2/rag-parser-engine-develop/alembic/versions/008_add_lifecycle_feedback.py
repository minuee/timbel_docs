"""Add lifecycle_feedback table (Phase C-2).

Revision ID: 008_lifecycle_feedback
Revises: 007_context_tables
Create Date: 2026-04-07

사용자의 블럭 분류 수정 피드백을 기록하는 테이블.
GAP-PROV-04, GAP-DB-10 참조.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "008_lifecycle_feedback"
down_revision: Union[str, None] = "007_context_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """lifecycle_feedback 테이블을 생성한다."""
    op.create_table(
        "lifecycle_feedback",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("block_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("old_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column("feedback_type", sa.String(20), server_default="correction", nullable=False),
        sa.Column("reason", sa.Text, server_default="", nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_lifecycle_feedback_block", "lifecycle_feedback", ["block_id"])
    op.create_index("ix_lifecycle_feedback_tenant", "lifecycle_feedback", ["tenant_id"])


def downgrade() -> None:
    """lifecycle_feedback 테이블을 삭제한다."""
    op.drop_index("ix_lifecycle_feedback_tenant", table_name="lifecycle_feedback")
    op.drop_index("ix_lifecycle_feedback_block", table_name="lifecycle_feedback")
    op.drop_table("lifecycle_feedback")
