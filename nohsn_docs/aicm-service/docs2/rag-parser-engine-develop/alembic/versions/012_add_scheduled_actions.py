"""Add scheduled_actions table for lifecycle scheduler.

Revision ID: 012_add_scheduled_actions
Revises: 011_enhance_audit_logs
Create Date: 2026-04-12

예약된 생명주기 작업 (비식별화, 아카이브, 퍼지, 상태 변경)을 저장하는
scheduled_actions 테이블을 추가한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "012_add_scheduled_actions"
down_revision: Union[str, None] = "011_enhance_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """scheduled_actions 테이블 생성."""
    op.create_table(
        "scheduled_actions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(30),
            nullable=False,
            comment="anonymize / archive / purge / change_status / reminder",
        ),
        sa.Column(
            "target_block_ids",
            JSONB,
            nullable=False,
            comment="대상 블럭 ID 목록",
        ),
        sa.Column(
            "params",
            JSONB,
            nullable=True,
            comment="액션 파라미터",
        ),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="예약 실행 시각",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending / executed / cancelled / failed",
        ),
        sa.Column(
            "result",
            JSONB,
            nullable=True,
            comment="실행 결과",
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "transition_event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("transition_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "policy_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lifecycle_policies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Text,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="실제 실행 시각",
        ),
    )

    # 인덱스 생성
    op.create_index(
        "ix_scheduled_actions_tenant",
        "scheduled_actions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_scheduled_actions_status_scheduled",
        "scheduled_actions",
        ["status", "scheduled_at"],
    )


def downgrade() -> None:
    """scheduled_actions 테이블 삭제."""
    op.drop_index("ix_scheduled_actions_status_scheduled", table_name="scheduled_actions")
    op.drop_index("ix_scheduled_actions_tenant", table_name="scheduled_actions")
    op.drop_table("scheduled_actions")
