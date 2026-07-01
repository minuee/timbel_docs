"""Add users and user_repository_access tables for RBAC.

Revision ID: 002_users_rbac
Revises: 001_initial
Create Date: 2026-04-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "002_users_rbac"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """users 및 user_repository_access 테이블을 생성한다."""

    # Role enum 타입 생성
    user_role_enum = sa.Enum(
        "tenant_admin",
        "repo_admin",
        "editor",
        "viewer",
        "api_consumer",
        name="user_role_enum",
    )
    user_role_enum.create(op.get_bind(), checkfirst=True)

    # === users ===
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("email", sa.String(300), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "role",
            user_role_enum,
            nullable=False,
            server_default="viewer",
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_users_tenant_external_id"),
    )

    # === user_repository_access ===
    op.create_table(
        "user_repository_access",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "repository_id",
            UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role",
            user_role_enum,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "repository_id", name="uq_user_repo_access"),
    )


def downgrade() -> None:
    """users 및 user_repository_access 테이블을 삭제한다."""
    op.drop_table("user_repository_access")
    op.drop_table("users")

    # Role enum 타입 삭제
    sa.Enum(name="user_role_enum").drop(op.get_bind(), checkfirst=True)
