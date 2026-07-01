"""tenants.feature_flags JSONB — runtime feature flag toggle (Phase 1).

Revision ID: 073
Revises: 072
Create Date: 2026-05-07

Spec: docs/superpowers/specs/2026-05-07-feature-flags-runtime-toggle.md

목적 (사용자 명시 2026-05-07):
- env 변수 `FEATURE_SOP_RAG` 는 컨테이너 restart 가 필요 — 운영 중 즉시 토글 불가.
- DB 단위 영속 + admin UI 클릭으로 실시간 토글 가능하게.

설계 (GPT-5 phase 0 검증 반영):
- 별도 테이블 X — tenants 행 단위 read 1 회로 모든 flag 가져오게 JSONB 컬럼 추가.
- audit 은 audit_logs 활용 (event_kind='feature_flag_update', old_value/new_value).
- env 변수는 kill-switch 우선 — DB 보다 위.
- 기본값 '{}' — 51 tenant 모두 default 동일 → 회귀 0.
- NULL 금지 — 항상 dict (jsonb_set 원자 부분 업데이트 안전).

회귀 0:
- env unset + DB 빈 값 = 기존 동작 (default false).
- env=true|false = 강제 (UI 토글 무시) — production kill-switch 보존.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "073"
down_revision: Union[str, None] = "072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # tenants.feature_flags JSONB DEFAULT '{}' — runtime 토글 영속.
    op.add_column(
        "tenants",
        sa.Column(
            "feature_flags",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "feature_flags")
