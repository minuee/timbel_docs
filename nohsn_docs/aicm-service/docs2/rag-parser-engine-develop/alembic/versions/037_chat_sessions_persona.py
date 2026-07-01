"""chat_sessions.system_prompt — 세션 단위 페르소나/역할 주입.

Revision ID: 037
Revises: 036
Create Date: 2026-04-26

세션을 만들 때 system_prompt 를 함께 받으면, 해당 세션의 모든 turn 에서
사용자 입력 앞에 system_prompt 를 prepend 한다. "이 챗은 콜센터 봇이다",
"친절한 부동산 안내자다" 같은 페르소나/임무 단위 분리를 가볍게 지원.

Note: 본격 외부 에이전트 (agents 테이블, API key 인증, 외부 채널 등) 는 별도
spec 의 후속 작업. 본 변경은 운영자/관리자가 chat 화면에서 "이 세션은 X
역할" 라고 셋팅하면 그대로 동작하게 만드는 최소 단위.
"""
from alembic import op
import sqlalchemy as sa


revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("system_prompt", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "system_prompt")
