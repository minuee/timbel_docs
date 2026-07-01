"""Add system_settings table for platform-wide configuration.

Revision ID: 012_add_system_settings
Revises: 011_enhance_audit_logs
Create Date: 2026-04-12

Stores per-section settings as JSONB (llm, embedding, pipeline, search).
Platform admin only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "014_add_system_settings"
down_revision: Union[str, None] = "013_add_user_totp_and_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """system_settings 테이블 생성."""
    op.create_table(
        "system_settings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "section",
            sa.String(50),
            nullable=False,
            unique=True,
            comment="설정 섹션 (llm, embedding, pipeline, search)",
        ),
        sa.Column(
            "value",
            JSONB,
            nullable=False,
            server_default="{}",
            comment="섹션별 설정값 (JSONB)",
        ),
        sa.Column(
            "updated_by",
            sa.Text,
            nullable=True,
            comment="마지막 수정자 user_id",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="마지막 수정 시각",
        ),
    )

    # section 인덱스 (unique 제약 조건으로 자동 생성되지만 명시적으로도 추가)
    op.create_index(
        "ix_system_settings_section",
        "system_settings",
        ["section"],
        unique=True,
    )


def downgrade() -> None:
    """system_settings 테이블 삭제."""
    op.drop_index("ix_system_settings_section", table_name="system_settings")
    op.drop_table("system_settings")
