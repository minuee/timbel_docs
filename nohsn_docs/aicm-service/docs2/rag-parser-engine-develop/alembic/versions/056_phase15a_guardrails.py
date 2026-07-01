"""phase15a guardrails — sop_repo_ids + risk_metadata + memo body_hash

Revision ID: 056
Revises: 055
Create Date: 2026-05-06

Adds three guardrail-supporting columns:

1. ``agents.sop_repo_ids`` — Phase 1.5B 가 활용. Agent 별 SOP/policy 문서를
   참조할 repo IDs 목록.
2. ``custom_tools.risk_metadata`` — admin 등록 시 입력. risk_tier / approval /
   rate_limit / budget 같은 거버넌스 메타.
3. ``documents.body_hash`` — Task 4 의 ``memo_recent_duplicate`` checker 가
   참조. Memo 는 별도 테이블이 아니라 ``documents`` 의 ``document_type =
   'agent_memo'`` row 로 저장되므로, body_hash 는 documents 컬럼으로 추가하고
   ``ix_memos_body_hash_recent`` 부분 인덱스로 memo dedup 쿼리를 지원한다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade():
    # 1. agents.sop_repo_ids
    op.add_column(
        "agents",
        sa.Column(
            "sop_repo_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )

    # 2. custom_tools.risk_metadata
    op.add_column(
        "custom_tools",
        sa.Column(
            "risk_metadata",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )

    # 3. documents.body_hash — memo dedup 위한 컬럼 (memos 테이블이 별도로 없으므로
    #    documents 에 추가). 부분 인덱스는 agent_memo 문서만 대상으로 좁혀 다른
    #    문서 검색에 부담을 주지 않는다.
    op.add_column(
        "documents",
        sa.Column("body_hash", sa.String(64), nullable=True),
    )
    op.execute(
        """
        CREATE INDEX ix_memos_body_hash_recent
        ON documents (created_by, body_hash, created_at)
        WHERE body_hash IS NOT NULL
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_memos_body_hash_recent")
    op.drop_column("documents", "body_hash")
    op.drop_column("custom_tools", "risk_metadata")
    op.drop_column("agents", "sop_repo_ids")
