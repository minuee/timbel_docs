"""add skill_drafts table (Task 34-36 Phase A)

Revision ID: 025
Revises: 024
Create Date: 2026-04-24

Task 34 (Scenario Extractor) + Task 35 (Draft store) + Task 36 (Skill Drafts API).

사용자가 채팅에서 "이런 기능 하나 만들어 줘" 요청 → intent classifier 가
``_skill_draft_request`` sentinel 을 뱉으면 엔진은 DraftComposer 로 skill
YAML draft 를 생성한 뒤 이 테이블에 ``status='pending'`` 으로 쌓아 둔다.
관리자가 UI (Phase B) 에서 검토·승인하면 ``status='approved'`` 로 전환되며
실제 active skill document 로 promote 된다.

- ``account_id`` 로 소유자 묶음 (draft 는 요청한 사용자에게 귀속).
- ``session_id`` 는 요청이 시작된 chat 세션 — 디버깅 / 문맥 복원 용도.
- ``source_user_message`` 는 draft 를 촉발한 마지막 사용자 발화.
- ``status`` CHECK 제약은 pending/approved/rejected/expired 4가지만 허용.
- ``reviewed_by_account_id`` / ``reviewed_at`` 는 결정 audit.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_drafts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("source_user_message", sa.Text, nullable=False),
        sa.Column("draft_yaml", sa.Text, nullable=False),
        sa.Column("draft_title", sa.String(200), nullable=False),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "reviewed_by_account_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_skill_drafts_account_status",
        "skill_drafts",
        ["account_id", "status"],
    )
    op.execute(
        """
        ALTER TABLE skill_drafts
        ADD CONSTRAINT ck_skill_drafts_status
        CHECK (status IN ('pending','approved','rejected','expired'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE skill_drafts DROP CONSTRAINT IF EXISTS ck_skill_drafts_status"
    )
    op.drop_index(
        "idx_skill_drafts_account_status", table_name="skill_drafts"
    )
    op.drop_table("skill_drafts")
