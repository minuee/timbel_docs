"""add tenant_skills table (Stage B-Core-1)

Revision ID: 024
Revises: 023
Create Date: 2026-04-23

Stage B-Core-1 — tenant 별 스킬 활성화.

모든 스킬이 전역으로 intent classifier 라벨에 올라가서, 개인 유저에게도
``appointment_derm`` 같은 business 스킬이 부적절하게 라우팅되는 문제가 있었다.

``tenant_skills`` 는 (tenant × skill_id) 복합 PK 로 해당 tenant 가 실제
enable 한 스킬만 기록한다. 엔진 런타임은 account_id → membership 으로
묶여진 tenant 들의 enabled skill 합집합만 후보로 본다.

- ``skill_id`` 는 YAML meta.id (문자열) — skill 객체 자체는 FS/KMS 에서 로드.
- ``enabled_at`` / ``enabled_by_account_id`` 로 audit.
- ``config`` (JSONB) 은 tenant-specific override (예: 병원명, 진료시간).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_skills",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("skill_id", sa.String(100), primary_key=True),
        sa.Column(
            "enabled_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "enabled_by_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "config",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("idx_tenant_skills_tenant", "tenant_skills", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_tenant_skills_tenant", table_name="tenant_skills")
    op.drop_table("tenant_skills")
