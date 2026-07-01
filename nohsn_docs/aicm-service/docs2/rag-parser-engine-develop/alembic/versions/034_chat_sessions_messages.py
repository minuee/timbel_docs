"""chat_sessions + chat_messages — frontend-v2 채팅 화면 세션/메시지 영구화.

Revision ID: 034
Revises: 033
Create Date: 2026-04-26

Phase P1.2 (KMS-Plus). frontend-v2/ChatEngine 가 호출하는
``/api/v1/chat/sessions/*`` 패밀리의 저장소.

설계:
- chat_sessions: account_id + tenant_id scoped. 마지막 활동 시각 기준 정렬.
- chat_messages: session FK CASCADE. role(user/assistant), content, intent,
  cards JSONB. 시각순 정렬용 created_at + 일련번호.
- account/tenant 별 부분 인덱스로 latest/history 빠르게 조회.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_chat_sessions_account_tenant_updated",
        "chat_sessions",
        ["account_id", "tenant_id", sa.text("updated_at DESC")],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("intent", sa.String(64)),
        sa.Column("cards", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_account_tenant_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")
