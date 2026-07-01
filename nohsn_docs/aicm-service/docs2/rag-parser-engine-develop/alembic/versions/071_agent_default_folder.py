"""agent default folder — library_folders.owner_agent_id + agents.default_folder_id (옵션 Y v2).

Revision ID: 071
Revises: 070
Create Date: 2026-05-07

목적 (사용자 명시 옵션 Y v2):
- 작성된 문서 / 업로드된 문서 → 각 agent 의 *전용 하부 폴더* 자동 저장.
- 라이브러리에서 그 폴더가 *agent 의 폴더* 로 분류 (다른 agent / 사용자도
  picker 로 reuse 가능).

설계 (GPT-5 P1 반영):
- ``library_folders.owner_agent_id`` — agent 자동 폴더 식별.
- ``UNIQUE(owner_agent_id) WHERE NOT NULL`` — 한 agent 가 default folder 2개 못
  가짐 (race 차단).
- ``agents.default_folder_id`` — agent 의 default 저장 폴더 lookup 가속.
- FK ``ON DELETE SET NULL`` — 폴더 삭제 시 agent 살아있고 다음 업로드 시 자동 재생성.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "071"
down_revision: Union[str, None] = "070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. library_folders.owner_agent_id
    op.add_column(
        "library_folders",
        sa.Column(
            "owner_agent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_library_folders_owner_agent",
        "library_folders",
        ["owner_agent_id"],
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )
    # GPT-5 P1 — 한 agent 가 default folder 2개 갖지 못하게.
    op.create_index(
        "uq_library_folders_owner_agent",
        "library_folders",
        ["owner_agent_id"],
        unique=True,
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_library_folders_owner_agent",
        "library_folders",
        "agents",
        ["owner_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. agents.default_folder_id
    op.add_column(
        "agents",
        sa.Column(
            "default_folder_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agents_default_folder",
        "agents",
        "library_folders",
        ["default_folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_default_folder", "agents", type_="foreignkey")
    op.drop_column("agents", "default_folder_id")
    op.drop_constraint(
        "fk_library_folders_owner_agent", "library_folders", type_="foreignkey"
    )
    op.drop_index("uq_library_folders_owner_agent", table_name="library_folders")
    op.drop_index("ix_library_folders_owner_agent", table_name="library_folders")
    op.drop_column("library_folders", "owner_agent_id")
