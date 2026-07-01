"""channel_inbound_dedup — webhook update_id 멱등성 보장 테이블

Revision ID: 060
Revises: 059
Create Date: 2026-05-07

목적 (Webhook 보안 보강 — Telegram deep dive §11):
- Telegram 은 webhook 응답이 2xx 가 아니면 동일 ``update_id`` 로 재시도한다.
- 네트워크 단절 / 백엔드 5xx 시 동일 update 가 N 번 들어와 중복 응답 발송.
- 채널별 (channel_id, idempotency_key) 단위로 24h dedup window 유지.

스키마 결정:
- ``channel_id`` (FK agent_channels) + ``idempotency_key`` (text) 합성 unique.
- ``idempotency_key`` 는 채널별 의미가 다르다:
  - Telegram: ``str(update_id)``
  - Slack (향후): ``event_id``
  - LINE (향후): ``webhookEventId``
  - KakaoWork (향후): ``message.id``
- ``processed_at`` (timestamptz NOT NULL DEFAULT now()) — TTL 정리 기준.
- ``response_summary`` jsonb NULL — 중복 hit 시 디버깅용 (재발송 X).

TTL/정리:
- ON CONFLICT DO NOTHING 으로 INSERT — 새 row 면 처리, 이미 있으면 skip.
- 24h 이상 된 row 는 별도 cleanup cron (또는 admin) 이 DELETE.

회귀 위험 0:
- 새 테이블만 추가. 기존 row/쿼리 영향 X.
- 미적용 환경에서도 webhook 동작은 그대로 (dedup 코드는 테이블 부재 시 best-effort).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """channel_inbound_dedup 테이블 생성."""
    op.create_table(
        "channel_inbound_dedup",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "channel_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("agent_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("response_summary", JSONB, nullable=True),
    )

    # (channel_id, idempotency_key) — 채널 안에서 update_id 유일.
    op.create_unique_constraint(
        "channel_inbound_dedup_uq",
        "channel_inbound_dedup",
        ["channel_id", "idempotency_key"],
    )

    # processed_at — TTL cleanup cron 빠르게.
    op.create_index(
        "ix_channel_inbound_dedup_processed_at",
        "channel_inbound_dedup",
        ["processed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_inbound_dedup_processed_at",
        table_name="channel_inbound_dedup",
    )
    op.drop_constraint(
        "channel_inbound_dedup_uq",
        "channel_inbound_dedup",
        type_="unique",
    )
    op.drop_table("channel_inbound_dedup")
