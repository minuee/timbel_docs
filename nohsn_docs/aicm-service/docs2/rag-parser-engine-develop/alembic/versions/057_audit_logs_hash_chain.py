"""audit_logs hash chain — append-only + sha256 row chain (Phase 1.5A Task 8d)

Revision ID: 057
Revises: 055
Create Date: 2026-05-07

Adds tamper-evident sha256 row hash chain columns + agent-guardrails extension
fields (actor_tier / event_kind / tool_name / args_redacted / outcome).

Note: 056 reserved by Phase 1.5A Task 6 (concurrent task). This migration
extends the existing audit_logs table from 004/011 — does NOT recreate.

DB role permission revoke (UPDATE/DELETE deny on audit_logs) is intentionally
NOT in this migration — that's a deploy/ops concern handled by a separate
post-migration script. App-level append-only is enforced by audit_service
which only INSERTs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """audit_logs 테이블에 hash-chain + guardrail 컬럼 추가."""

    # === legacy NOT NULL 완화 — guardrail 이벤트는 action/resource_type 없을 수 있음 ===
    # 004 마이그레이션이 action / resource_type 을 NOT NULL 로 만들었으나,
    # 신규 event_kind 기반 호출은 그 둘 없이 들어옴.
    op.alter_column("audit_logs", "action", nullable=True)
    op.alter_column("audit_logs", "resource_type", nullable=True)

    # === guardrail extension columns ===
    # actor_tier: guest/verified/admin (Phase 1.5A 인증 분리)
    op.add_column(
        "audit_logs",
        sa.Column("actor_tier", sa.String(32), nullable=True),
    )
    # event_kind: tool_call / agent_create / sop_invoke / etc.
    # (기존 action enum 보다 더 일반화된 이벤트 분류 — text-free)
    op.add_column(
        "audit_logs",
        sa.Column("event_kind", sa.String(64), nullable=True),
    )
    # tool_name: tool_call 일 때 어떤 tool 인지
    op.add_column(
        "audit_logs",
        sa.Column("tool_name", sa.String(256), nullable=True),
    )
    # args_redacted: PII/secret 가린 args dump (canonical JSON 의 일부)
    op.add_column(
        "audit_logs",
        sa.Column("args_redacted", JSONB, nullable=True),
    )
    # outcome: success / failure / denied / etc.
    op.add_column(
        "audit_logs",
        sa.Column("outcome", sa.String(32), nullable=True),
    )

    # === hash chain columns ===
    # prev_row_hash: 같은 tenant 의 직전 row 의 row_hash (NULL = chain head)
    op.add_column(
        "audit_logs",
        sa.Column("prev_row_hash", sa.String(64), nullable=True),
    )
    # row_hash: sha256( (prev_row_hash or '') + canonical_json(payload) )
    # nullable=True 로 추가 (기존 row 는 backfill 안 함). 신규 row 는 service 가 항상 채움.
    op.add_column(
        "audit_logs",
        sa.Column("row_hash", sa.String(64), nullable=True),
    )

    # === indexes ===
    # tenant_id+created_at DESC 는 004 에서 이미 있음 (ix_audit_logs_tenant_created)
    # actor_id+created_at DESC 도 011 에서 user_id 로 있음 (ix_audit_logs_user_created_desc)
    # row_hash unique — chain 검증/디버그용
    op.create_index(
        "ix_audit_logs_row_hash",
        "audit_logs",
        ["row_hash"],
        unique=False,  # backfill 안 한 NULL 허용
    )
    op.create_index(
        "ix_audit_logs_event_kind",
        "audit_logs",
        ["tenant_id", "event_kind", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """guardrail / hash-chain 컬럼 및 인덱스 롤백."""
    op.drop_index("ix_audit_logs_event_kind", table_name="audit_logs")
    op.drop_index("ix_audit_logs_row_hash", table_name="audit_logs")
    op.drop_column("audit_logs", "row_hash")
    op.drop_column("audit_logs", "prev_row_hash")
    op.drop_column("audit_logs", "outcome")
    op.drop_column("audit_logs", "args_redacted")
    op.drop_column("audit_logs", "tool_name")
    op.drop_column("audit_logs", "event_kind")
    op.drop_column("audit_logs", "actor_tier")
    # NOT NULL 복원
    op.alter_column("audit_logs", "resource_type", nullable=False)
    op.alter_column("audit_logs", "action", nullable=False)
