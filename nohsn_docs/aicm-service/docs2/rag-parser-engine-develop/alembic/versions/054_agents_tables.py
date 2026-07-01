"""agents tables (Phase 1) — ALTER existing + new tables

Revision ID: 054
Revises: 053
Create Date: 2026-05-06

기존 agents 테이블 (persona/system_prompt/allowed_skills 등) 위에 새 Phase 1
컬럼 ALTER ADD. agent_channels / channel_user_mappings 는 신규 CREATE.

기존 1 row (장병적금상담봇) 의 새 컬럼 backfill:
- goal: "(legacy — please update via admin panel)"
- guidelines_md: "(legacy — please update via admin panel)"
- knowledge_isolation: 'priority'
- 그 외: 기본값 사용
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade():
    # === agents 테이블 ALTER — 새 컬럼 추가 ===
    op.add_column("agents", sa.Column("goal", sa.Text, nullable=True))
    op.add_column("agents", sa.Column("guidelines_md", sa.Text, nullable=True))
    op.add_column("agents", sa.Column(
        "primary_repo_ids",
        postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
        nullable=False, server_default="{}",
    ))
    op.add_column("agents", sa.Column(
        "fallback_repo_ids",
        postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
        nullable=False, server_default="{}",
    ))
    op.add_column("agents", sa.Column(
        "knowledge_isolation", sa.Text,
        nullable=False, server_default="priority",
    ))
    op.add_column("agents", sa.Column(
        "allowed_tools",
        postgresql.ARRAY(sa.Text),
        nullable=False, server_default="{}",
    ))
    op.add_column("agents", sa.Column("done_when", sa.Text, nullable=True))
    op.add_column("agents", sa.Column(
        "test_mode_visible", sa.Boolean,
        nullable=False, server_default=sa.text("TRUE"),
    ))
    op.add_column("agents", sa.Column(
        "template_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))

    # 기존 row backfill — goal / guidelines_md NULL 채움
    op.execute("""
        UPDATE agents
        SET goal = '(legacy — please update via admin panel)',
            guidelines_md = '(legacy — please update via admin panel)'
        WHERE goal IS NULL
    """)

    # NULL -> NOT NULL 변경
    op.alter_column("agents", "goal", nullable=False)
    op.alter_column("agents", "guidelines_md", nullable=False)

    # CHECK constraint
    op.create_check_constraint(
        "agents_isolation_check",
        "agents",
        "knowledge_isolation IN ('strict', 'priority', 'broad')",
    )

    # partial index (기존 ix_agents_tenant_active 와 이름 중복 방지 — 신규 이름 사용)
    op.create_index(
        "agents_tenant_idx", "agents", ["tenant_id"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # === agent_channels — 신규 CREATE ===
    op.create_table(
        "agent_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False,
                  server_default=sa.text("TRUE")),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("kind", "external_id",
                            name="agent_channels_kind_external_uq"),
    )
    op.create_index("agent_channels_agent_idx", "agent_channels", ["agent_id"])

    # === channel_user_mappings — 신규 CREATE ===
    op.create_table(
        "channel_user_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_user_id", sa.Text, nullable=False),
        sa.Column("internal_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_seen", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["channel_id"], ["agent_channels.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["internal_user_id"], ["users.id"]),
        sa.UniqueConstraint("channel_id", "external_user_id",
                            name="channel_user_mappings_uq"),
    )


def downgrade():
    op.drop_table("channel_user_mappings")
    op.drop_table("agent_channels")
    op.drop_index("agents_tenant_idx", table_name="agents")
    op.drop_constraint("agents_isolation_check", "agents", type_="check")
    op.drop_column("agents", "template_id")
    op.drop_column("agents", "test_mode_visible")
    op.drop_column("agents", "done_when")
    op.drop_column("agents", "allowed_tools")
    op.drop_column("agents", "knowledge_isolation")
    op.drop_column("agents", "fallback_repo_ids")
    op.drop_column("agents", "primary_repo_ids")
    op.drop_column("agents", "guidelines_md")
    op.drop_column("agents", "goal")
