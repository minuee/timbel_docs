"""D70 — agents.oos_keywords jsonb (cross-domain rejection 가드).

Revision ID: 080
Revises: 079
Create Date: 2026-05-11

목적:
- D66 musinsa #258 ("어제 시킨 배달 어디까지 왔어?" → 무신사 배송 절차 답변) 같은
  cross-domain OOS 거절 실패 직접 차단.
- 봇별 *다른 도메인* 키워드를 컬럼에 보관 → engine.py compose path 시작 hook 이
  매칭 시 T2 거절 응답으로 분기 (LLM 호출 스킵).

GPT-5 사전 verdict (2026-05-11): GO_WITH_CHANGES.
- nullable=True + server_default '[]'::jsonb → 메타데이터 변경만, 테이블 리라이트 X.
- 기존 row 는 NULL 로 남으므로 런타임에서 None / [] 모두 안전 처리 (agent_context.from_agent).
- 후속 PR 에서 NOT NULL 전환 가능 (NULL row 모니터링 후).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "oos_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "oos_keywords")
