"""Add auth columns to users and create integrations table.

Revision ID: 010_auth_integrations
Revises: 009_backend_features
Create Date: 2026-04-07

New columns on users: password_hash, auth_provider, email_verified, totp_secret, last_login_at
New table: integrations
New table: user_tenants (if not exists)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "010_auth_integrations"
down_revision: Union[str, None] = "009_backend_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """인증 컬럼 추가 및 integrations 테이블 생성."""

    # --- users 테이블에 인증 관련 컬럼 추가 ---
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.String(20),
            nullable=False,
            server_default="local",
            comment="인증 방식: local/google/apple/sso",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_secret",
            sa.String(64),
            nullable=True,
            comment="2FA TOTP 비밀키",
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- integrations 테이블 ---
    op.create_table(
        "integrations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "integration_type",
            sa.String(50),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "config",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="inactive",
            comment="inactive, active, error",
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sync_frequency",
            sa.String(20),
            nullable=False,
            server_default="manual",
            comment="manual, hourly, daily",
        ),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """롤백: integrations 테이블 및 users 인증 컬럼 제거."""
    op.drop_table("integrations")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "password_hash")
