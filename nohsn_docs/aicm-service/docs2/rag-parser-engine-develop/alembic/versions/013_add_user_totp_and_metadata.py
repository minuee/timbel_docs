"""Add totp_verified and metadata columns to users table.

Revision ID: 013_add_user_totp_and_metadata
Revises: 012_add_scheduled_actions
Create Date: 2026-04-12

2FA(TOTP) 설정 확인 여부(totp_verified)와 사용자 메타데이터(metadata) JSONB
컬럼을 users 테이블에 추가한다. metadata에는 이용약관/개인정보처리방침 동의
정보를 저장한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "013_add_user_totp_and_metadata"
down_revision: Union[str, None] = "012_add_scheduled_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """totp_verified, metadata 컬럼 추가."""
    op.add_column(
        "users",
        sa.Column(
            "totp_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="2FA TOTP 설정 확인 완료 여부",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "metadata",
            JSONB(),
            nullable=True,
            comment="사용자 메타데이터 (동의 정보 등)",
        ),
    )


def downgrade() -> None:
    """totp_verified, metadata 컬럼 제거."""
    op.drop_column("users", "metadata")
    op.drop_column("users", "totp_verified")
