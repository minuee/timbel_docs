"""KMS document store 에서 agent_skill 타입 문서 로드.

fs loader (load_all_skills) 와 같은 dict[str, Skill] 시그니처를 반환.
env `AGENT_SKILLS_SOURCE=kms` 시 `dependencies._build_engine` 에서 사용.

documents.processing_meta 에 YAML 전문을 넣어 둔 구조(seed_agent_skills 참조)
를 전제로 한다. documents 테이블에 content/body 컬럼이 없는 KMS 스키마에
맞춘 선택.
"""
from __future__ import annotations

from uuid import UUID

import yaml
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.agent_framework.runtime.schema import Skill
from src.common.logging import get_logger

log = get_logger(__name__)

DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")
AGENT_REPO_NAME = "agent_framework_library"
AGENT_DOCTYPE_NAME = "agent_skill"


async def load_all_skills_from_kms(
    engine: AsyncEngine,
    *,
    tenant_id: UUID = DEFAULT_TENANT_ID,
    repository_name: str = AGENT_REPO_NAME,
    document_type_name: str = AGENT_DOCTYPE_NAME,
) -> dict[str, Skill]:
    """agent_skill 타입 문서 전부 로드 → Skill 객체 딕셔너리.

    Parameters
    ----------
    engine : AsyncEngine
        SQLAlchemy async engine (settings.DATABASE_URL 기반 권장)
    tenant_id : UUID
        기본 tenant (공유 library). tenant-scoped 커스텀 스킬 단계에서 확장.
    """
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT d.id, d.title, d.processing_meta
                    FROM documents d
                    JOIN document_types dt ON d.document_type_id = dt.id
                    JOIN repositories r ON d.repository_id = r.id
                    WHERE dt.name = :dt_name
                      AND r.tenant_id = :tid
                      AND r.name = :repo_name
                      AND d.status = 'active'
                    ORDER BY d.title
                    """
                ),
                {
                    "dt_name": document_type_name,
                    "tid": tenant_id,
                    "repo_name": repository_name,
                },
            )
        ).all()

    skills: dict[str, Skill] = {}
    for doc_id, title, processing_meta in rows:
        if not processing_meta:
            log.warning("kms_skill_missing_meta", doc_id=str(doc_id), title=title)
            continue
        yaml_text = processing_meta.get("yaml")
        if not yaml_text:
            log.warning(
                "kms_skill_missing_yaml_in_meta", doc_id=str(doc_id), title=title
            )
            continue
        try:
            raw = yaml.safe_load(yaml_text)
            skill = Skill.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            log.error(
                "kms_skill_load_failed",
                doc_id=str(doc_id),
                title=title,
                error=str(exc),
            )
            continue
        skills[skill.meta.id] = skill
        log.debug(
            "kms_skill_loaded", skill=skill.meta.id, doc_id=str(doc_id), title=title
        )
    log.info(
        "kms_skills_loaded",
        count=len(skills),
        tenant_id=str(tenant_id),
        repo=repository_name,
    )
    return skills
