"""account_tenants — account ↔ tenant M:N 멤버십 + scope_group.

Revision ID: 043
Revises: 042
Create Date: 2026-04-28

배경
----
오픈 준비 단계에서 사용자가 가진 권한(personal/company/business/sole_proprietor)
을 효율적으로 관리하고 데이터 격리를 유동적으로 다루기 위해 account ↔ tenant
M:N 멤버십을 도입. 격리 전략은 혼합:

- ``personal``, ``sole_proprietor`` — 사용자 단독 personal_tenant 안에서
  scope_group 컬럼만으로 구분 (직원 join 없음, 데이터 공유 없음).
- ``company``, ``business`` — 사업체 단위 별개 tenant. 본인이 대표일 때
  추가 가입(=새 tenant 생성 + 멤버십 row 추가). 한 account 가 N개 회사를
  보유할 수 있으므로 M:N.

backfill
--------
기존 사용자에 대해 ``accounts.personal_tenant_id`` 가 있으면 scope_group
'personal' 멤버십 row 를 자동 생성. role='owner', is_active=true.
"""
from alembic import op
import sqlalchemy as sa


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_tenants",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope_group",
            sa.String(32),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(32),
            nullable=False,
            server_default="owner",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "joined_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # 한 사용자가 한 tenant 에 같은 scope_group 으로 중복 가입 불가.
    op.create_unique_constraint(
        "uq_account_tenants_acc_tnt_scope",
        "account_tenants",
        ["account_id", "tenant_id", "scope_group"],
    )

    # 사용자별 멤버십 조회 — manifest router / 권한 검증 hot path.
    op.create_index(
        "ix_account_tenants_account_id",
        "account_tenants",
        ["account_id", "is_active"],
    )

    op.create_index(
        "ix_account_tenants_tenant_id",
        "account_tenants",
        ["tenant_id", "is_active"],
    )

    # CHECK — scope_group 화이트리스트 (DB 레벨 가드).
    op.create_check_constraint(
        "ck_account_tenants_scope_group",
        "account_tenants",
        "scope_group IN ('personal', 'company', 'business', 'sole_proprietor')",
    )

    # backfill — 기존 accounts.personal_tenant_id 매핑을 personal 멤버십 row 로.
    op.execute(
        """
        INSERT INTO account_tenants (account_id, tenant_id, scope_group, role)
        SELECT a.id, a.personal_tenant_id, 'personal', 'owner'
          FROM accounts a
         WHERE a.personal_tenant_id IS NOT NULL
        ON CONFLICT (account_id, tenant_id, scope_group) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_account_tenants_scope_group", "account_tenants", type_="check"
    )
    op.drop_index("ix_account_tenants_tenant_id", table_name="account_tenants")
    op.drop_index("ix_account_tenants_account_id", table_name="account_tenants")
    op.drop_constraint(
        "uq_account_tenants_acc_tnt_scope",
        "account_tenants",
        type_="unique",
    )
    op.drop_table("account_tenants")
