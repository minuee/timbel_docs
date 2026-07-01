"""Add categories.icon column (UI Font Awesome icon name).

Revision ID: kms_003_add_category_icon
Revises: kms_002_fix_categories_and_tenant_synonyms
Create Date: 2026-06-11

Issue:
  분류관리에서 부모 분류에 아이콘(Font Awesome 이름)을 설정하지만 categories 에
  icon 컬럼이 없어 저장되지 않았다. 프론트는 icon 송수신/표시 코드를 이미 보유.

Root cause:
  ORM/스키마/라우터/서비스에 icon 이 없어 입력값이 버려짐.

Fix:
  categories.icon varchar(50) 컬럼 추가. ADD COLUMN IF NOT EXISTS 로 재실행 안전.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "kms_003_add_category_icon"
down_revision: Union[str, None] = "kms_002_fix_categories_and_tenant_synonyms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE categories ADD COLUMN IF NOT EXISTS icon varchar(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE categories DROP COLUMN IF EXISTS icon")
