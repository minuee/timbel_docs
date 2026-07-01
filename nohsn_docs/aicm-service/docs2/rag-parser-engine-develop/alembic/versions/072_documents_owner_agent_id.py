"""documents.owner_agent_id — agent 단위 write 격리 (Phase 1 — schedule).

Revision ID: 072
Revises: 071
Create Date: 2026-05-07

목적 (사용자 명시 2026-05-07):
- 일정은 agent 별 *전용 영역* — 다른 agent 의 일정에 섞이지 않음.
- write 도구는 4 단계 scope (tenant > user > agent > session) 가 필요.
  read-only 는 ``knowledge_isolation`` 으로 충분.
- Phase 1 = ``schedule.*`` 만 ``owner_agent_id`` 격리 hardcode.
- Phase 2 (도구 manifest default_scope), Phase 3 (agents.tool_scope_overrides),
  Phase 4 (resource-level inheritance) 는 spec 만 작성, 별도 PR.

설계 (GPT-5 검증 2026-05-07 반영):
- 별도 ``schedules`` 테이블 *생성 안 함* — schedule 데이터는 이미
  ``documents`` 테이블에 ``document_type='agent_schedule'`` 로 저장됨 (52 rows).
- ``documents.owner_agent_id`` 컬럼 추가 — 모든 write doctype (agent_schedule,
  agent_memo, agent_expense 등) 이 같은 컬럼으로 점진적 확산 가능.
- FK ``ON DELETE SET NULL`` — agent 삭제 시 row 보존, NULL 버킷은 list 에서
  default-deny (admin 만 include_null=true 로 조회).
- Partial index ``ix_documents_owner_agent_partial`` — owner_agent_id 단독 lookup.
- Composite index ``ix_documents_owner_agent_doctype`` — doctype + tenant +
  owner + status 조합 쿼리 (schedule_store.list_all 패턴).
- NOT NULL 강제는 *다음 PR* — 기존 449 row (agent_schedule 외 + 다른 doctype)
  영향 회귀 0 보장. Phase 1 backfill 은 schedule 만.

회귀 0:
- 기존 schedules row (52건) → backfill 스크립트 실행 시 admin Locus 의
  agent_id 로 채움 (tenant 별 1:1 mapping).
- 다른 agent_* doctype (memo/expense/stock_watch) 은 Phase 2 까지 NULL 유지 —
  schedule_store 만 owner_agent_id 인지/필터.
- agent_data 외 일반 documents (KMS 본문, RAG 소스) 는 NULL 유지 — 영향 0.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "072"
down_revision: Union[str, None] = "071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. documents.owner_agent_id (NULLABLE — 기존 row 보존).
    op.add_column(
        "documents",
        sa.Column(
            "owner_agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_documents_owner_agent",
        "documents",
        "agents",
        ["owner_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # 2. partial index — owner_agent_id 단독 lookup (agent 삭제 cascade 시).
    op.create_index(
        "ix_documents_owner_agent_partial",
        "documents",
        ["owner_agent_id"],
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )
    # 3. composite index — schedule_store.list_all 패턴
    #    (doctype + tenant + owner + status).
    op.create_index(
        "ix_documents_owner_agent_doctype",
        "documents",
        ["document_type_id", "tenant_id", "owner_agent_id", "status"],
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_documents_owner_agent_doctype", table_name="documents")
    op.drop_index("ix_documents_owner_agent_partial", table_name="documents")
    op.drop_constraint("fk_documents_owner_agent", "documents", type_="foreignkey")
    op.drop_column("documents", "owner_agent_id")
