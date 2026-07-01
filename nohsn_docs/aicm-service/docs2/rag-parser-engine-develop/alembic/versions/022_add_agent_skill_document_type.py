"""add agent_skill document type + agent_framework_library repository

Revision ID: 022
Revises: 021
Create Date: 2026-04-24

Stage A — KMS-Plus 에이전트 스킬을 KMS 문서 체계로 승격.

- document_types 는 (tenant_id, name) 복합 UNIQUE 이므로 기본 tenant(UUID 0)
  에 'agent_skill' 타입을 추가.
- 스킬 전용 repository 'agent_framework_library' 도 같이 생성 (seed 스크립트는
  이 repo 안에 문서를 insert).
- agent_skill 타입 문서는 블록 파이프라인을 건너뛴다 (parse_worker 에서 early
  return). 본 migration 은 DB 행만 만든다.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    # 1) document_types.agent_skill (기본 tenant 기준)
    op.execute(
        f"""
        INSERT INTO document_types (id, tenant_id, name, description, is_system)
        SELECT gen_random_uuid(), '{DEFAULT_TENANT_ID}', 'agent_skill',
               'KMS-Plus 에이전트 프레임워크 스킬 정의 (YAML). '
               '블록 파이프라인 건너뜀 — processing_meta.yaml 에 원문 저장.',
               true
        WHERE NOT EXISTS (
            SELECT 1 FROM document_types
            WHERE tenant_id = '{DEFAULT_TENANT_ID}' AND name = 'agent_skill'
        );
        """
    )

    # 2) agent_framework_library repository (기본 tenant 기준)
    op.execute(
        f"""
        INSERT INTO repositories (id, tenant_id, name, description, search_mode, is_active)
        SELECT gen_random_uuid(), '{DEFAULT_TENANT_ID}',
               'agent_framework_library',
               'KMS-Plus 에이전트 스킬 전용 공유 라이브러리 (tenant-scoped 로 전환하기 전 단계)',
               'simple', true
        WHERE NOT EXISTS (
            SELECT 1 FROM repositories
            WHERE tenant_id = '{DEFAULT_TENANT_ID}' AND name = 'agent_framework_library'
        );
        """
    )


def downgrade() -> None:
    # 1) 해당 repo 소속 agent_skill 문서 제거 (blocks 는 FK CASCADE)
    op.execute(
        f"""
        DELETE FROM documents
        WHERE repository_id IN (
            SELECT id FROM repositories
            WHERE tenant_id = '{DEFAULT_TENANT_ID}' AND name = 'agent_framework_library'
        );
        """
    )
    # 2) repository 제거
    op.execute(
        f"""
        DELETE FROM repositories
        WHERE tenant_id = '{DEFAULT_TENANT_ID}' AND name = 'agent_framework_library';
        """
    )
    # 3) document_type 제거
    op.execute(
        f"""
        DELETE FROM document_types
        WHERE tenant_id = '{DEFAULT_TENANT_ID}' AND name = 'agent_skill';
        """
    )
