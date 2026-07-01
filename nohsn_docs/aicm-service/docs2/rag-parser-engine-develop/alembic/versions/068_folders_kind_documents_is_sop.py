"""Phase folder-kind + documents.is_sop — SOP/매뉴얼 자동 분류 분리.

Revision ID: 068
Revises: 067
Create Date: 2026-05-07

목적 (5 산업 봇 KMS 재처리 + SOP 분류):
- ``library_folders.kind`` — 폴더 자체의 분류 메타. enum 값
  (``'sop' / 'manual' / 'glossary' / 'faq' / 'policy'``). 기본 ``'manual'``.
- ``documents.is_sop`` — doc 레벨 SOP 플래그 (folder.kind 와 별개로 LLM 1-shot
  분류로 보정 가능). 기본 ``false``.
- 부분 인덱스 ``ix_documents_repo_is_sop`` — repo 안에서 SOP 만 빠르게 필터링.

설계 원칙 (SOP/매뉴얼 자동 분리):
- 회귀 0 — 기존 documents 모두 ``is_sop=false`` (default), 기존 folder 는
  ``kind='manual'`` (default). 검색 동작 변경 X.
- ``kms_sop.search`` 가 추후 ``is_sop=true OR folder.kind='sop'`` 로 좁혀
  진짜 SOP 만 query — 메뉴얼 매뉴얼 혼용 차단.
- 5 봇 (baemin / homeshop / kbsoldier / musinsa / samchully) 재처리 시
  원본 폴더 트리 walk + LLM 분류 결과로 ``kind`` / ``is_sop`` 자동 채움.

회귀 가드:
- 기존 documents 쿼리 (status / repository_id / folder_id WHERE) 영향 0.
- ``library_folders.kind`` 는 server_default 'manual' — 기존 row 자동 채움.
- ``documents.is_sop`` 는 server_default false — 기존 row 자동 채움.
- 부분 인덱스 (WHERE is_sop = true) — 기본 false 일 때 인덱스 거의 비어 무영향.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 허용 kind 값 — DB 레벨 CHECK constraint (enum 표 대신 단순 CHECK 로 유지보수성).
ALLOWED_KINDS = ("sop", "manual", "glossary", "faq", "policy")


def upgrade() -> None:
    """library_folders.kind + documents.is_sop 추가 + 부분 인덱스."""

    # =====================================================================
    # 1. library_folders.kind — 폴더 자체의 분류 메타.
    # =====================================================================
    op.add_column(
        "library_folders",
        sa.Column(
            "kind",
            sa.Text,
            nullable=False,
            server_default=sa.text("'manual'"),
            comment=(
                "폴더 분류: sop / manual / glossary / faq / policy. "
                "재처리 시 LLM 1-shot 으로 채움. 기본 'manual'."
            ),
        ),
    )
    # CHECK constraint — 허용 값 외 차단.
    op.create_check_constraint(
        "ck_library_folders_kind",
        "library_folders",
        sa.text(
            "kind IN ('sop','manual','glossary','faq','policy')"
        ),
    )
    # kind='sop' 빠른 lookup — 부분 인덱스.
    op.create_index(
        "ix_library_folders_kind_sop",
        "library_folders",
        ["repository_id"],
        unique=False,
        postgresql_where=sa.text("kind = 'sop'"),
    )

    # =====================================================================
    # 2. documents.is_sop — doc 레벨 SOP 플래그.
    # =====================================================================
    op.add_column(
        "documents",
        sa.Column(
            "is_sop",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "이 doc 이 SOP 인지 (folder.kind 와 독립적으로 보정 가능). "
                "재처리 시 folder.kind 기본 + LLM 1-shot 보정."
            ),
        ),
    )
    # SOP 만 빠르게 필터링 — 부분 인덱스 (기본 false 일 때 거의 비어).
    op.create_index(
        "ix_documents_repo_is_sop",
        "documents",
        ["repository_id"],
        unique=False,
        postgresql_where=sa.text("is_sop = true"),
    )


def downgrade() -> None:
    """역순."""
    op.drop_index("ix_documents_repo_is_sop", table_name="documents")
    op.drop_column("documents", "is_sop")

    op.drop_index("ix_library_folders_kind_sop", table_name="library_folders")
    op.drop_constraint(
        "ck_library_folders_kind", "library_folders", type_="check"
    )
    op.drop_column("library_folders", "kind")
