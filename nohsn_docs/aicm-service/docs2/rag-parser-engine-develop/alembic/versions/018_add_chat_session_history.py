"""채팅 세션 히스토리 — title, is_active 컬럼 추가.

Revision ID: 018_add_chat_session_history
Revises: 017_add_chat_sessions
Create Date: 2026-04-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_add_chat_session_history"
down_revision: Union[str, None] = "017_add_chat_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("title", sa.String(200), server_default="새 대화", nullable=False),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "is_active")
    op.drop_column("chat_sessions", "title")
