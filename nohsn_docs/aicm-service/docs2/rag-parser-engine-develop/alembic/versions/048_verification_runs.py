"""verification_runs 테이블 — KMS-Plus P0.2.

Revision ID: 048
Revises: 047
Create Date: 2026-04-28

배경
----
PR P9 (Verification Suite) 의 실행 기록. 시나리오 실행마다 1행 — 시작/종료
시각, 상태, trace JSON, 소요시간.

설계
----
- ``scenario_id``  UUID FK verification_scenarios (CASCADE) NULL — ad-hoc 실행 허용
- ``started_at``   timestamptz default now()
- ``finished_at``  timestamptz NULL — 실행 중이면 NULL
- ``status``       text — 자유 식별자 (pending/running/pass/fail/skip 등),
                   enum 강제 X — 운영자가 새 상태 추가 가능
- ``trace``        JSONB default '{}' — 실행 trace (P9 가 채움)
- ``duration_ms``  integer NULL — 종료 후 산출

본 마이그는 컬럼만. 실 실행은 P9.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_runs" in inspector.get_table_names():
        return
    op.create_table(
        "verification_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scenario_id",
            UUID(as_uuid=True),
            sa.ForeignKey("verification_scenarios.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "trace",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    # 시나리오별 최신 실행 조회 (FeedPage / dashboard) 용 desc 인덱스.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_verification_runs_scenario_started "
        "ON verification_runs (scenario_id, started_at DESC)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_runs" not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_verification_runs_scenario_started")
    op.drop_table("verification_runs")
