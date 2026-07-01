"""documents.scope_group + expense_ledger.scope_group — 도메인 데이터 scope 분리.

Revision ID: 044
Revises: 043
Create Date: 2026-04-28

배경
----
T4 — 사용자가 보유한 그룹(personal/sole_proprietor/company/business)별로 도메인
데이터(일정/일기/가계부)를 격리하기 위해 row-level scope_group 컬럼 추가.

설계
----
- ``documents.scope_group`` (VARCHAR(32), NULL): schedule/diary 등 agent
  document 패턴이 사용. KMS 본문 등 다른 사용처는 NULL 유지. 컬럼 비용은
  partial index(NOT NULL 조건) 로 격리.
- ``expense_ledger.scope_group`` (VARCHAR(32), NOT NULL DEFAULT 'personal'):
  가계부는 모두 scope 인지가 필요. 기존 row 는 모두 personal 로 backfill.

CHECK 제약은 application 레벨에서 검증 — DB 화이트리스트 강제 시 향후 그룹
추가 가 alembic 변경을 강제해 운영 부담. 단 파라미터 ENUM 키워드는
``account_tenants.scope_group`` 의 CHECK 와 동일 어휘 유지 (personal /
company / business / sole_proprietor).
"""
from alembic import op
import sqlalchemy as sa


revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # documents — nullable, KMS 도메인은 NULL.
    op.add_column(
        "documents",
        sa.Column("scope_group", sa.String(32), nullable=True),
    )
    # 부분 인덱스 — schedule/diary 가 자주 (account_id, scope_group) 로 조회.
    op.create_index(
        "ix_documents_scope_group_partial",
        "documents",
        ["scope_group", "tenant_id"],
        postgresql_where=sa.text("scope_group IS NOT NULL"),
    )

    # expense_ledger — NOT NULL DEFAULT personal. 기존 row 는 server_default 로 backfill.
    op.add_column(
        "expense_ledger",
        sa.Column(
            "scope_group",
            sa.String(32),
            nullable=False,
            server_default="personal",
        ),
    )
    op.create_index(
        "ix_expense_ledger_scope_group",
        "expense_ledger",
        ["account_id", "scope_group", "date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expense_ledger_scope_group", table_name="expense_ledger"
    )
    op.drop_column("expense_ledger", "scope_group")
    op.drop_index(
        "ix_documents_scope_group_partial", table_name="documents"
    )
    op.drop_column("documents", "scope_group")
