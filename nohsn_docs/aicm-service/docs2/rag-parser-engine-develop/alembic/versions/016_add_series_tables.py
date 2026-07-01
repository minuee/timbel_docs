"""시리즈 데이터 모델 — CDC 축적 데이터 시계열 관리.

Revision ID: 016_add_series_tables
Revises: 015_db_indexes
Create Date: 2026-04-14

knowledge_series: 시리즈 메타데이터 (지출, 체중, 영업실적 등)
series_entries: 시리즈에 속하는 개별 데이터 포인트
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "016_add_series_tables"
down_revision: Union[str, None] = "015_db_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """knowledge_series + series_entries 테이블 생성."""

    # ----- knowledge_series -----
    op.create_table(
        "knowledge_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True, comment="NULL이면 팀 공유 시리즈"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("series_type", sa.String(50), nullable=False, comment="expense, body_metric, exercise, sales 등"),
        sa.Column("scope", sa.String(20), server_default="personal", nullable=False, comment="personal | team | organization"),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data_schema", postgresql.JSONB(), server_default="{}", nullable=False, comment="시리즈 데이터 스키마 정의"),
        sa.Column("aggregation_config", postgresql.JSONB(), server_default="{}", nullable=False, comment="집계 설정"),
        sa.Column("visualization_config", postgresql.JSONB(), server_default="{}", nullable=False, comment="시각화 설정"),
        sa.Column("alert_config", postgresql.JSONB(), server_default="{}", nullable=False, comment="알림 설정"),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ----- series_entries -----
    op.create_table(
        "series_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("blocks.id", ondelete="SET NULL"), nullable=True, comment="연결된 CDC 블럭 ID"),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_time", sa.Time(), nullable=True),
        sa.Column("source", sa.String(20), server_default="chat", nullable=False, comment="chat | manual | import"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ----- indexes -----
    op.create_index("ix_series_tenant", "knowledge_series", ["tenant_id"])
    op.create_index("ix_series_user", "knowledge_series", ["user_id"])
    op.create_index("ix_series_type", "knowledge_series", ["series_type"])

    op.create_index("ix_entries_series", "series_entries", ["series_id"])
    op.create_index("ix_entries_date", "series_entries", ["entry_date"])
    op.create_index("ix_entries_series_date", "series_entries", ["series_id", "entry_date"])


def downgrade() -> None:
    """series_entries + knowledge_series 테이블 삭제."""
    op.drop_index("ix_entries_series_date", table_name="series_entries")
    op.drop_index("ix_entries_date", table_name="series_entries")
    op.drop_index("ix_entries_series", table_name="series_entries")
    op.drop_index("ix_series_type", table_name="knowledge_series")
    op.drop_index("ix_series_user", table_name="knowledge_series")
    op.drop_index("ix_series_tenant", table_name="knowledge_series")

    op.drop_table("series_entries")
    op.drop_table("knowledge_series")
