"""Add is_noise column to blocks table.

Revision ID: 021
Revises: 020
Create Date: 2026-04-15

Noise blocks (headers, footers, page numbers, watermarks) were previously
discarded during pipeline processing.  This migration adds a boolean flag
so they can be preserved in the DB for human review while being excluded
from search indexes.
"""

from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column(
            "is_noise",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="true = noise block (excluded from search indexes)",
        ),
    )
    op.create_index("ix_blocks_is_noise", "blocks", ["is_noise"])
    # Composite index for common query: "noise blocks of a document"
    op.create_index(
        "ix_blocks_document_noise",
        "blocks",
        ["document_id", "is_noise"],
    )


def downgrade() -> None:
    op.drop_index("ix_blocks_document_noise", "blocks")
    op.drop_index("ix_blocks_is_noise", "blocks")
    op.drop_column("blocks", "is_noise")
