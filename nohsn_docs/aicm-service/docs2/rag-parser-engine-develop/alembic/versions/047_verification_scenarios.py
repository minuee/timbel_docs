"""verification_scenarios 테이블 — KMS-Plus P0.2.

Revision ID: 047
Revises: 046
Create Date: 2026-04-28

배경
----
PR P9 (Verification Suite) 의 시나리오 카탈로그. yaml 형식 정의 (입력 → 기대 동작)
를 영속화. 운영자/시스템(self_audit) 이 추가/수정 가능.

설계
----
- ``name``      text UNIQUE — 시나리오 식별자
- ``yaml_text`` text — yaml 본문 (스키마는 P9 에서 확정, 본 마이그는 컬럼만)
- ``last_pass_at`` timestamptz NULL — 마지막 통과 시각 (회귀 추적)
- ``created_at``  timestamptz default now()

P9 가 실제 실행을 구현. 본 마이그는 contract 만 마련.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_scenarios" in inspector.get_table_names():
        return
    op.create_table(
        "verification_scenarios",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("yaml_text", sa.Text(), nullable=True),
        sa.Column("last_pass_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_verification_scenarios_name",
        "verification_scenarios",
        ["name"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "verification_scenarios" not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_verification_scenarios_name", table_name="verification_scenarios"
    )
    op.drop_table("verification_scenarios")
