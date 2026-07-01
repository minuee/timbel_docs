"""Add blocks table for block-based pipeline.

Revision ID: 005_blocks
Revises: 004_audit_logs
Create Date: 2026-04-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "005_blocks"
down_revision: Union[str, None] = "004_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """blocks 테이블 생성."""
    op.create_table(
        "blocks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("block_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("block_index", sa.Integer, nullable=False),
        sa.Column("block_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("source_location", JSONB, server_default="{}", nullable=False),
        sa.Column("metadata", JSONB, server_default="{}", nullable=False),
        sa.Column("vector_id", sa.String(100), nullable=True),
        sa.Column("is_indexed", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 인덱스
    op.create_index("ix_blocks_document_id", "blocks", ["document_id"])
    op.create_index("ix_blocks_repository_id", "blocks", ["repository_id"])
    op.create_index("ix_blocks_document_order", "blocks", ["document_id", "block_index"])

    # 유니크 제약
    op.create_unique_constraint("uq_blocks_document_hash", "blocks", ["document_id", "block_hash"])


def downgrade() -> None:
    """blocks 테이블 삭제."""
    op.drop_table("blocks")
