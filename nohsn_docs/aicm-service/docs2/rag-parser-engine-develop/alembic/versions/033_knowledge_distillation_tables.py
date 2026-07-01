"""knowledge distillation — block_extraction_index + block_relations + domain_knowledge_summary.

Revision ID: 033
Revises: 032
Create Date: 2026-04-26

Wave 6 (Sub-project A — Knowledge Distillation Pipeline).

L1 ``block_extraction_index`` — block 단위 시점/버전 라벨, lazy LLM 추출 결과.
L2 ``block_relations`` — 두 block 간 supersedes/conflicts/duplicate/complementary 관계.
L3 ``domain_knowledge_summary`` — tenant+repo 단위 신본 매핑 + 핵심 컨텍스트.

설계:
- blocks FK CASCADE — block 삭제 시 메타도 정리.
- raw_response JSONB — LLM 원응답 보관 → confidence 미달 시 재추출 가능.
- (tenant_id, repository_id) UNIQUE — 도메인 요약은 tenant+repo 1개.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID


revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "block_extraction_index",
        sa.Column("block_id", UUID(as_uuid=True),
                  sa.ForeignKey("blocks.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("effective_date", sa.Date),
        sa.Column("version_label", sa.Text),
        sa.Column("topic_keywords", ARRAY(sa.Text)),
        sa.Column("confidence", sa.REAL),
        sa.Column("raw_response", JSONB(), nullable=False, server_default="{}"),
        sa.Column("extracted_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("extractor_model", sa.Text, nullable=False),
    )
    op.create_index("idx_bei_tenant", "block_extraction_index", ["tenant_id"])

    op.create_table(
        "block_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("from_block_id", UUID(as_uuid=True),
                  sa.ForeignKey("blocks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("to_block_id", UUID(as_uuid=True),
                  sa.ForeignKey("blocks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("relation", sa.Text, nullable=False),
        sa.Column("confidence", sa.REAL),
        sa.Column("distilled_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("reasoning", sa.Text),
        sa.CheckConstraint(
            "relation IN ('supersedes','conflicts','duplicate','complementary')",
            name="ck_block_relations_relation",
        ),
        sa.UniqueConstraint("from_block_id", "to_block_id", "relation",
                            name="uq_block_relations_pair"),
    )
    op.create_index("idx_br_from", "block_relations", ["from_block_id"])
    op.create_index("idx_br_to", "block_relations", ["to_block_id"])

    op.create_table(
        "domain_knowledge_summary",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True)),
        sa.Column("summary_text", sa.Text, nullable=False),
        sa.Column("source_block_count", sa.Integer),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.Column("generator_model", sa.Text, nullable=False),
        sa.UniqueConstraint("tenant_id", "repository_id",
                            name="uq_dks_tenant_repo"),
    )
    op.create_index("idx_dks_tenant", "domain_knowledge_summary", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_dks_tenant", table_name="domain_knowledge_summary")
    op.drop_table("domain_knowledge_summary")
    op.drop_index("idx_br_to", table_name="block_relations")
    op.drop_index("idx_br_from", table_name="block_relations")
    op.drop_table("block_relations")
    op.drop_index("idx_bei_tenant", table_name="block_extraction_index")
    op.drop_table("block_extraction_index")
