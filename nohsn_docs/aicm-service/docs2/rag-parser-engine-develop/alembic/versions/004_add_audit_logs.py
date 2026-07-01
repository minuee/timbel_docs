"""Add audit_logs table and composite indexes for query optimization.

Revision ID: 004_audit_logs
Revises: 003_phase2_tables
Create Date: 2026-04-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "004_audit_logs"
down_revision: Union[str, None] = "003_phase2_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """감사 로그 테이블 생성 및 기존 테이블 인덱스 최적화."""

    # === audit_action_enum 타입 생성 ===
    audit_action_enum = sa.Enum(
        "CREATE", "UPDATE", "DELETE", "LOGIN", "SEARCH",
        name="audit_action_enum",
    )
    audit_action_enum.create(op.get_bind(), checkfirst=True)

    # === audit_logs 테이블 ===
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "action",
            audit_action_enum,
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("old_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # audit_logs 인덱스
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "ix_audit_logs_tenant_created",
        "audit_logs",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_tenant_user",
        "audit_logs",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_audit_logs_tenant_resource",
        "audit_logs",
        ["tenant_id", "resource_type", "resource_id"],
    )

    # === 기존 테이블 인덱스 최적화 (Phase 3) ===

    # documents: (repository_id, status) 복합 인덱스
    op.create_index(
        "ix_documents_repo_status",
        "documents",
        ["repository_id", "status"],
    )
    # documents: (created_at DESC) 인덱스
    op.create_index(
        "ix_documents_created_at_desc",
        "documents",
        [sa.text("created_at DESC")],
    )

    # chunks: (document_id, is_indexed) 복합 인덱스
    op.create_index(
        "ix_chunks_doc_indexed",
        "chunks",
        ["document_id", "is_indexed"],
    )
    # chunks: (repository_id, is_indexed) 복합 인덱스
    op.create_index(
        "ix_chunks_repo_indexed",
        "chunks",
        ["repository_id", "is_indexed"],
    )

    # search_logs: (tenant_id, created_at DESC) 복합 인덱스
    op.create_index(
        "ix_search_logs_tenant_created",
        "search_logs",
        ["tenant_id", sa.text("created_at DESC")],
    )
    # search_logs: (repository_id, created_at DESC) 복합 인덱스
    op.create_index(
        "ix_search_logs_repo_created",
        "search_logs",
        ["repository_id", sa.text("created_at DESC")],
    )

    # categories: (repository_id, parent_id) 복합 인덱스
    op.create_index(
        "ix_categories_repo_parent",
        "categories",
        ["repository_id", "parent_id"],
    )


def downgrade() -> None:
    """감사 로그 테이블 및 추가 인덱스를 삭제한다."""
    # 기존 테이블 추가 인덱스 삭제
    op.drop_index("ix_categories_repo_parent", table_name="categories")
    op.drop_index("ix_search_logs_repo_created", table_name="search_logs")
    op.drop_index("ix_search_logs_tenant_created", table_name="search_logs")
    op.drop_index("ix_chunks_repo_indexed", table_name="chunks")
    op.drop_index("ix_chunks_doc_indexed", table_name="chunks")
    op.drop_index("ix_documents_created_at_desc", table_name="documents")
    op.drop_index("ix_documents_repo_status", table_name="documents")

    # audit_logs 테이블 삭제
    op.drop_table("audit_logs")

    # enum 타입 삭제
    sa.Enum(name="audit_action_enum").drop(op.get_bind(), checkfirst=True)
