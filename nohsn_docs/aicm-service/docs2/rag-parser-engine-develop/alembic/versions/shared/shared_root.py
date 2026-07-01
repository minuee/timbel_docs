"""Phase 2 T2.1 — Alembic multi-branch transition: shared branch root (no-op).

Revision ID: shared_root
Revises: 081
Create Date: 2026-05-19

목적 (spec §7 Alembic multi-branch 전략):
- 단일 linear history (001 → ... → 081) 를 *transition* 시점에 3 갈래 (shared /
  kms / agent) 로 분기. 본 revision 은 ``branch_labels=("shared",)`` 만 부여하는
  *no-op* root. 실제 DDL 변경 없음.
- 향후 shared 도메인 (tenants, users, audit_logs, integrations, llm_usage,
  anonymization_logs, api_keys, tenant_links, transition_events,
  lifecycle_policies, user_repository_access, dlq_messages) 의 신규 migration
  은 본 revision 의 자손으로 추가.

상위 (down_revision="081") = 기존 단일 history 의 마지막 head. 이 transition
revision 이 적용되면 alembic_version 테이블에는 ``shared_root`` (그리고 동시
적용된 ``kms_root`` / ``agent_root``) 가 동시 기록된다.

실 DB 미적용 — 본 PR 은 multi-branch 파일 작성만. staging 검증 후 적용.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "shared_root"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = ("shared",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — branch label 부여만 수행."""
    pass


def downgrade() -> None:
    """No-op — branch label 해제만 수행."""
    pass
