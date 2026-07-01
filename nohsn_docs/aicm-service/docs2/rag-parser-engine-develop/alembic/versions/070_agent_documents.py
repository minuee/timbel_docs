"""agent_documents — agent x document 매핑 테이블 (옵션 Y v2).

Revision ID: 070
Revises: 069
Create Date: 2026-05-07

목적 (사용자 명시 옵션 Y, 2026-05-07):
- agent 별 SOP/지식자료 mode 를 *문서 단위* 로 전환.
- 라이브러리는 전역 view (태그 제거), agent 문서함은 그 agent 의 매핑만 표시.
- (M-A) 기존 문서에서 link picker (다중 선택), (M-B) 로컬 업로드 자동 link 모두 지원.

설계 (GPT-5 P0/P1 반영):
- ``tenant_id`` 컬럼 + INSERT/UPDATE 트리거 — agent.tenant_id == document.tenant_id
  강제. cross-tenant 누수 0.
- ``UNIQUE(agent_id, document_id)`` — 동일 agent 가 같은 doc 을 2 mode 로
  등록 불가 (mode toggle 만).
- ``mode`` CHECK = sop / kms 만 허용.
- ``source`` CHECK = shared / uploaded.
- 인덱스 3개: (agent_id, mode), (document_id), (tenant_id, agent_id).

회귀 가드:
- 빈 테이블 시작 → retrieval (RAG) 은 agent_documents 빈 → 옛 repo_ids fallback.
- backfill (Phase 5) 후 union 전략으로 회귀 0.
- documents.is_sop 필드 유지 (옛 데이터 호환).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION enforce_agent_documents_tenant() RETURNS TRIGGER AS $$
DECLARE
  agent_tenant UUID;
  doc_tenant UUID;
BEGIN
  SELECT tenant_id INTO agent_tenant FROM agents WHERE id = NEW.agent_id;
  SELECT tenant_id INTO doc_tenant FROM documents WHERE id = NEW.document_id;
  IF agent_tenant IS NULL THEN
    RAISE EXCEPTION 'agent_documents: agent % not found', NEW.agent_id;
  END IF;
  IF doc_tenant IS NULL THEN
    RAISE EXCEPTION 'agent_documents: document % not found', NEW.document_id;
  END IF;
  IF NEW.tenant_id != agent_tenant THEN
    RAISE EXCEPTION 'agent_documents.tenant_id % mismatch with agent.tenant_id %',
      NEW.tenant_id, agent_tenant;
  END IF;
  IF NEW.tenant_id != doc_tenant THEN
    RAISE EXCEPTION 'agent_documents.tenant_id % mismatch with document.tenant_id % (cross-tenant blocked)',
      NEW.tenant_id, doc_tenant;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    """agent_documents 테이블 + 트리거 + 인덱스 생성."""

    op.create_table(
        "agent_documents",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column(
            "source",
            sa.Text,
            nullable=False,
            server_default=sa.text("'shared'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "agent_id", "document_id", name="uq_agent_documents_agent_doc"
        ),
        sa.CheckConstraint(
            "mode IN ('sop','kms')", name="ck_agent_documents_mode"
        ),
        sa.CheckConstraint(
            "source IN ('shared','uploaded')",
            name="ck_agent_documents_source",
        ),
    )

    op.create_index(
        "ix_agent_documents_agent_mode",
        "agent_documents",
        ["agent_id", "mode"],
    )
    op.create_index(
        "ix_agent_documents_document",
        "agent_documents",
        ["document_id"],
    )
    op.create_index(
        "ix_agent_documents_tenant_agent",
        "agent_documents",
        ["tenant_id", "agent_id"],
    )

    # GPT-5 P0 — tenant 누수 방어 트리거.
    op.execute(_TENANT_TRIGGER_SQL)
    op.execute(
        """
        CREATE TRIGGER trg_agent_documents_tenant_check
          BEFORE INSERT OR UPDATE ON agent_documents
          FOR EACH ROW EXECUTE FUNCTION enforce_agent_documents_tenant();
        """
    )


def downgrade() -> None:
    """역순."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_agent_documents_tenant_check ON agent_documents;"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_agent_documents_tenant();")
    op.drop_index("ix_agent_documents_tenant_agent", table_name="agent_documents")
    op.drop_index("ix_agent_documents_document", table_name="agent_documents")
    op.drop_index("ix_agent_documents_agent_mode", table_name="agent_documents")
    op.drop_table("agent_documents")
