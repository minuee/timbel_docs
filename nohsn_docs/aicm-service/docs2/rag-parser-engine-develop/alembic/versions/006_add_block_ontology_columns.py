"""Add ontology columns to blocks table (Phase A-5).

Revision ID: 006_block_ontology
Revises: 005_blocks
Create Date: 2026-04-07

New columns: nature, time_reference, entities, domain_category_ids,
validity_status, classification_provenance.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

# revision identifiers, used by Alembic.
revision: str = "006_block_ontology"
down_revision: Union[str, None] = "005_blocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """blocks 테이블에 온톨로지 컬럼을 추가한다."""
    op.add_column(
        "blocks",
        sa.Column(
            "nature",
            sa.String(30),
            nullable=True,
            comment="fact/opinion/schedule/record/reference/casual",
        ),
    )
    op.add_column(
        "blocks",
        sa.Column(
            "time_reference",
            JSONB,
            nullable=True,
            comment='{"raw": "...", "resolved": "ISO", "basis": "..."}',
        ),
    )
    op.add_column(
        "blocks",
        sa.Column(
            "entities",
            JSONB,
            nullable=True,
            comment='{"speakers": [], "people": [], "orgs": [], "locations": []}',
        ),
    )
    op.add_column(
        "blocks",
        sa.Column(
            "domain_category_ids",
            ARRAY(sa.String),
            nullable=True,
            comment="분류된 카테고리 ID 목록",
        ),
    )
    op.add_column(
        "blocks",
        sa.Column(
            "validity_status",
            sa.String(20),
            server_default="active",
            nullable=False,
            comment="active/superseded/expired",
        ),
    )
    op.add_column(
        "blocks",
        sa.Column(
            "classification_provenance",
            JSONB,
            nullable=True,
            comment="분류 추론 과정 (reasoning, model, confidence 등)",
        ),
    )

    # 인덱스 (검색 필터 성능)
    op.create_index("ix_blocks_nature", "blocks", ["nature"])
    op.create_index("ix_blocks_validity_status", "blocks", ["validity_status"])


def downgrade() -> None:
    """온톨로지 컬럼을 제거한다."""
    op.drop_index("ix_blocks_validity_status", table_name="blocks")
    op.drop_index("ix_blocks_nature", table_name="blocks")
    op.drop_column("blocks", "classification_provenance")
    op.drop_column("blocks", "validity_status")
    op.drop_column("blocks", "domain_category_ids")
    op.drop_column("blocks", "entities")
    op.drop_column("blocks", "time_reference")
    op.drop_column("blocks", "nature")
