"""Lucas-KMS 001 — repository_groups table 신설.

Revision ID: lucas_kms_001_repository_groups
Revises: kms_root
Create Date: 2026-05-19

Lucas-KMS 전용 신규 entity: ``RepositoryGroup``.

- tenant 안에 named multi-repository subset 을 정의.
- 검색 호출 시 ``repository_group_id`` 또는 ``repository_ids`` array 로
  multi-repo 하이브리드 검색 활성화.
- ``repository_ids`` 는 postgres ``ARRAY(UUID)`` (FK 미강제) — application
  layer 에서 active 필터로 cleanup.
- ``UniqueConstraint(tenant_id, name)`` — tenant 안 group 이름 중복 차단.
- ``ix_repo_groups_tenant_default`` — set-default endpoint 의 lookup 최적화.

본 migration 은 통합 솔루션 (AICM-APIs) 에는 적용되지 않는다 — Lucas-KMS
branch 안에서만 활성. KMS root (kms_root) 의 자손이며 ``branch_labels=None``
유지 (kms branch 안의 단순 자손 revision).

메모리 절칙:
- 본체 (AICM-APIs) 미수정 — 본 파일은 Lucas-KMS 폴더 전용.
- 하드코딩 X — 컬럼/index 모두 model 정의와 1:1.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = "lucas_kms_001_repository_groups"
down_revision: Union[str, None] = "kms_root"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """``repository_groups`` 테이블 + tenant/default 복합 index 생성."""
    op.create_table(
        "repository_groups",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "repository_ids",
            ARRAY(UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_repo_group_tenant_name"),
    )

    # tenant_id index (FK lookup + list endpoint)
    op.create_index(
        "ix_repository_groups_tenant_id",
        "repository_groups",
        ["tenant_id"],
    )

    # set-default endpoint 의 lookup (tenant + is_default).
    op.create_index(
        "ix_repo_groups_tenant_default",
        "repository_groups",
        ["tenant_id", "is_default"],
    )


def downgrade() -> None:
    """``repository_groups`` 테이블 + index drop."""
    op.drop_index(
        "ix_repo_groups_tenant_default",
        table_name="repository_groups",
    )
    op.drop_index(
        "ix_repository_groups_tenant_id",
        table_name="repository_groups",
    )
    op.drop_table("repository_groups")
