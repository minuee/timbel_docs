"""add permanent_failure column to dlq_messages

Revision ID: 020
Revises: 019
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dlq_messages",
        sa.Column(
            "permanent_failure",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_dlq_messages_permanent_failure",
        "dlq_messages",
        ["permanent_failure"],
    )


def downgrade() -> None:
    op.drop_index("ix_dlq_messages_permanent_failure", "dlq_messages")
    op.drop_column("dlq_messages", "permanent_failure")
