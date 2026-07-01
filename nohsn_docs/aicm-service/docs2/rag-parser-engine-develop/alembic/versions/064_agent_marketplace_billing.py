"""Phase 1.5D — Agent Marketplace + Billing + Alerts + Templates.

Revision ID: 064
Revises: 063
Create Date: 2026-05-07

목적 (Phase 1.5D — 에이전트 관리 9 페이지 + 임대 사업 모델):
- ``agent_templates`` — super-admin 카탈로그 (template_key + version → publish).
- ``agent_subscriptions`` — 고객사 tenant 가 import 한 instance ledger.
- ``agent_billing`` — 월 청구 ledger (turn / token / channel / total_amount).
- ``agent_alerts`` — Phase 1.8 admin_notifications 의 agent-scoped projection.
- ``agents`` 컬럼 추가 — source_template_id / is_template / lineage_root_id.
- ``mv_agent_dashboard_5min`` — agent_message_log 5분 실시간 KPI view.

설계 원칙 (spec §2):
- 하드코딩 enum 금지 — kind / category / pricing.model 모두 free string.
- RLS 무력화 X — agent_templates 만 super-admin 자산 (tenant_id 비식별).
- backward-compat: 기존 agents 행은 source_template_id NULL / is_template false.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Phase 1.5D 신규 4 테이블 + agents 컬럼 + materialized view."""

    # =====================================================================
    # 1. agent_templates — super-admin 카탈로그 (tenant_id 없음 — global asset).
    # =====================================================================
    op.create_table(
        "agent_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("template_key", sa.String(100), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("persona_template", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "sop_markdown_template",
            sa.Text,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "allowed_tools",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "channel_kinds",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "required_paid_addons",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # publish_status — 자유 문자열 (draft/published/deprecated 권고).
        sa.Column(
            "publish_status",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("author_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "pricing_plan",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("preview_screenshots", JSONB(), nullable=True),
        sa.Column("vendor", sa.String(100), nullable=True),
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
        sa.UniqueConstraint(
            "template_key",
            "version",
            name="uq_agent_templates_key_version",
        ),
    )
    op.create_index(
        "ix_agent_templates_publish_category",
        "agent_templates",
        ["publish_status", "category"],
    )

    # =====================================================================
    # 2. agent_subscriptions — 고객사 import 인스턴스 ledger.
    # =====================================================================
    op.create_table(
        "agent_subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("customer_tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customized_persona", sa.Text, nullable=True),
        sa.Column("customized_sop_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "quota_used_this_month",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("quota_limit", sa.Integer, nullable=True),
        sa.Column(
            "billing_plan",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "activated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "customer_tenant_id",
            "template_id",
            "agent_id",
            name="uq_agent_subscriptions_tenant_template_agent",
        ),
    )
    op.create_index(
        "ix_agent_subscriptions_tenant_status",
        "agent_subscriptions",
        ["customer_tenant_id", "status"],
    )
    op.create_index(
        "ix_agent_subscriptions_template",
        "agent_subscriptions",
        ["template_id"],
    )

    # =====================================================================
    # 3. agent_billing — 월 청구 ledger.
    # =====================================================================
    op.create_table(
        "agent_billing",
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
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "turn_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "token_in",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "token_out",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "channel_cost",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tool_call_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "currency",
            sa.String(8),
            nullable=False,
            server_default="KRW",
        ),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(200), nullable=True),
        sa.Column("line_items", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "agent_id",
            "period_start",
            "period_end",
            name="uq_agent_billing_agent_period",
        ),
    )
    op.create_index(
        "ix_agent_billing_tenant_period",
        "agent_billing",
        ["tenant_id", sa.text("period_start DESC")],
    )
    op.create_index(
        "ix_agent_billing_subscription",
        "agent_billing",
        ["subscription_id"],
    )

    # =====================================================================
    # 4. agent_alerts — 운영 알람 (Phase 1.8 와 cross-link).
    # =====================================================================
    op.create_table(
        "agent_alerts",
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
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        # kind/level — 자유 문자열. enum 박지 않음 (spec §2.1).
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column(
            "level",
            sa.String(16),
            nullable=False,
            server_default="info",
        ),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column(
            "triggered_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("acknowledged_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("acknowledged_by", UUID(as_uuid=True), nullable=True),
        sa.Column("notification_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_agent_alerts_agent_triggered",
        "agent_alerts",
        ["agent_id", sa.text("triggered_at DESC")],
    )
    op.create_index(
        "ix_agent_alerts_tenant_unack",
        "agent_alerts",
        ["tenant_id", "level", "acknowledged_at"],
    )

    # =====================================================================
    # 5. agents 컬럼 추가 — Marketplace lineage.
    # =====================================================================
    op.add_column(
        "agents",
        sa.Column(
            "source_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "is_template",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "lineage_root_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agents_source_template",
        "agents",
        ["source_template_id"],
        postgresql_where=sa.text("source_template_id IS NOT NULL"),
    )

    # =====================================================================
    # 6. mv_agent_dashboard_5min — 5분 실시간 KPI.
    # 본 view 는 agent_message_log 기반 (audit_log + tool_invocations 가 아닌
    # 우리가 이미 가진 신뢰 source). refresh 는 cron (1분 권고).
    # =====================================================================
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_agent_dashboard_5min AS
        SELECT
            a.tenant_id                                    AS tenant_id,
            aml.agent_id                                   AS agent_id,
            COUNT(*)                                       AS turn_5m,
            COUNT(DISTINCT aml.external_session_id)        AS active_sessions_5m,
            SUM(CASE WHEN aml.status = 'error' THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0)                      AS error_rate_5m,
            COALESCE(AVG(aml.latency_ms), 0)::int          AS avg_latency_ms_5m,
            COALESCE(SUM(aml.tokens_in), 0)                AS tokens_in_5m,
            COALESCE(SUM(aml.tokens_out), 0)               AS tokens_out_5m
        FROM agent_message_log aml
        JOIN agents a ON a.id = aml.agent_id
        WHERE aml.created_at > now() - interval '5 minutes'
        GROUP BY a.tenant_id, aml.agent_id
        WITH NO DATA;
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_agent_dashboard_5min "
        "ON mv_agent_dashboard_5min (tenant_id, agent_id);"
    )


def downgrade() -> None:
    """역순 — view → agents 컬럼 → 4 테이블."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_agent_dashboard_5min")

    op.drop_index("ix_agents_source_template", table_name="agents")
    op.drop_column("agents", "lineage_root_id")
    op.drop_column("agents", "is_template")
    op.drop_column("agents", "source_template_id")

    op.drop_index("ix_agent_alerts_tenant_unack", table_name="agent_alerts")
    op.drop_index("ix_agent_alerts_agent_triggered", table_name="agent_alerts")
    op.drop_table("agent_alerts")

    op.drop_index("ix_agent_billing_subscription", table_name="agent_billing")
    op.drop_index("ix_agent_billing_tenant_period", table_name="agent_billing")
    op.drop_table("agent_billing")

    op.drop_index(
        "ix_agent_subscriptions_template",
        table_name="agent_subscriptions",
    )
    op.drop_index(
        "ix_agent_subscriptions_tenant_status",
        table_name="agent_subscriptions",
    )
    op.drop_table("agent_subscriptions")

    op.drop_index(
        "ix_agent_templates_publish_category",
        table_name="agent_templates",
    )
    op.drop_table("agent_templates")
