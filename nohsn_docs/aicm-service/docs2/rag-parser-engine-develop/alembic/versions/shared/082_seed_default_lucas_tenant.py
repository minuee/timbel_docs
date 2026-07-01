"""Phase 2 Fix A — Lucas-KMS default tenant idempotent seed.

Revision ID: 082_seed_default_lucas_tenant
Revises: shared_root
Create Date: 2026-05-19

목적 (2026-05-19 사용자 무인증 모드 결정):
- ``LUCAS_AUTH_DISABLED=true`` 모드에서 ``get_current_principal`` /
  ``get_current_tenant_id`` 가 반환하는 default tenant_id
  (``00000000-0000-0000-0000-000000000001``) 가 DB 에 *존재* 해야 함.
- 부재 시 default tenant 로 동작하는 모든 INSERT (repositories, documents,
  audit_logs, ...) 가 FK 위반으로 500. 무인증 모드 사용성 망가짐.

설계:
- ``ON CONFLICT (id) DO NOTHING`` — idempotent. 재실행/multi-deploy 안전.
- 모든 NOT NULL 컬럼 (name, slug, config, plan, tenant_type, context_config,
  feature_flags) 명시. live DB 의 ``\d tenants`` 검증 결과 기반.
- ``id`` 는 명시 — gen_random_uuid() 가 아닌 *고정* UUID (settings 의
  LUCAS_DEFAULT_TENANT_ID 와 동기). 하드코딩 회피 원칙 예외 — idempotent
  seed 는 명시적 default 식별 필요.
- downgrade — 운영 안전상 *조건부* delete (자식 row 부재 시만 — 회귀 방지).

branch (multi-branch transition):
- ``tenants`` 는 *shared* 도메인 (spec §7) → shared branch 의 첫 자손.
- ``down_revision="shared_root"`` — 081 + shared_root 위에 빌드.
- 단일 head 인 legacy linear 환경 (``080``) 에서도 alembic 이 shared_root → 082
  순서로 자동 적용. multi-branch 전환 검증 후 staging 적용.

실 DB 적용 절차:
1. ``alembic upgrade head`` (staging) — 080 → 081 → shared_root/kms_root/
   agent_root → 082 순서 자동.
2. ``SELECT * FROM tenants WHERE id = '00000000-...001';`` — 1 row 확인.
3. ``LUCAS_AUTH_DISABLED=true`` 로 API 호출 → repository INSERT 성공 확인.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "082_seed_default_lucas_tenant"
down_revision: Union[str, None] = "shared_root"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Default Lucas-KMS tenant — settings.LUCAS_DEFAULT_TENANT_ID 와 동기.
# 변경 시 src/common/config.py 도 함께 수정.
# ---------------------------------------------------------------------------
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_NAME = "Lucas-KMS Default"
DEFAULT_TENANT_SLUG = "lucas-kms-default"
DEFAULT_TENANT_TYPE = "system"
DEFAULT_TENANT_PLAN = "standard"


def upgrade() -> None:
    """Default tenant idempotent INSERT.

    NOT NULL 컬럼 명시:
    - id, name, slug, tenant_type, plan: 명시 값
    - config, context_config, feature_flags: 빈 jsonb '{}' (default 부재)
    - is_active: server_default true (생략 시 자동)
    - created_at, updated_at: server_default now() (생략 시 자동)
    """
    op.execute(
        f"""
        INSERT INTO tenants (
            id, name, slug, config, plan, tenant_type, context_config, feature_flags
        ) VALUES (
            '{DEFAULT_TENANT_ID}',
            '{DEFAULT_TENANT_NAME}',
            '{DEFAULT_TENANT_SLUG}',
            '{{}}'::jsonb,
            '{DEFAULT_TENANT_PLAN}',
            '{DEFAULT_TENANT_TYPE}',
            '{{}}'::jsonb,
            '{{}}'::jsonb
        )
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    """자식 row 부재 시에만 default tenant 삭제 — 운영 안전.

    repositories / documents 등 FK 자식이 1 row 라도 있으면 SKIP (no-op).
    회귀 우려 0 — admin 이 명시적으로 cleanup 후 재실행 가능.
    """
    op.execute(
        f"""
        DO $$
        DECLARE
            child_count int;
        BEGIN
            -- 직접 FK 참조 4 table 중 가장 빈번한 것만 체크 (repositories).
            SELECT COUNT(*) INTO child_count
            FROM repositories
            WHERE tenant_id = '{DEFAULT_TENANT_ID}';

            IF child_count = 0 THEN
                DELETE FROM tenants WHERE id = '{DEFAULT_TENANT_ID}';
                RAISE NOTICE 'Default Lucas-KMS tenant 제거 완료.';
            ELSE
                RAISE NOTICE 'Default tenant 제거 SKIP — repositories 자식 %% row 존재.', child_count;
            END IF;
        END $$;
        """
    )
