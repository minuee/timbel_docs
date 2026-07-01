"""audit_logs.owner_scope + owner_agent_id — agent 단위 감사 row 격리 (D24 §1).

Revision ID: 076
Revises: 075
Create Date: 2026-05-08

목적 (사용자 명시 2026-05-08 / D24):
- Phase 1.5A 057 hash chain 완성 후, agent dispatch audit row 의 *생성 주체* 추적
  + admin / agent / role 격리 메타.
- D23 (#196) 의 agent_* doctype 격리 완료 후 audit_logs 영역 마무리.

설계 (GPT-5 phase 0 GO_WITH_CHANGES 반영):
- ``owner_scope`` (32) — 'admin' | 'agent' | 'role' | NULL (legacy pre-D24).
- ``owner_agent_id`` UUID — agent 가 produce 한 audit row 의 source agent.
  FK ``agents.id`` ``ON DELETE SET NULL`` (D23 패턴 일관성).
- partial index ``ix_audit_logs_owner_agent_partial`` —
  ``owner_agent_id IS NOT NULL`` 단독 lookup.
- composite index ``ix_audit_logs_owner_scope_tenant`` —
  ``(tenant_id, owner_scope, created_at DESC)`` filtered list 패턴.
- hash chain payload (_build_payload) 변경 *없음* — 신규 컬럼은 hash 입력에서
  제외 (legacy row 와 hash 호환 유지).

회귀 0:
- 두 컬럼 모두 NULLABLE — 기존 audit_logs row (Phase 1.5A 의 hash chain row 포함)
  영향 0. 기존 verify_chain 그대로 통과.
- INSERT 시 owner_scope/owner_agent_id 미전달 → NULL 저장.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "076"
down_revision: Union[str, None] = "075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 1. owner_scope (32) — 'admin' | 'agent' | 'role' | NULL ===
    op.add_column(
        "audit_logs",
        sa.Column("owner_scope", sa.String(32), nullable=True),
    )

    # === 2. owner_agent_id UUID FK ON DELETE SET NULL ===
    op.add_column(
        "audit_logs",
        sa.Column(
            "owner_agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_audit_logs_owner_agent",
        "audit_logs",
        "agents",
        ["owner_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # === 3. partial index — owner_agent_id 단독 lookup ===
    op.create_index(
        "ix_audit_logs_owner_agent_partial",
        "audit_logs",
        ["owner_agent_id"],
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )

    # === 4. composite index — (tenant + scope + recency) filtered list ===
    op.create_index(
        "ix_audit_logs_owner_scope_tenant",
        "audit_logs",
        ["tenant_id", "owner_scope", sa.text("created_at DESC")],
        postgresql_where=sa.text("owner_scope IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_owner_scope_tenant", table_name="audit_logs")
    op.drop_index("ix_audit_logs_owner_agent_partial", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_owner_agent", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "owner_agent_id")
    op.drop_column("audit_logs", "owner_scope")
