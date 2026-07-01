"""user_mail_accounts SMTP 컬럼 — KMS-Plus 메일 보내기 인프라.

Revision ID: 052
Revises: 051
Create Date: 2026-05-06

배경
----
기존 user_mail_accounts 는 IMAP/POP3 수신 전용 (host/port/protocol/username/
password_encrypted). 메일 보내기 (SMTP) 를 챗에서 지원하려면 발신용 SMTP
자격증명이 별도로 필요. 같은 row 에 nullable 컬럼으로 추가 — 1 mail account =
1 IMAP+SMTP 묶음 (대부분 케이스 동일 호스트/계정).

설계
----
- 모두 nullable. 기존 row 무관 (IMAP-only 운영 계속 가능).
- smtp_host / smtp_port / smtp_username 은 평문, smtp_password_encrypted 는
  Fernet (mail.credentials).
- smtp_use_tls (bool) — 587 STARTTLS / 465 SSL 둘 다 지원.
"""
from alembic import op
import sqlalchemy as sa


revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_mail_accounts",
        sa.Column("smtp_host", sa.String(255), nullable=True),
    )
    op.add_column(
        "user_mail_accounts",
        sa.Column("smtp_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "user_mail_accounts",
        sa.Column("smtp_username", sa.String(255), nullable=True),
    )
    op.add_column(
        "user_mail_accounts",
        sa.Column("smtp_password_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "user_mail_accounts",
        sa.Column(
            "smtp_use_tls",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_mail_accounts", "smtp_use_tls")
    op.drop_column("user_mail_accounts", "smtp_password_encrypted")
    op.drop_column("user_mail_accounts", "smtp_username")
    op.drop_column("user_mail_accounts", "smtp_port")
    op.drop_column("user_mail_accounts", "smtp_host")
