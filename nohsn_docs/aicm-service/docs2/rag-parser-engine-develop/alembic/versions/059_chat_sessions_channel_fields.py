"""chat_sessions 채널 필드 — channel_kind / channel_id / external_user_id / agent_id
+ channel_user_mappings.internal_account_id (mapping → account 직접 참조).

Revision ID: 059
Revises: 058
Create Date: 2026-05-07

목적 (spec ``2026-05-07-channel-chat-sync-design.md``):
- 한 admin (예: test1) 이 *어디서 말하든* (웹 /c, 텔레그램, 추후 Slack/LINE 등)
  같은 KMS 코어 + 통합 history 를 가지도록.
- 옵션 B (separate sessions + unified inbox view). 채널별 chat_sessions 행
  분리 (보안 격리 + SOP/persona 분리), 통합 inbox 페이지에서 한 곳에 표시.

변경:
1. ``chat_sessions.channel_kind``  text NOT NULL DEFAULT 'web'
   + CHECK in ('web','telegram','slack','line','kakao','discord','teams',
                'email','sms','rcs','custom')
2. ``chat_sessions.channel_id``    uuid NULL FK agent_channels(id) ON DELETE SET NULL
3. ``chat_sessions.external_user_id`` text NULL  (텔레그램 등 webhook from_user_id)
4. ``chat_sessions.agent_id``      uuid NULL FK agents(id) ON DELETE SET NULL
5. ``ix_chat_sessions_account_channel`` partial index
   on (account_id, channel_kind, created_at DESC) — 채널별 inbox 정렬 빠르게.
6. ``channel_user_mappings.internal_account_id`` uuid NULL FK accounts(id)
   ON DELETE SET NULL — 기존 ``internal_user_id`` (users FK) 와 별도 컬럼.
   webhook routing 이 ``account_id`` 를 직접 참조해 chat_sessions 에
   account 단위로 연결. (accounts 와 users 가 1:1 이 아닌 현 스키마 정합).

회귀 위험 0:
- 기존 chat_sessions row 는 server_default='web' 으로 자동 채워짐.
- INSERT 문 변경 없이도 web /c 경로 동작 그대로.
- channel_user_mappings 는 새 컬럼 추가만, 기존 internal_user_id 보존.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "059"
down_revision: Union[str, None] = "058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ALLOWED_CHANNEL_KINDS = (
    "web",
    "telegram",
    "slack",
    "line",
    "kakao",
    "discord",
    "teams",
    "email",
    "sms",
    "rcs",
    "custom",
)


def upgrade() -> None:
    """chat_sessions 채널 필드 + channel_user_mappings.internal_account_id."""
    # 1. channel_kind — server_default='web' 으로 기존 row 자동 채움.
    op.add_column(
        "chat_sessions",
        sa.Column(
            "channel_kind",
            sa.Text,
            nullable=False,
            server_default=sa.text("'web'"),
        ),
    )
    # CHECK constraint — 허용 kind 만.
    allowed_csv = ", ".join(f"'{k}'" for k in _ALLOWED_CHANNEL_KINDS)
    op.create_check_constraint(
        "chat_sessions_channel_kind_check",
        "chat_sessions",
        f"channel_kind IN ({allowed_csv})",
    )

    # 2. channel_id — webhook 채널 origin (web 은 NULL).
    op.add_column(
        "chat_sessions",
        sa.Column(
            "channel_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("agent_channels.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 3. external_user_id — 텔레그램 user_id 등 webhook 발신자 식별자.
    op.add_column(
        "chat_sessions",
        sa.Column(
            "external_user_id",
            sa.Text,
            nullable=True,
        ),
    )

    # 4. agent_id — 어떤 agent context 로 처리됐는지 attribution.
    op.add_column(
        "chat_sessions",
        sa.Column(
            "agent_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 5. partial index — 활성 (deleted X) 세션 + (account, channel) 별 timeline.
    # ``is_active`` 컬럼은 chat_sessions 에 없음 → updated_at 기준 ordering 으로
    # 일반 index. inbox 가 (account, channel_kind, created_at DESC) 로 조회.
    op.create_index(
        "ix_chat_sessions_account_channel",
        "chat_sessions",
        ["account_id", "channel_kind", sa.text("created_at DESC")],
    )

    # 6. channel_user_mappings.internal_account_id — accounts FK.
    # accounts 와 users 가 1:1 매핑이 아닌 현 스키마에서 webhook routing 이
    # *직접* account 를 참조하기 위한 새 컬럼. 기존 internal_user_id 는 보존
    # (다른 코드 의존성 안전). ON DELETE SET NULL — account 삭제 시 mapping 만
    # guest 로 강등되도록.
    op.add_column(
        "channel_user_mappings",
        sa.Column(
            "internal_account_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """롤백 — 컬럼/인덱스/제약 모두 제거."""
    op.drop_column("channel_user_mappings", "internal_account_id")
    op.drop_index("ix_chat_sessions_account_channel", table_name="chat_sessions")
    op.drop_column("chat_sessions", "agent_id")
    op.drop_column("chat_sessions", "external_user_id")
    op.drop_column("chat_sessions", "channel_id")
    op.drop_constraint(
        "chat_sessions_channel_kind_check", "chat_sessions", type_="check"
    )
    op.drop_column("chat_sessions", "channel_kind")
