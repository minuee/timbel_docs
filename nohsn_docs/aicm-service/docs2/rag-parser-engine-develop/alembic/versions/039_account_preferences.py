"""accounts.preferences + display_name — 사용자 설정 영구화.

Revision ID: 039
Revises: 038
Create Date: 2026-04-26

Phase F10 (KMS-Plus). frontend-v3 의 ``/settings`` 페이지가 호출하는
``/api/v1/account/settings`` GET/PATCH 의 저장소.

- ``accounts.display_name`` (varchar 100, nullable): 사용자가 자신을 부를 호칭.
  사이드바·인사 메시지에서 ``name`` 대신 우선 표시.
- ``accounts.preferences`` (JSONB, NOT NULL DEFAULT '{}'): 톤/시간대/알림 등
  자유 형식 키-값 모음. 스키마는 백엔드가 강제하지 않고 프론트가 관리.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("display_name", sa.String(100), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "preferences",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "preferences")
    op.drop_column("accounts", "display_name")
