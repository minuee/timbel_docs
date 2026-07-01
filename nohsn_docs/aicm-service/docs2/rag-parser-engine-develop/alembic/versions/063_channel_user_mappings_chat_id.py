"""channel_user_mappings — chat_id binding key + group_enabled flag (Task 8f)

Revision ID: 063
Revises: 062
Create Date: 2026-05-07

목적 (Phase 1.5A Task 8f — chat_id binding 결함 fix):
- 기존 UNIQUE (channel_id, external_user_id) — 동일 user 가 여러 group 에서
  메시지 보내도 단일 row 로 합쳐져 group 별 metadata / activation 분리 불가.
- group/supergroup/channel 에서 chat.id != from.id 일 때 mapping key 가
  user.id 만으로는 부족.
- 응답 송출 대상 (chat_id) 와 발신자 (external_user_id) 를 분리해
  (channel_id, chat_id, external_user_id) 합성 unique 로 확장.
- ``group_enabled`` flag — group/supergroup/channel 은 default deny,
  admin 이 명시적으로 true 토글한 경우만 응답 (멤버 전체에 자동 응답 폭주 차단).

스키마 변경:
1. ``chat_id TEXT`` 컬럼 추가 (NOT NULL, 기존 row 는 external_user_id 로 backfill).
2. ``group_enabled BOOLEAN NOT NULL DEFAULT false`` 컬럼 추가.
3. 기존 UNIQUE ``channel_user_mappings_uq (channel_id, external_user_id)`` DROP.
4. 새 UNIQUE ``channel_user_mappings_uq (channel_id, chat_id, external_user_id)`` CREATE.

Backfill 안정성:
- 기존 row 는 모두 private chat 1:1 매핑이라는 가정 (Telegram 한정으로는
  parse_inbound 가 chat.id == from.id 인 케이스만 mapping 생성했음).
- chat_id = external_user_id 로 동일 값 채우면 (channel, chat, external) 합성
  unique 충돌 없음.
- group_enabled default false — 기존 1:1 매핑은 chat_type=private 과 동등하게
  취급되어 router 의 ``is_group_chat`` 분기가 False → group_enabled 미사용.

회귀 위험:
- ORM 모델은 ``chat_id`` 와 ``group_enabled`` 컬럼이 추가되도록 갱신 (이번 커밋).
- pre-063 환경의 ORM 코드 → 신컬럼 SET 안 함. 새 코드는 ``hasattr`` 가드로
  pre-063 환경에서도 동작 (graceful degrade — UNIQUE 위반 시 fallback).

downgrade:
- 새 UNIQUE 제거 → 옛 UNIQUE (channel_id, external_user_id) 복원.
- 기존 row 가 group chat 일 경우 옛 UNIQUE 위반 가능 — downgrade 전에
  group chat row (chat_id != external_user_id) 를 운영자가 수동 정리해야 함.
- ``chat_id`` / ``group_enabled`` 컬럼 DROP.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """chat_id + group_enabled 컬럼 추가 + 합성 UNIQUE 재구성."""
    # 1) chat_id 컬럼 — 우선 nullable 로 추가, backfill 후 NOT NULL.
    op.add_column(
        "channel_user_mappings",
        sa.Column("chat_id", sa.Text, nullable=True),
    )
    # 2) backfill — 기존 row 는 모두 private chat (chat_id = external_user_id).
    op.execute(
        "UPDATE channel_user_mappings SET chat_id = external_user_id "
        "WHERE chat_id IS NULL"
    )
    # 3) NOT NULL constraint 적용.
    op.alter_column(
        "channel_user_mappings",
        "chat_id",
        existing_type=sa.Text(),
        nullable=False,
    )

    # 4) group_enabled 컬럼 — group/supergroup/channel default deny.
    op.add_column(
        "channel_user_mappings",
        sa.Column(
            "group_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # 5) 기존 UNIQUE 제거 + 새 UNIQUE 생성.
    op.drop_constraint(
        "channel_user_mappings_uq",
        "channel_user_mappings",
        type_="unique",
    )
    op.create_unique_constraint(
        "channel_user_mappings_uq",
        "channel_user_mappings",
        ["channel_id", "chat_id", "external_user_id"],
    )


def downgrade() -> None:
    """downgrade — group chat row 가 남아 있으면 UNIQUE 위반 가능 (수동 정리 필요)."""
    op.drop_constraint(
        "channel_user_mappings_uq",
        "channel_user_mappings",
        type_="unique",
    )
    op.create_unique_constraint(
        "channel_user_mappings_uq",
        "channel_user_mappings",
        ["channel_id", "external_user_id"],
    )
    op.drop_column("channel_user_mappings", "group_enabled")
    op.drop_column("channel_user_mappings", "chat_id")
