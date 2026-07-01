"""agents_tool_scope_overrides — agent 별 도구 scope override JSONB (#154 Phase 3).

Revision ID: 075
Revises: 074
Create Date: 2026-05-07

Spec: docs/superpowers/specs/2026-05-07-agent-tool-scope-overrides.md
GPT-5 phase 0: docs/superpowers/specs/2026-05-07-agent-tool-scope-overrides.gpt5-phase0.txt

목적 (사용자 명시 2026-05-07):
- Phase 1 (alembic 072 — schedule.* hardcode 격리) → Phase 2 (#153 — 도구 manifest
  default_scope) 다음 단계. agent 별로 도구 scope 를 *하향* override 가능.
- 승격 금지 정책: SCOPE_RANK = {tenant:4, user:3, agent:2, session:1}.
  default 보다 *낮거나 같은* 등급만 허용 (Pydantic validator 가 강제).

회귀 0:
- ALTER TABLE agents ADD COLUMN tool_scope_overrides JSONB NOT NULL DEFAULT '{}'
- 기존 row 자동 채움 (NOT NULL DEFAULT '{}'::jsonb).
- 본 PR 은 *컬럼 + UI 추가* 까지 — manifest enforcement 는 Phase 4 (#155).
- override 안 한 agent (= default {}) 는 기존 동작 그대로.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "075"
down_revision: Union[str, None] = "074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """agents.tool_scope_overrides JSONB 컬럼 추가."""
    op.add_column(
        "agents",
        sa.Column(
            "tool_scope_overrides",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "tool_scope_overrides")
