"""verification_proposals 테이블 — KMS-Plus P0.2.

Revision ID: 049
Revises: 048
Create Date: 2026-04-28

배경
----
PR P9 의 self-audit 결과 — 시스템이 "이런 시나리오를 추가하자" 라고 제안한
yaml drafts 의 review queue. 운영자가 accept/reject 결정.

설계
----
- ``source``               text — 'self_audit', 'manual' 등 자유 식별자
- ``suggested_yaml``       text — 제안된 시나리오 yaml
- ``evidence``             JSONB default '{}' — 근거 (실패 trace 등)
- ``status``               text default 'proposed' — proposed/accepted/rejected/expired
- ``created_at``           timestamptz default now()
- ``reviewed_at``          timestamptz NULL
- ``reviewer_account_id``  UUID NULL — 리뷰어 (FK 강제 X — 옛 계정 삭제 후에도 기록 보존)

7일 expire (proposed) 처리는 P9 의 cron 이 담당. 본 마이그는 partial index
로 인덱싱만 준비.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_proposals" in inspector.get_table_names():
        return
    op.create_table(
        "verification_proposals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("suggested_yaml", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="proposed"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewer_account_id", UUID(as_uuid=True), nullable=True
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_verification_proposals_status_created "
        "ON verification_proposals (status, created_at DESC)"
    )
    # 7-day expire 후보 — proposed 상태만 인덱싱 (전체 row 의 일부).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_verification_proposals_proposed_created "
        "ON verification_proposals (created_at) WHERE status = 'proposed'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_proposals" not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_verification_proposals_proposed_created")
    op.execute("DROP INDEX IF EXISTS ix_verification_proposals_status_created")
    op.drop_table("verification_proposals")
