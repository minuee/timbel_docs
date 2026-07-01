"""activation pipeline — unified status CHECK, skill_drafts.status_v2,
CC-pair connectors, tool_invocations (pending/resume), freshness_runs,
activation meta backfill.

Revision ID: 028
Revises: 025
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "028"
down_revision = "025"
branch_labels = None
depends_on = None

STATUS_LABELS = (
    "draft",
    "processing",
    "pending_review",
    "active",
    "archived",
    "rejected",
    "failed",
)


def upgrade() -> None:
    # 1. documents.status CHECK 통일 (기존 CHECK drop 후 재생성)
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_status_check "
        "CHECK (status IN " + str(STATUS_LABELS) + ")"
    )

    # 2. skill_drafts.status_v2 추가 + 백필 (2-phase rename, 029 가 기존 drop)
    op.add_column("skill_drafts", sa.Column("status_v2", sa.String(32), nullable=True))
    op.execute(
        """
        UPDATE skill_drafts SET status_v2 = CASE status
          WHEN 'pending'  THEN 'pending_review'
          WHEN 'approved' THEN 'active'
          WHEN 'rejected' THEN 'rejected'
          WHEN 'expired'  THEN 'archived'
          ELSE 'pending_review' END
        """
    )
    op.alter_column("skill_drafts", "status_v2", nullable=False)
    op.execute(
        "ALTER TABLE skill_drafts ADD CONSTRAINT skill_drafts_status_v2_check "
        "CHECK (status_v2 IN " + str(STATUS_LABELS) + ")"
    )
    op.create_index("ix_skill_drafts_status_v2", "skill_drafts", ["status_v2"])

    # 2b. 기존 INSERT 경로 호환 — status 만 넣어도 status_v2 가 자동 매핑되도록
    # BEFORE INSERT/UPDATE trigger 설치 (2-phase rename 과도기 동안만 유지).
    # 029 에서 기존 status 컬럼 drop 시 함께 drop 예정.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION skill_drafts_sync_status_v2()
        RETURNS TRIGGER AS $$
        BEGIN
          IF NEW.status_v2 IS NULL AND NEW.status IS NOT NULL THEN
            NEW.status_v2 := CASE NEW.status
              WHEN 'pending'  THEN 'pending_review'
              WHEN 'approved' THEN 'active'
              WHEN 'rejected' THEN 'rejected'
              WHEN 'expired'  THEN 'archived'
              ELSE 'pending_review' END;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skill_drafts_sync_status_v2
        BEFORE INSERT OR UPDATE ON skill_drafts
        FOR EACH ROW EXECUTE FUNCTION skill_drafts_sync_status_v2();
        """
    )

    # 3. CC-pair 구조 (델타 #2 Onyx 패턴) — connectors / credentials / pairs
    op.create_table(
        "connectors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("spec_kind", sa.String(32), nullable=False),
        sa.Column("spec", JSONB(), nullable=False, server_default="{}"),
        sa.Column("allowed_ops", JSONB(), nullable=False, server_default="[]"),
        sa.Column("side_effect_level", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "spec_kind IN ('openapi','rss','mcp','custom')",
            name="connectors_spec_kind_check",
        ),
        sa.CheckConstraint(
            "side_effect_level IN ('read_only','write_external','irreversible')",
            name="connectors_side_effect_check",
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_connectors_tenant_name"),
    )

    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("auth_type", sa.String(32), nullable=False),
        sa.Column("auth_secret_ref", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "auth_type IN ('bearer','oauth','api_key','basic','none')",
            name="ccred_auth_type_check",
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ccred_tenant_name"),
    )

    op.create_table(
        "connector_credential_pairs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "connector_id",
            sa.String(64),
            sa.ForeignKey("connectors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "credential_id",
            sa.String(64),
            sa.ForeignKey("connector_credentials.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("processing_meta", JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_probe_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_probe_ok", sa.Boolean()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN " + str(STATUS_LABELS), name="ccp_status_check"
        ),
        sa.UniqueConstraint(
            "tenant_id", "connector_id", "credential_id", name="uq_ccp_triple"
        ),
    )
    op.create_index(
        "idx_ccp_tenant_status",
        "connector_credential_pairs",
        ["tenant_id", "status"],
    )

    # 4. tool_invocations 감사 + interrupt/resume (델타 #5 LangGraph)
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64)),
        sa.Column("turn_id", sa.String(64)),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("cc_pair_id", sa.String(64)),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("input_args", JSONB()),
        sa.Column("output", JSONB()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column(
            "dry_run", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")
        ),
        sa.Column(
            "confirmed_by_user",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("confirmed_by_user_id", sa.String(64)),
        sa.Column("resume_token", sa.String(128)),
        sa.CheckConstraint(
            "status IN ('pending_confirm','pending_resume','succeeded','failed',"
            "'dry_run','canceled','timeout')",
            name="tool_inv_status_check",
        ),
    )
    op.create_index(
        "idx_tool_inv_tenant_time",
        "tool_invocations",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_tool_inv_skill",
        "tool_invocations",
        ["skill_id", sa.text("created_at DESC")],
    )
    op.execute(
        "CREATE INDEX idx_tool_inv_pending ON tool_invocations (tenant_id, status) "
        "WHERE status IN ('pending_confirm','pending_resume')"
    )

    # 5. 기존 active documents 백필 (감사용 legacy_auto_approved 마커)
    op.execute(
        """
        UPDATE documents
           SET processing_meta = jsonb_set(
                COALESCE(processing_meta, '{}'::jsonb),
                '{activation}',
                COALESCE(processing_meta -> 'activation', '{}'::jsonb)
                  || '{"legacy_auto_approved": true, "policy": "pre_028_baseline"}'::jsonb,
                true)
         WHERE status = 'active'
           AND (processing_meta -> 'activation' ->> 'legacy_auto_approved') IS NULL
        """
    )

    # 6. 주기 cross-scan 실행 로그 (델타 #4)
    op.create_table(
        "knowledge_freshness_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64)),  # NULL = all tenants
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column(
            "docs_scanned",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "pairs_classified",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "issues_found",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "trigger", sa.String(32), nullable=False, server_default="scheduled"
        ),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','canceled')",
            name="kfr_status_check",
        ),
        sa.CheckConstraint(
            "trigger IN ('scheduled','manual','post_deploy')",
            name="kfr_trigger_check",
        ),
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_freshness_runs")

    op.execute("DROP INDEX IF EXISTS idx_tool_inv_pending")
    op.execute("DROP INDEX IF EXISTS idx_tool_inv_skill")
    op.execute("DROP INDEX IF EXISTS idx_tool_inv_tenant_time")
    op.execute("DROP TABLE IF EXISTS tool_invocations")

    op.execute("DROP INDEX IF EXISTS idx_ccp_tenant_status")
    op.execute("DROP TABLE IF EXISTS connector_credential_pairs")
    op.execute("DROP TABLE IF EXISTS connector_credentials")
    op.execute("DROP TABLE IF EXISTS connectors")

    op.execute("DROP TRIGGER IF EXISTS trg_skill_drafts_sync_status_v2 ON skill_drafts")
    op.execute("DROP FUNCTION IF EXISTS skill_drafts_sync_status_v2()")
    op.execute("ALTER TABLE skill_drafts DROP CONSTRAINT IF EXISTS skill_drafts_status_v2_check")
    op.execute("DROP INDEX IF EXISTS ix_skill_drafts_status_v2")
    op.execute("ALTER TABLE skill_drafts DROP COLUMN IF EXISTS status_v2")

    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check")
