"""agents.web_search_mode — 4-mode 웹검색 enum + admin Locus default 'separate' 시드.

Revision ID: 069
Revises: 068
Create Date: 2026-05-07

목적 (Plan A v3, 2026-05-07 사용자 명시):
- ``agents.web_search_mode`` (enum 4 값: off / separate / blended / web_only)
  컬럼 추가. default = ``'off'`` (격리 우선).
- 본 마이그레이션 안에서 admin agent 만 ``'separate'`` 로 시드 (사용자 명시
  v3, 2026-05-07): "지식 + 웹 같이 검색, 따로 랭크, 구분해서 답변".

설계 원칙:
- server_default = 'off' — 기존 row 가 NULL → 'off' 자동 채움. 회귀 0.
- CHECK constraint — DB 레벨 enum 강제 (TEXT enum 변형 케이스 차단).
- 5 role agent (baemin / homeshop / kbsoldier / musinsa / samchully) 는 'off'
  로 격리 — 사용자 데이터 외부 유출 방지 default.
- admin Locus 만 'separate' — 자기 KMS 가 작아서 외부 보강 필요 + 사용자가 자기
  비서로 쓰기 때문에 외부 검색 응답 가치 큼.

회귀 가드:
- AgentContext / engine / grounding 이 web_search_mode 미지원 시점에는 컬럼만
  존재 (코드는 'off' 로 동작). v3 의 (5) retrieval 4 모드 분기 commit 후 활성.
- partial unique 인덱스/외래키 영향 0.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 허용 mode 값 — DB 레벨 CHECK constraint.
ALLOWED_MODES = ("off", "separate", "blended", "web_only")


def upgrade() -> None:
    """agents.web_search_mode 추가 + admin Locus 'separate' 시드."""

    # 1. 컬럼 추가 — server_default 'off' 로 기존 row 자동 채움.
    op.add_column(
        "agents",
        sa.Column(
            "web_search_mode",
            sa.Text,
            nullable=False,
            server_default=sa.text("'off'"),
            comment=(
                "웹검색 모드: off / separate / blended / web_only. "
                "off=KMS만, separate=KMS+web 각각 랭크 두 섹션 답변, "
                "blended=KMS+web 통합 ranking 단일 list, web_only=web만. "
                "default='off' (격리 우선)."
            ),
        ),
    )

    # 2. CHECK constraint — 허용 값 외 차단.
    op.create_check_constraint(
        "ck_agents_web_search_mode",
        "agents",
        sa.text(
            "web_search_mode IN ('off','separate','blended','web_only')"
        ),
    )

    # 3. admin Locus 시드 — 사용자 명시 v3 (2026-05-07):
    #    "지식 + 웹 같이 검색, 따로 랭크, 구분해서 답변".
    op.execute(
        sa.text(
            "UPDATE agents SET web_search_mode = 'separate' "
            "WHERE kind = 'admin'"
        )
    )


def downgrade() -> None:
    """역순."""
    op.drop_constraint(
        "ck_agents_web_search_mode", "agents", type_="check"
    )
    op.drop_column("agents", "web_search_mode")
