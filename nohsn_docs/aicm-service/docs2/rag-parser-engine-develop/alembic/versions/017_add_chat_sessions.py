"""채팅 세션 PostgreSQL 백업 테이블.

Revision ID: 017_add_chat_sessions
Revises: 016_add_series_tables
Create Date: 2026-04-14

Redis 세션의 주기적 DB 백업으로 데이터 보호를 강화한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "017_add_chat_sessions"
down_revision: Union[str, None] = "016_add_series_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """chat_sessions 테이블 생성."""

    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "session_data",
            postgresql.JSONB(),
            nullable=False,
            comment="전체 세션 데이터 (messages 포함)",
        ),
        sa.Column(
            "message_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_chat_sessions_user",
        "chat_sessions",
        ["tenant_id", "user_id"],
    )


def downgrade() -> None:
    """chat_sessions 테이블 삭제."""
    op.drop_index("ix_chat_sessions_user", table_name="chat_sessions")
    op.drop_table("chat_sessions")
