"""agents.kind 컬럼 — admin / role 구분 (Locus 어시스턴트 vs 역할 에이전트)

Revision ID: 058
Revises: 057
Create Date: 2026-05-07

목적: tenant 의 *어시스턴트 본인* (admin agent) 과 *사용자가 만든 하부 역할 에이전트*
(role agent) 를 데이터 모델 단에서 구분. admin agent 는 engine 에서 skill state
machine bypass + plan_orchestrator 의 카테고리별 7-tool allowlist 무시. role
agent 는 기존 동작 유지.

변경:
- ``agents.kind`` text NOT NULL DEFAULT 'role' + CHECK in ('admin','role')
- ``ix_agents_tenant_kind`` partial index on (tenant_id, kind) WHERE is_active
- ``ux_agents_tenant_admin`` partial unique index on (tenant_id) WHERE
  kind='admin' AND is_active — tenant 당 admin 1개 강제
- 기존 Locus 어시스턴트 (id 7512bed2-…) → kind='admin'
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "058"
down_revision: Union[str, None] = "057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOCUS_AGENT_ID = "7512bed2-7e9a-4c3a-914e-e3da5cb74ccf"


def upgrade() -> None:
    """agents.kind + 인덱스 + Locus 어시스턴트 backfill."""
    # 1. kind 컬럼 — 기본값 'role'. 기존 row 도 자동 'role' 으로 채워짐.
    op.add_column(
        "agents",
        sa.Column(
            "kind",
            sa.Text,
            nullable=False,
            server_default=sa.text("'role'"),
        ),
    )

    # 2. CHECK constraint — admin/role 만 허용.
    op.create_check_constraint(
        "agents_kind_check",
        "agents",
        "kind IN ('admin', 'role')",
    )

    # 3. tenant + kind partial index — admin 조회 빠르게 + 활성 row 만.
    op.create_index(
        "ix_agents_tenant_kind",
        "agents",
        ["tenant_id", "kind"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # 4. tenant 당 admin 1개 — partial unique index.
    op.create_index(
        "ux_agents_tenant_admin",
        "agents",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'admin' AND is_active = TRUE"),
    )

    # 5. Locus 어시스턴트 backfill — 존재할 때만 update (다른 환경 안전).
    op.execute(
        f"""
        UPDATE agents
           SET kind = 'admin'
         WHERE id = '{_LOCUS_AGENT_ID}'
        """
    )


def downgrade() -> None:
    """kind 컬럼 + 인덱스 + constraint 롤백."""
    op.drop_index("ux_agents_tenant_admin", table_name="agents")
    op.drop_index("ix_agents_tenant_kind", table_name="agents")
    op.drop_constraint("agents_kind_check", "agents", type_="check")
    op.drop_column("agents", "kind")
