"""chat_messages.structured_blocks JSONB — KMS-Plus P0.2.

Revision ID: 050
Revises: 049
Create Date: 2026-04-28

배경
----
PR P5 (Context Panel · Structured Blocks) 가 사용할 컬럼. SSE 스트리밍 중
``event: structured_block`` 으로 전달된 payload 들을 finally 시점에 한 번에
JSONB 로 영속화 → 새로고침/세션 재진입 시 동일하게 Context Panel 복원.

설계
----
- 040 (trace) 와 동일한 idempotent 패턴.
- nullable — 옛 메시지/구조 블록 미사용 메시지는 NULL.
- 인덱스 없음 — JSONB 가 크고 query target 아님.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_messages" not in inspector.get_table_names():
        # chat_messages 가 아직 없는 환경 (test fresh DB 등) — skip.
        return
    existing_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
    if "structured_blocks" not in existing_cols:
        op.add_column(
            "chat_messages",
            sa.Column("structured_blocks", JSONB(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_messages" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
    if "structured_blocks" in existing_cols:
        op.drop_column("chat_messages", "structured_blocks")
