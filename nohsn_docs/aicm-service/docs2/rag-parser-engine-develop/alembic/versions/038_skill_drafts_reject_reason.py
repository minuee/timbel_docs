"""skill_drafts.reject_reason — 반려 사유 영구화.

Revision ID: 038
Revises: 037
Create Date: 2026-04-26

검토자가 draft 를 reject 할 때 입력한 사유 텍스트를 DB 에 보존한다.
프론트(검토 큐 UI) 가 이미 사유를 수집·전송하지만 백엔드는 지금까지 무시.
nullable=True — 기존 row 호환 + 빈 사유 허용.
"""
from alembic import op
import sqlalchemy as sa


revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_drafts",
        sa.Column("reject_reason", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_drafts", "reject_reason")
