"""user_mail_accounts.scope + accounts.user_groups + signup hook 보강.

Revision ID: 042
Revises: 041
Create Date: 2026-04-28

오픈 준비 — 사용자 group 기반 메뉴 필터링 + scope 분리 (개인 메일 / 회사 메일).

- ``user_mail_accounts.scope`` (varchar 16, default 'personal'): 사용자가 등록
  시 'personal' 또는 'company' 명시. mirror worker 가 메일 분류 시 이 값을
  metadata 에 첨부 → 향후 inbox API 의 scope 필터링 가능.
- ``accounts.preferences`` 안에 'user_groups' key (JSONB) — manifest filter
  에 활용. accounts.preferences 컬럼은 alembic 039 에서 이미 추가됨.
  컬럼 추가 X, application 레벨에서 키 set/get.
"""
from alembic import op
import sqlalchemy as sa


revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_mail_accounts",
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default="personal",
        ),
    )
    # 'personal' | 'company' — 인덱스 거의 불필요 (계정당 row 적음).


def downgrade() -> None:
    op.drop_column("user_mail_accounts", "scope")
