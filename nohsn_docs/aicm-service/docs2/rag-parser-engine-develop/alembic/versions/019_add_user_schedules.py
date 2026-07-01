"""add user_schedules table

Revision ID: 019
Revises: 018
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018_add_chat_session_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("attendees", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(30), server_default="internal", nullable=False),
        sa.Column("external_id", sa.String(300), nullable=True),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("blocks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("is_completed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_schedules_tenant_user", "user_schedules", ["tenant_id", "user_id"])
    op.create_index("ix_schedules_date", "user_schedules", ["event_date"])
    op.create_index("ix_schedules_source", "user_schedules", ["source"])
    op.create_index("ix_schedules_external", "user_schedules", ["source", "external_id"])


def downgrade() -> None:
    op.drop_index("ix_schedules_external", "user_schedules")
    op.drop_index("ix_schedules_source", "user_schedules")
    op.drop_index("ix_schedules_date", "user_schedules")
    op.drop_index("ix_schedules_tenant_user", "user_schedules")
    op.drop_table("user_schedules")
