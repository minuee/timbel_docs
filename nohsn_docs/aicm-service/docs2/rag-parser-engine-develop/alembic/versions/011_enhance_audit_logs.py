"""Enhance audit_logs: add detail column and extend audit_action_enum.

Revision ID: 011_enhance_audit_logs
Revises: 010_auth_integrations
Create Date: 2026-04-12

Adds VIEW, DOWNLOAD, EXPORT, SHARE values to audit_action_enum.
Adds 'detail' JSONB column for structured audit metadata (query, result_count, etc.).
Adds composite indexes for optimized queries.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "011_enhance_audit_logs"
down_revision: Union[str, None] = "010_auth_integrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New enum values to add
_NEW_ACTIONS = ["VIEW", "DOWNLOAD", "EXPORT", "SHARE"]


def upgrade() -> None:
    """audit_action_enum 확장 및 detail 칼럼 추가."""

    # === 1. audit_action_enum에 새 값 추가 ===
    # PostgreSQL에서는 ALTER TYPE ... ADD VALUE로 enum 값을 추가한다.
    # 트랜잭션 내에서 ADD VALUE는 사용 불가이므로 autocommit 모드 사용.
    for action_value in _NEW_ACTIONS:
        op.execute(
            sa.text(
                f"ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS '{action_value}'"
            )
        )

    # === 2. detail JSONB 칼럼 추가 ===
    op.add_column(
        "audit_logs",
        sa.Column(
            "detail",
            JSONB,
            nullable=True,
            comment="추가 상세 정보 (검색 쿼리, 결과 수, 변경 사유 등)",
        ),
    )

    # === 3. 복합 인덱스 추가 (user_id, created_at DESC) ===
    # (tenant_id, created_at DESC) 인덱스는 004 마이그레이션에서 이미 생성됨
    op.create_index(
        "ix_audit_logs_user_created_desc",
        "audit_logs",
        ["user_id", sa.text("created_at DESC")],
    )

    # (resource_type, resource_id) 인덱스도 004에서 이미 복합 인덱스 생성됨
    # ix_audit_logs_tenant_resource -> (tenant_id, resource_type, resource_id)


def downgrade() -> None:
    """detail 칼럼 및 추가 인덱스 삭제.

    Note: PostgreSQL에서 enum 값 제거는 쉽지 않으므로 enum은 그대로 유지한다.
    """
    op.drop_index("ix_audit_logs_user_created_desc", table_name="audit_logs")
    op.drop_column("audit_logs", "detail")
