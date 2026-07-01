"""Phase 2 T2.1 — Alembic multi-branch transition: agent branch root (no-op).

Revision ID: agent_root
Revises: 081
Create Date: 2026-05-19

목적 (spec §7 Alembic multi-branch 전략):
- Agent 도메인 (agents, agent_channels, channel_inbound_dedup,
  channel_user_mappings, agent_documents, custom_tools, lifecycle_feedback,
  scheduled_actions) 의 *branch label* 부여.
- ``depends_on=("shared",)`` 로 shared 의 tenants/users 등 FK 가 먼저 적용된
  환경에서만 작동을 보장.
- 향후 Agent 전용 migration 은 본 revision 의 자손으로 추가.

본 revision 자체는 no-op — 기존 단일 history 가 이미 agent table 을 생성했기
때문.

실 DB 미적용 — staging 검증 후 적용.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "agent_root"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = ("agent",)
depends_on: Union[str, Sequence[str], None] = ("shared",)


def upgrade() -> None:
    """No-op — branch label 부여만 수행."""
    pass


def downgrade() -> None:
    """No-op — branch label 해제만 수행."""
    pass
