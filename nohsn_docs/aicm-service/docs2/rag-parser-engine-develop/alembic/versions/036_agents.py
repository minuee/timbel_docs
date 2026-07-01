"""agents + agent_api_keys + agent_message_log — 외부 에이전트 (External Agent) 백엔드.

Revision ID: 036
Revises: 035
Create Date: 2026-04-26

Phase P3.B (KMS-Plus). frontend-v3 의 ``AgentsListPage`` / ``AgentDetailPage`` 가
호출하는 ``/api/v1/agents/*`` (운영자 측) 와 ``/api/v1/external/agent/{id}/*``
(API key 인증, 외부 호출자 측) 의 영구 저장소.

- ``agents``           : tenant 가 발급하는 named agent. persona + system_prompt
                         + allowed_skills/repos + rate_limit. soft delete = is_active.
- ``agent_api_keys``   : agent 당 N 개 키. ``key_prefix`` (검색용 12자) +
                         ``key_hash`` (bcrypt). soft revoke = revoked_at IS NOT NULL.
- ``agent_message_log``: 외부 호출 감사 로그. request/response JSON, status,
                         tokens_in/out, latency_ms, channel, external_session_id.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------
    # agents
    # ---------------------------------------------------------------------
    op.create_table(
        "agents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("persona", sa.Text, nullable=False, server_default=""),
        sa.Column("system_prompt", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "allowed_skills",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "allowed_repos",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "rate_limit_per_min",
            sa.Integer,
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_agents_tenant_active",
        "agents",
        ["tenant_id", "is_active"],
    )

    # ---------------------------------------------------------------------
    # agent_api_keys
    # ---------------------------------------------------------------------
    op.create_table(
        "agent_api_keys",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # active key 만 빠르게 조회 (revoked 제외).
    op.create_index(
        "ix_agent_api_keys_agent",
        "agent_api_keys",
        ["agent_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # prefix 로 1차 후보 좁히기 (인증 hot path).
    op.create_index(
        "ix_agent_api_keys_prefix",
        "agent_api_keys",
        ["key_prefix"],
    )

    # ---------------------------------------------------------------------
    # agent_message_log
    # ---------------------------------------------------------------------
    op.create_table(
        "agent_message_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(40), nullable=True),
        sa.Column("external_session_id", sa.String(200), nullable=True),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("response", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_agent_log_agent_created",
        "agent_message_log",
        ["agent_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_log_agent_created", table_name="agent_message_log")
    op.drop_table("agent_message_log")
    op.drop_index("ix_agent_api_keys_prefix", table_name="agent_api_keys")
    op.drop_index("ix_agent_api_keys_agent", table_name="agent_api_keys")
    op.drop_table("agent_api_keys")
    op.drop_index("ix_agents_tenant_active", table_name="agents")
    op.drop_table("agents")
