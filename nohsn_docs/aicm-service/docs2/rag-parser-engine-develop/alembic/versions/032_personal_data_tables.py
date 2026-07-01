"""expense_ledger + health_log — 개인 데이터 primitives.

Revision ID: 032
Revises: 031
Create Date: 2026-04-25

Phase 9 (KMS-Plus) — Wave Insight (Multi-skill Orchestration + Cross-domain 분석).

용도:
- ``expense_ledger`` — 가계부. 카테고리·금액·결제수단·날짜.
- ``health_log`` — 운동/수면/식사/복약 자가기록. 종류별 텍스트 + 수치.

기존 ``user_schedules`` (migration 019) 와 결합해 **3-도메인 cross-analysis**
(schedule + expense + health) 의 데이터 기반이 된다.

설계:
- account-scoped (memberships/accounts 기준). tenant 분리는 application 단에서.
- ``date`` 는 단순 ``DATE`` (시간정보 불필요한 통계용). ``user_schedules`` 와 의도적
  으로 다름 — 일정은 시각이 중요, 가계부/건강로그는 일자만으로도 분석 충분.
- ``metadata`` JSONB — 영수증 OCR 원본·운동 강도·외부 동기화 ID 등 미래 확장.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # expense_ledger — 가계부
    op.create_table(
        "expense_ledger",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        # 식비/교통/주거/여가/의료/교육/통신/공과금/...
        sa.Column("amount_krw", sa.Numeric(14, 0), nullable=False),
        sa.Column("description", sa.String(256)),
        sa.Column("payment_method", sa.String(32)),  # 카드/현금/이체/...
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_expense_account_date", "expense_ledger", ["account_id", "date"]
    )
    op.create_index(
        "ix_expense_account_category",
        "expense_ledger",
        ["account_id", "category", "date"],
    )

    # health_log — 운동·수면·식사·복약 자가기록
    op.create_table(
        "health_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        # exercise / sleep / meal / medication / mood / ...
        sa.Column("value_text", sa.Text),
        # "30분 조깅", "7시간 30분", "샐러드+닭가슴살"
        sa.Column("value_numeric", sa.Numeric(10, 2)),
        # 분 / 시간 / kcal / mg 등 (kind 별 의미 다름)
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index(
        "ix_health_account_date_kind",
        "health_log",
        ["account_id", "date", "kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_health_account_date_kind", table_name="health_log")
    op.drop_table("health_log")
    op.drop_index("ix_expense_account_category", table_name="expense_ledger")
    op.drop_index("ix_expense_account_date", table_name="expense_ledger")
    op.drop_table("expense_ledger")
