"""accounts 테이블에 email_login + password_hash + email_verified + is_active 추가.

Revision ID: 031
Revises: 030
Create Date: 2026-04-25

Phase 9 (KMS-Plus) — Auth v2 (JWT + RBAC).

기존 ``accounts`` 는 phone unique key 로 만들어졌고 (Stage B-1, migration 023)
email/password 는 없다. v2 는 phone-only 로그인을 유지하면서, email + password 로
로그인하는 새 인증 경로를 추가한다.

설계:
- ``email`` — nullable. 기존 phone-only 계정 호환.
- ``password_hash`` — nullable. legacy session_token 경로는 비밀번호 없이도 동작.
- ``email_verified`` — Boolean default false. 가입 직후 verify 메일 흐름 대비.
- ``is_active`` — Boolean default true. soft-disable 지원.
- 부분 인덱스 ``ix_accounts_email_active`` — ``WHERE is_active = true AND email IS NOT NULL``
  로 active account 의 email lookup 가속.

forward-only — 기존 row 의 NOT NULL 강제 X (legacy account 호환).
"""
from alembic import op
import sqlalchemy as sa


revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("email", sa.String(320), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column("password_hash", sa.String(256), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )
    # active account 의 email lookup 가속 — 부분 인덱스.
    op.create_index(
        "ix_accounts_email_active",
        "accounts",
        ["email"],
        unique=False,
        postgresql_where=sa.text("is_active = true AND email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_accounts_email_active", table_name="accounts")
    op.drop_column("accounts", "is_active")
    op.drop_column("accounts", "email_verified")
    op.drop_column("accounts", "password_hash")
    op.drop_column("accounts", "email")
