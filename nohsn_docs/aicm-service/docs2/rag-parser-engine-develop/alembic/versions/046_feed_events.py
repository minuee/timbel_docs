"""feed_events 테이블 — KMS-Plus P0.2 backend wrapper layer.

Revision ID: 046
Revises: 045
Create Date: 2026-04-28

배경
----
frontend-v3 UX overhaul (PR P3) 의 FeedPage 가 사용할 영속 이벤트 테이블.
account_id + tenant_id scope 의 이벤트(아침 브리핑/시스템 알림/cron 결과 등)를
저장. read_at 으로 읽음 상태 추적, produced_at 기반 cursor pagination.

설계
----
- ``id``                UUID PK
- ``account_id``        UUID FK accounts (CASCADE) — 계정 scope
- ``tenant_id``         UUID FK tenants (CASCADE) — tenant scope (개인/회사 분리)
- ``kind``              text — 이벤트 종류 (자유 식별자, hardcode enum X)
- ``title`` / ``body``  text — 표시 본문
- ``body_html``         text NULL — rich body (markdown 렌더 결과 캐시 등)
- ``pills``             JSONB default '[]' — 카드 상단 라벨/배지 리스트
- ``read_at``           timestamptz NULL — 읽음 처리 시각
- ``produced_at``       timestamptz NOT NULL default now() — 정렬 키
- ``source``            JSONB default '{}' — 출처 메타 (cron name, ref id 등)

idempotent — 040 패턴 따라 재실행 안전.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "feed_events" in inspector.get_table_names():
        return
    op.create_table(
        "feed_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "pills",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "produced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "source",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_feed_events_account_produced",
        "feed_events",
        ["account_id", "produced_at"],
    )
    op.create_index(
        "ix_feed_events_tenant_produced",
        "feed_events",
        ["tenant_id", "produced_at"],
    )
    # partial index — 읽지 않은 이벤트만 대상. unread badge count + 미읽음 목록
    # 쿼리 최적화 (전체 row 의 일부만 인덱싱).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_feed_events_account_unread "
        "ON feed_events (account_id) WHERE read_at IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "feed_events" not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_feed_events_account_unread")
    op.drop_index("ix_feed_events_tenant_produced", table_name="feed_events")
    op.drop_index("ix_feed_events_account_produced", table_name="feed_events")
    op.drop_table("feed_events")
