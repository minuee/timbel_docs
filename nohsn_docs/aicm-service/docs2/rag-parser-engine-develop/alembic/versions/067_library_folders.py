"""Phase library-folders — repo 안 트리(디렉토리) 분류 + documents.folder_id.

Revision ID: 067
Revises: 065
Create Date: 2026-05-07

목적 (라이브러리 트리 UI/UX 개선):
- ``library_folders`` 신규 테이블 — repo 안에서 폴더 트리 (자기 참조 parent_folder_id).
  같은 부모 안 이름 중복 X (UNIQUE).
- ``documents.folder_id`` 추가 — NULL = repo 의 root. ON DELETE SET NULL —
  폴더 삭제 시 자료 보존, 자동 root 로 회수.
- 인덱스: (repository_id, folder_id) — 폴더별 listing 가속, (parent_folder_id) — 트리 walk.

설계 원칙 (라이브러리-트리 spec):
- 회귀 0 — 기존 documents 모두 folder_id NULL (root) backfill 자동. byte-equal.
- KMS 검색 무영향 — folder 는 분류 전용, 검색은 기존 repo_id/agent_id 격리 유지.
- DetachedInstanceError 패턴 주의 — 컬럼만 추가, relationship 변경 X (소수만).
- 5 role agent repo (baemin / homeshop / kb_soldier / musinsa / samchully) 도
  자동으로 사용 가능 — 별도 backfill X (UI 에서 폴더 신설).

회귀 가드:
- 기존 documents 쿼리 (repository_id WHERE) → folder_id 컬럼만 추가, 기존 row 영향 0.
- ON DELETE CASCADE (parent → child folder) — 부모 폴더 삭제 시 자식까지 자동 정리.
- ON DELETE SET NULL (folder → document) — 폴더 삭제 시 doc 자료 보존, root 회수.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "067"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """library_folders 신규 + documents.folder_id 추가 + index 3."""

    # =====================================================================
    # 1. library_folders 신규 테이블 — repo 안 폴더 트리.
    # =====================================================================
    op.create_table(
        "library_folders",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
            comment="소속 repo. repo 삭제 시 폴더도 함께 정리.",
        ),
        sa.Column(
            "parent_folder_id",
            UUID(as_uuid=True),
            sa.ForeignKey("library_folders.id", ondelete="CASCADE"),
            nullable=True,
            comment="상위 폴더. NULL = repo 의 root 직속. 부모 삭제 시 cascade.",
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            nullable=True,
        ),
        # 같은 부모 안 이름 중복 X. parent NULL 도 UNIQUE 작동 (PostgreSQL NULLS NOT DISTINCT 미사용
            # — 일반 UNIQUE 는 NULL 다중 허용 → 별도 부분 인덱스로 root 레벨 unique 보강).
        sa.UniqueConstraint(
            "repository_id", "parent_folder_id", "name",
            name="uq_library_folders_parent_name",
        ),
    )

    # repo root 레벨 (parent_folder_id IS NULL) 도 이름 중복 차단 — 부분 unique index.
    op.create_index(
        "uq_library_folders_root_name",
        "library_folders",
        ["repository_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_folder_id IS NULL"),
    )

    op.create_index(
        "ix_library_folders_repository",
        "library_folders",
        ["repository_id"],
    )
    op.create_index(
        "ix_library_folders_parent",
        "library_folders",
        ["parent_folder_id"],
        postgresql_where=sa.text("parent_folder_id IS NOT NULL"),
    )
    op.create_index(
        "ix_library_folders_tenant",
        "library_folders",
        ["tenant_id"],
    )

    # =====================================================================
    # 2. documents.folder_id — NULL = repo root 직속, FK SET NULL.
    # =====================================================================
    op.add_column(
        "documents",
        sa.Column(
            "folder_id",
            UUID(as_uuid=True),
            sa.ForeignKey("library_folders.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "library_folders 안 폴더 ID. NULL = repo root 직속. "
                "폴더 삭제 시 SET NULL — 자료 보존."
            ),
        ),
    )

    # 폴더별 listing 가속 — (repo_id, folder_id) 복합 인덱스.
    op.create_index(
        "ix_documents_repo_folder",
        "documents",
        ["repository_id", "folder_id"],
    )
    # folder_id 단독 인덱스 — 폴더 삭제 시 SET NULL 후보 row 빠르게 찾기.
    op.create_index(
        "ix_documents_folder_id",
        "documents",
        ["folder_id"],
        postgresql_where=sa.text("folder_id IS NOT NULL"),
    )


def downgrade() -> None:
    """역순."""
    op.drop_index("ix_documents_folder_id", table_name="documents")
    op.drop_index("ix_documents_repo_folder", table_name="documents")
    op.drop_column("documents", "folder_id")

    op.drop_index("ix_library_folders_tenant", table_name="library_folders")
    op.drop_index("ix_library_folders_parent", table_name="library_folders")
    op.drop_index("ix_library_folders_repository", table_name="library_folders")
    op.drop_index("uq_library_folders_root_name", table_name="library_folders")
    op.drop_table("library_folders")
