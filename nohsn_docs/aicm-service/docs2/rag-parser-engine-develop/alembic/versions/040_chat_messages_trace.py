"""chat_messages.trace JSONB — 추론 과정 영속화 (PR-D).

Revision ID: 040
Revises: 039
Create Date: 2026-04-27

PR-D (KMS-Plus). 사용자 강조: "추론 과정은 디버깅에서 중요한 요소". 기존
TraceStrip 은 frontend in-memory 로만 살다가 새로고침/세션 재진입 시 휘발.
원인: chat_messages 에 trace 저장 컬럼이 없고, chat_v1 의 finally INSERT 도
trace 를 모으지 않으며, restore endpoint 도 trace 를 반환하지 않음. 본 마이그
는 첫 단계 — 컬럼 자리 마련.

설계:
- ``trace`` JSONB NULL — list of trace items. 각 item 은
  ``{ts, kind, label, detail?}``. detail 은 raw event payload 보관 (디버깅·재현용).
- index 없음 — 큰 JSON 이고 query target 아님.
- idempotent — chat_messages 가 다른 untracked chain (034) 또는 운영 DB 에서
  이미 정의된 환경/테스트 환경 둘 다 안전. 테이블 부재 시 skip 하고 다음 마이그
  가 (또는 운영자가) 테이블 생성 후 재실행.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_messages" not in inspector.get_table_names():
        # chat_messages 가 아직 없는 환경 (test fresh DB 등) — skip.
        # 별도 chain 의 마이그가 테이블을 만든 후 trace 컬럼은 그쪽에서 직접 포함.
        return
    existing_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
    if "trace" not in existing_cols:
        op.add_column(
            "chat_messages",
            sa.Column("trace", JSONB(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_messages" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
    if "trace" in existing_cols:
        op.drop_column("chat_messages", "trace")
