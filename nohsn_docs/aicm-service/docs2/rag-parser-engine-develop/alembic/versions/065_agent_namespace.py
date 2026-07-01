"""Phase 1.5E — Agent Namespace + 3중 격리 layer.

Revision ID: 065
Revises: 064
Create Date: 2026-05-07

목적 (Phase 1.5E — agent 전용 repo namespace + cross-industry leak 차단):
- ``agents.repo_namespace text NULL`` — agent 가 소유한 repo namespace 라벨
  (예: baemin / musinsa / samchully). admin kind 는 NULL — 모든 repo 접근.
- ``repositories.agent_id uuid NULL FK agents(id) ON DELETE SET NULL`` —
  이 repo 의 *소유 agent*. NULL = 공용 repo (admin 만 접근). agent 삭제 시
  자동으로 공용으로 demote (자료 보존).
- ``repositories.namespace text NULL`` — agents.repo_namespace 와 sync.
  검색 결과 grouping / UI 표기 용.
- 인덱스 2개 — agent_id partial index + (tenant_id, agent_id) 복합 index.

설계 원칙 (spec §1):
- 회귀 0 — 기존 repo 모두 agent_id NULL (공용) backfill. 5 role agent 의
  5 repo 만 즉시 격리. admin agent 는 자동 제외 (kind = 'role' WHERE 절).
- 하드코딩 X — repo_namespace 는 agent 가 정의하는 자유 문자열.
  backfill 룰은 split_part(name, '_', 1) — 5 role agent (baemin_consult /
  homeshop_voc / kb_soldier_savings / musinsa_consult / samchully_voc) 가
  깨끗이 매칭. 향후 추가 agent 도 동일 패턴 가정.
- DetachedInstanceError 패턴 주의 — 컬럼만 추가, relationship 변경 X.

Backfill 검증 (upgrade 후 실행):
    SELECT a.name, a.repo_namespace, r.name AS repo_name, r.namespace, r.agent_id
      FROM agents a
      JOIN repositories r ON r.id = ANY(a.primary_repo_ids)
     WHERE a.kind = 'role';
    -- 5 row 기대, 모두 r.agent_id = a.id, r.namespace = a.repo_namespace.

회귀 가드:
- 기존 web /c chat (admin 또는 agent_context 미주입) → 모든 repo 접근 그대로.
- 새 컬럼은 모두 nullable + ON DELETE SET NULL — agent 삭제 시에도 안전.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Phase 1.5E — agents.repo_namespace + repositories.(agent_id, namespace) + index 2."""

    # =====================================================================
    # 1. agents.repo_namespace — agent 의 namespace 라벨.
    # =====================================================================
    op.add_column(
        "agents",
        sa.Column(
            "repo_namespace",
            sa.Text,
            nullable=True,
            comment=(
                "Agent 의 repo namespace 라벨 (예: baemin, musinsa). "
                "admin kind 는 NULL — 모든 repo 접근. role + NULL 은 공용 "
                "repo 만 접근 (격리 약함, 권고 X). 자유 문자열 — tenant 안 "
                "unique 하게 운영자 책임. Marketplace import 시 customer "
                "tenant 안 prefix 적용 권고."
            ),
        ),
    )

    # =====================================================================
    # 2. repositories.agent_id + namespace — repo 의 소유 agent + 라벨 sync.
    # =====================================================================
    op.add_column(
        "repositories",
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "이 repo 의 소유 agent (Phase 1.5E). NULL = 공용 repo "
                "(admin 만 접근). 동일 tenant 안 role agent 는 자기 agent_id "
                "+ NULL 만 접근. ON DELETE SET NULL — agent 삭제 시 자료 보존."
            ),
        ),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "namespace",
            sa.Text,
            nullable=True,
            comment=(
                "agents.repo_namespace 와 sync. 검색 결과 grouping / UI 표기 용."
            ),
        ),
    )

    # =====================================================================
    # 3. 인덱스 — partial (agent_id) + 복합 (tenant_id, agent_id).
    # =====================================================================
    # repositories 는 ``is_active`` boolean 만 — soft-delete 컬럼 (deleted_at) 없음.
    # active 인 row 만 인덱스 cover.
    op.create_index(
        "ix_repositories_agent_id_active",
        "repositories",
        ["agent_id"],
        postgresql_where=sa.text("is_active = true AND agent_id IS NOT NULL"),
    )
    op.create_index(
        "ix_repositories_tenant_agent_active",
        "repositories",
        ["tenant_id", "agent_id"],
        postgresql_where=sa.text("is_active = true"),
    )

    # =====================================================================
    # 4. Backfill — 5 role agent (kind='role') 의 repo_namespace 자동 채움.
    #    name 의 첫 단어 (underscore 분리) 룰 — baemin_consult → 'baemin'.
    # =====================================================================
    op.execute(
        """
        UPDATE agents a
           SET repo_namespace = split_part(a.name, '_', 1)
         WHERE a.kind = 'role'
           AND a.repo_namespace IS NULL
           AND COALESCE(array_length(a.primary_repo_ids, 1), 0) >= 1;
        """
    )

    # =====================================================================
    # 5. Backfill — primary_repo_ids[1] 의 repo 에 agent_id + namespace 부여.
    #    role kind 만 — admin 은 자동 제외 → namespace NULL → Layer 2 bypass.
    # =====================================================================
    op.execute(
        """
        UPDATE repositories r
           SET agent_id = a.id,
               namespace = a.repo_namespace
          FROM agents a
         WHERE a.kind = 'role'
           AND a.repo_namespace IS NOT NULL
           AND COALESCE(array_length(a.primary_repo_ids, 1), 0) >= 1
           AND r.id = a.primary_repo_ids[1]
           AND r.tenant_id = a.tenant_id
           AND r.is_active = true
           AND r.agent_id IS NULL;
        """
    )


def downgrade() -> None:
    """역순 — index 2 → 컬럼 3."""
    op.drop_index(
        "ix_repositories_tenant_agent_active",
        table_name="repositories",
    )
    op.drop_index(
        "ix_repositories_agent_id_active",
        table_name="repositories",
    )
    op.drop_column("repositories", "namespace")
    op.drop_column("repositories", "agent_id")
    op.drop_column("agents", "repo_namespace")
