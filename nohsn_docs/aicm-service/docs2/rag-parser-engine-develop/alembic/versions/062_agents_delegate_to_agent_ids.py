"""agents.delegate_to_agent_ids — multi-agent 위임 (Phase 1.5B-γ)

Revision ID: 062
Revises: 061
Create Date: 2026-05-07

목적 (Phase 1.5B-γ — Multi-agent 데이터 모델):
- admin agent 가 사용자 의도에 따라 호출 가능한 *하부 role agent* 목록을
  보관. agent A 의 ``delegate_to_agent_ids`` 에 들어 있는 agent B 만
  A 가 위임 호출 가능.
- admin kind 인 경우 default 가 "모든 role agent 자동 inject" 이지만 명시적
  delegation 지정 시 그것만 사용 (override).

설계:
- 컬럼: ``delegate_to_agent_ids uuid[] NOT NULL DEFAULT '{}'``.
- CHECK: ``id != ALL(delegate_to_agent_ids)`` — 자기 자신 위임 금지.
- index: ``ix_agents_delegate_to_agent_ids`` GIN — 어느 agent 가 특정
  agent 를 위임하고 있는지 역검색 빠르게.
- 기존 row 는 server_default '{}' 로 자동 backfill (회귀 0).

회귀 위험:
- delegate_to_agent_ids 가 빈 배열인 한 기존 동작 그대로. router/engine 도
  None/빈 배열일 때 skip.

순환 위임 (A → B → A) 검사는 application layer (agents_v1.py) 에서
DFS 로 수행 — DB CHECK 만으로 표현 불가. max_depth=3 도 동일.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """delegate_to_agent_ids 컬럼 + 자기 위임 CHECK + GIN 인덱스."""
    # 1. 컬럼 추가 — 모든 기존 row 가 server_default '{}' 로 백필.
    op.add_column(
        "agents",
        sa.Column(
            "delegate_to_agent_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )

    # 2. 자기 자신 위임 금지 CHECK.
    op.create_check_constraint(
        "agents_no_self_delegation",
        "agents",
        "NOT (id = ANY(delegate_to_agent_ids))",
    )

    # 3. GIN 인덱스 — '어느 agent 가 X 를 위임하는가' 역검색용.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agents_delegate_to_agent_ids "
        "ON agents USING GIN (delegate_to_agent_ids)"
    )


def downgrade() -> None:
    """역순으로 인덱스 / 제약 / 컬럼 제거."""
    op.execute("DROP INDEX IF EXISTS ix_agents_delegate_to_agent_ids")
    op.drop_constraint("agents_no_self_delegation", "agents", type_="check")
    op.drop_column("agents", "delegate_to_agent_ids")
