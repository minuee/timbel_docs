"""user_mail_accounts + email_processing_log + source_email_id 외래키.

Revision ID: 041
Revises: 040
Create Date: 2026-04-28

PR-Z11A / Z13 / Z14 (KMS-Plus). 자비스 비전의 이메일 처리 시나리오 토대.

테이블:
- ``user_mail_accounts`` — 사용자가 등록한 IMAP/POP3 계정. password 는 Fernet
  암호화된 BYTEA. host/port/protocol/username + UID watermark + poll interval.
- ``email_processing_log`` — 미러링된 이메일마다의 분류 결과 + 취해진 액션
  기록. frontend 의 처리 로그 화면 + 디버깅용.

기존 테이블 보강:
- ``schedules`` (kms documents 가 아닌 redis 기반이라 column 추가 X — 대안:
  schedule body JSON 안에 source_email_id 필드 사용. agent_documents 의
  메타에서도 동일).
- ``reminders`` 동일 (redis 기반).
- 따라서 source attribution 은 *body/metadata 안의 JSON 필드* 로 처리하고
  별도 column 추가 불필요. email_processing_log.actions_taken 에서 역추적.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_mail_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(64), nullable=False, server_default="기본"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False),  # imap | imaps | pop3 | pop3s
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("last_uid_synced", sa.String(64), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("poll_interval_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "last_error", sa.String(500), nullable=True
        ),  # polling 실패 시 사용자 안내용
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")
        ),
    )
    op.create_index(
        "ix_user_mail_accounts_account_enabled",
        "user_mail_accounts",
        ["account_id", "enabled"],
    )

    op.create_table(
        "email_processing_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mail_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user_mail_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            nullable=True,  # KMS document FK — soft link, no FK constraint due to docs in different schema
        ),
        sa.Column("message_id", sa.String(500), nullable=True),  # email Message-ID header
        sa.Column("from_address", sa.String(255), nullable=True),
        sa.Column("from_domain", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        # 분류 결과 (LLM JSON 그대로)
        sa.Column("classification", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("trust_score", sa.Float, nullable=True),
        # 취해진 액션 list — [{type, target_id, summary, ...}, ...]
        sa.Column("actions_taken", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("error", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_email_processing_log_account_processed",
        "email_processing_log",
        ["account_id", sa.text("processed_at DESC")],
    )
    op.create_index(
        "ix_email_processing_log_message_id",
        "email_processing_log",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_email_processing_log_message_id", table_name="email_processing_log")
    op.drop_index("ix_email_processing_log_account_processed", table_name="email_processing_log")
    op.drop_table("email_processing_log")
    op.drop_index("ix_user_mail_accounts_account_enabled", table_name="user_mail_accounts")
    op.drop_table("user_mail_accounts")
