"""skill_drafts.processing_meta 추가 — activation pipeline 에서 사용.

Revision ID: 029
Revises: 028
Create Date: 2026-04-25

activation 파이프라인이 skill_drafts 에서도 processing_meta.activation 을
쓰기 때문에 JSONB 컬럼을 추가. 028 이미 배포된 환경에서 후속 forward-only.

Plan 에 예정됐던 "status→status_v2 cleanup" 은 030 으로 이관.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_drafts",
        sa.Column("processing_meta", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("skill_drafts", "processing_meta")
