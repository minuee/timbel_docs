"""add accounts and tenant_memberships for agent framework (Stage B-1)

Revision ID: 023
Revises: 022
Create Date: 2026-04-23

Stage B-1 — 원안 복귀 2단계.

기존 `users` 테이블은 (tenant_id, name, email, role) 로 tenant 내부 직원/관리자용.
Agent 프레임워크가 필요로 하는 "phone 기반 개인 유저" 는 별도 테이블이 필요.

- ``accounts`` — phone 기준 unique. 개인 유저 한 명 = 한 row. ``personal_tenant_id``
  로 각 계정의 개인 tenant (tenant_type='personal') 를 가리킨다.
- ``tenant_memberships`` — account × tenant 의 M:N. 개인 테넌트엔 owner, 비즈니스
  테넌트엔 staff/viewer 로 연결될 예정 (Stage B-3~5).

두 테이블 모두 신규 생성 — 기존 `users` / `tenant_links` 는 건드리지 않는다.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("phone", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column(
            "personal_tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_accounts_phone", "accounts", ["phone"], unique=True)

    op.create_table(
        "tenant_memberships",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'owner'"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("account_id", "tenant_id", name="uq_account_tenant"),
    )
    op.create_index("idx_memberships_account", "tenant_memberships", ["account_id"])
    op.create_index("idx_memberships_tenant", "tenant_memberships", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_memberships_tenant", table_name="tenant_memberships")
    op.drop_index("idx_memberships_account", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_index("idx_accounts_phone", table_name="accounts")
    op.drop_table("accounts")
