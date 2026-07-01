"""verification_runs 글로벌 started_at 인덱스 — KMS-Plus P0.2 hardening.

Revision ID: 051
Revises: 050
Create Date: 2026-04-28

배경
----
codex 2차 review (P2-5): 048 마이그가 ``(scenario_id, started_at DESC)``
복합 인덱스만 만들었음. ``GET /api/v1/verification/runs`` 의 글로벌 "최근 실행"
쿼리는 ``ORDER BY started_at DESC LIMIT N`` 이라 scenario_id 가 빠진 채
seq scan + sort 가 발생.

설계
----
- ``CREATE INDEX IF NOT EXISTS`` 로 idempotent.
- 단일 컬럼 ``started_at DESC`` — 글로벌 최신순 조회 전용.
- 048 의 복합 인덱스는 그대로 둠 — scenario 별 조회는 그쪽이 더 효율.
"""
from alembic import op
import sqlalchemy as sa


revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_runs" not in inspector.get_table_names():
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_verification_runs_started "
        "ON verification_runs (started_at DESC)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_runs" not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_verification_runs_started")
