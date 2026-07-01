"""Phase 2 T2.1 — Alembic multi-branch transition: kms branch root (no-op).

Revision ID: kms_root
Revises: 081
Create Date: 2026-05-19

목적 (spec §7 Alembic multi-branch 전략):
- KMS 도메인 (blocks, categories, documents, sections, chunks, document_types,
  intent_logs, library_folders, repositories, search_logs, document_categories
  association) 의 *branch label* 부여.
- ``depends_on=("shared",)`` 로 shared 가 먼저 적용된 환경에서만 작동을 보장
  (tenants/users 등 FK 참조).
- 향후 KMS 전용 migration 은 본 revision 의 자손으로 추가.

본 revision 자체는 no-op — 기존 단일 history 가 이미 KMS table 을 생성했기
때문. fresh DB 에 대해서도 ``081`` 까지 적용되면 모든 KMS table 이 이미 존재
하므로 추가 DDL 불필요.

실 DB 미적용 — staging 검증 후 적용.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "kms_root"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = ("kms",)
depends_on: Union[str, Sequence[str], None] = ("shared",)


def upgrade() -> None:
    """No-op — branch label 부여만 수행."""
    pass


def downgrade() -> None:
    """No-op — branch label 해제만 수행."""
    pass
