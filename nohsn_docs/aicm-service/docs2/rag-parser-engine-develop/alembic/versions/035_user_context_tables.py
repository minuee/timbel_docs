"""user_life_context + user_corporate_context — 개인/조직 컨텍스트 영구화.

Revision ID: 035
Revises: 034
Create Date: 2026-04-26

Phase P1.5 (KMS-Plus). frontend-v2 의 LifeContextPage / MyProfilePage /
CorporateContextPage 가 호출하는 ``/api/v1/context/*`` CRUD 의 저장소.

- user_life_context: account 1명당 N 개 항목 (key=값). 가족·취미·일정 같은 개인 컨텍스트.
- user_corporate_context: tenant 1개당 N 개 항목 (key=값). 회사 정책/도메인 컨텍스트.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_life_context",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, server_default="general"),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_user_life_context_account_updated",
        "user_life_context",
        ["account_id", sa.text("updated_at DESC")],
    )

    op.create_table(
        "user_corporate_context",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False, server_default="general"),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_user_corporate_context_tenant_updated",
        "user_corporate_context",
        ["tenant_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_user_corporate_context_tenant_updated", table_name="user_corporate_context")
    op.drop_table("user_corporate_context")
    op.drop_index("ix_user_life_context_account_updated", table_name="user_life_context")
    op.drop_table("user_life_context")
