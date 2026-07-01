"""documents 테이블에 search_excluded 컬럼 추가.

Revision ID: 053
Revises: 052
Create Date: 2026-05-06

배경
----
기존 documents.status = 'archived' 가 *소프트 삭제* 와 *검색 제외* 두 의미로
double-duty 수행. 문서함 토글("검색 제외")이 status 를 archived 로 만들어
library 기본 필터(status != archived)에서 해당 문서가 사라지는 결함.

수정
----
search_excluded BOOLEAN 컬럼을 별도로 추가.
- 검색 제외 토글: search_excluded = true (status 는 active 그대로)
- 소프트 삭제: status = 'archived' (기존 유지)
"""
from alembic import op
import sqlalchemy as sa


revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "search_excluded",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="true 이면 검색/RAG 에서 제외 (status 는 active 유지 — library 에 계속 표시)",
        ),
    )
    op.create_index(
        "ix_documents_search_excluded",
        "documents",
        ["search_excluded"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_search_excluded", table_name="documents")
    op.drop_column("documents", "search_excluded")
