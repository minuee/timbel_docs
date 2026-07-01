"""KMS-Plus 스킬 관리 API — 로드된 스킬 목록 + YAML 뷰어 + per-account 토글.

v1 read-only 였던 /list, /yaml 에 더해 Stage B-Core-5 에서
`POST /{skill_id}/enable`, `POST /{skill_id}/disable` 추가.
토글 대상은 `phone` 으로 식별된 account 의 personal_tenant.

Stage A: env `AGENT_SKILLS_SOURCE=kms` 일 때 YAML 조회는 documents.processing_meta
에서 가져오고 응답에 document_id 를 포함. fs 모드는 기존 동작(디스크) 유지.

### 인증 / tenant isolation
v1 internal 데모 — phone 을 body/query 로 그대로 신뢰. real auth 는 이후 단계.
"""
from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.agent_framework.api.dependencies import (
    get_agent_engine,
    get_skill_registry,
)
from src.agent_framework.core.accounts import get_or_create_account
from src.agent_framework.core.skill_registry import SkillRegistry
from src.agent_framework.runtime.engine import SKILLS_DIR, AgentEngine
from src.agent_framework.runtime.kms_skill_loader import (
    AGENT_DOCTYPE_NAME,
    AGENT_REPO_NAME,
    DEFAULT_TENANT_ID,
)
from src.common.config import settings


router = APIRouter(prefix="/agent/skills", tags=["agent-skills"])


def _source() -> str:
    return os.environ.get("AGENT_SKILLS_SOURCE", "fs").lower()


async def _kms_lookup_all_ids(tenant_id: UUID = DEFAULT_TENANT_ID) -> dict[str, UUID]:
    """title(=skill_id) → document_id 매핑 반환."""
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT d.title, d.id
                        FROM documents d
                        JOIN document_types dt ON d.document_type_id = dt.id
                        JOIN repositories r ON d.repository_id = r.id
                        WHERE dt.name = :dt
                          AND r.name = :repo
                          AND r.tenant_id = :tid
                          AND d.status = 'active'
                        """
                    ),
                    {
                        "dt": AGENT_DOCTYPE_NAME,
                        "repo": AGENT_REPO_NAME,
                        "tid": tenant_id,
                    },
                )
            ).all()
        return {title: doc_id for title, doc_id in rows}
    finally:
        await engine.dispose()


async def _kms_lookup_yaml(
    skill_id: str, tenant_id: UUID = DEFAULT_TENANT_ID
) -> tuple[UUID, str] | None:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT d.id, d.processing_meta
                        FROM documents d
                        JOIN document_types dt ON d.document_type_id = dt.id
                        JOIN repositories r ON d.repository_id = r.id
                        WHERE dt.name = :dt
                          AND r.name = :repo
                          AND r.tenant_id = :tid
                          AND d.title = :title
                          AND d.status = 'active'
                        """
                    ),
                    {
                        "dt": AGENT_DOCTYPE_NAME,
                        "repo": AGENT_REPO_NAME,
                        "tid": tenant_id,
                        "title": skill_id,
                    },
                )
            ).first()
    finally:
        await engine.dispose()
    if not row:
        return None
    doc_id, meta = row
    yaml_text = (meta or {}).get("yaml")
    if not yaml_text:
        return None
    return doc_id, yaml_text


class _PhoneBody(BaseModel):
    """enable/disable 바디 — v1 데모 (auth 대체)."""

    phone: str


@router.get("/list")
async def list_skills(
    phone: str | None = None,
    engine: AgentEngine = Depends(get_agent_engine),
):
    """로드된 스킬 요약 리스트.

    - phone 없음: legacy 응답 (enabled/can_enable 등 미포함).
    - phone 있음: account 를 resolve 해서 per-account 토글 메타 추가.
        - enabled: 해당 personal_tenant (+ membership tenants) 에 enable 된 스킬인지
        - can_enable: personal tenant 에서 opt-in 가능한지 (scope != business_only)
        - visibility: auto | opt-in (UI 가 "자동" / "선택" 배지 구분에 사용)

    source=kms 일 때는 document_id 도 포함.
    """
    source = _source()
    id_map: dict[str, UUID] = {}
    if source == "kms":
        try:
            id_map = await _kms_lookup_all_ids()
        except Exception:
            id_map = {}

    # per-account augmentation prep
    enabled_ids: set[str] = set()
    if phone:
        try:
            account = await get_or_create_account(phone=phone)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"account resolve failed: {e}")
        skill_registry: SkillRegistry | None = getattr(
            engine, "skill_registry", None
        )
        if skill_registry is not None:
            try:
                enabled_list = (
                    await skill_registry.list_enabled_skill_ids_for_account(
                        account.account_id
                    )
                )
                enabled_ids = set(enabled_list)
            except Exception:
                # DB 실패 시 legacy 응답 유지 — UI 가 조회 실패를 부드럽게 다룸
                enabled_ids = set()

    out = []
    for s in engine.skills.values():
        item = {
            "id": s.meta.id,
            "version": s.meta.version,
            "domain": s.meta.domain,
            "description": s.meta.description,
            "triggers": [t.intent for t in s.triggers],
            "trigger_type": s.trigger_type,
            "schedule": s.schedule,
            "source": source,
        }
        if source == "kms":
            doc_id = id_map.get(s.meta.id)
            item["document_id"] = str(doc_id) if doc_id else None
        if phone:
            scope = s.availability.scope
            item["enabled"] = s.meta.id in enabled_ids
            item["can_enable"] = scope in ("personal", "all")
            item["visibility"] = s.availability.visibility
        out.append(item)
    return out


@router.get("/{skill_id}/yaml")
async def get_yaml(
    skill_id: str,
    engine: AgentEngine = Depends(get_agent_engine),
):
    """특정 스킬의 원본 YAML 반환.

    source=fs 면 디스크에서, source=kms 면 documents.processing_meta 에서 조회.
    """
    if skill_id not in engine.skills:
        raise HTTPException(404, f"skill {skill_id} not loaded")

    if _source() == "kms":
        res = await _kms_lookup_yaml(skill_id)
        if res is None:
            raise HTTPException(
                404, f"yaml for {skill_id} not found in KMS (source=kms)"
            )
        doc_id, yaml_text = res
        return {
            "skill_id": skill_id,
            "yaml": yaml_text,
            "source": "kms",
            "document_id": str(doc_id),
        }

    # fs 기본 동작
    path = SKILLS_DIR / f"{skill_id}.yaml"
    if not path.exists():
        raise HTTPException(404, f"yaml file not found: {path.name}")
    return {"skill_id": skill_id, "yaml": path.read_text(encoding="utf-8"), "source": "fs"}


@router.post("/{skill_id}/enable")
async def enable_skill(
    skill_id: str,
    body: _PhoneBody,
    engine: AgentEngine = Depends(get_agent_engine),
    registry: SkillRegistry = Depends(get_skill_registry),
):
    """Stage B-Core-5: phone 의 personal_tenant 에 skill opt-in.

    business_only 스킬은 personal tenant 에 enable 할 수 없으므로 400.
    idempotent — 이미 enable 되어 있어도 성공 (ON CONFLICT DO NOTHING).
    """
    skill = engine.skills.get(skill_id)
    if skill is None:
        raise HTTPException(404, f"skill {skill_id} not loaded")

    scope = skill.availability.scope
    if scope not in ("personal", "all"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "business_only skill cannot be enabled on personal tenant",
                "skill_id": skill_id,
                "hint": "이 스킬은 비즈니스 계정 관리자만 활성화할 수 있습니다",
            },
        )

    account = await get_or_create_account(phone=body.phone)
    await registry.enable_skill(
        tenant_id=account.personal_tenant_id,
        skill_id=skill_id,
        by_account_id=account.account_id,
    )
    return {
        "skill_id": skill_id,
        "enabled": True,
        "tenant_id": str(account.personal_tenant_id),
    }


@router.post("/{skill_id}/disable")
async def disable_skill(
    skill_id: str,
    body: _PhoneBody,
    engine: AgentEngine = Depends(get_agent_engine),
    registry: SkillRegistry = Depends(get_skill_registry),
):
    """Stage B-Core-5: phone 의 personal_tenant 에서 skill opt-out.

    이미 disable 된 상태여도 no-op 성공. DELETE 대신 POST 를 써 일부 HTTP
    클라이언트 (특히 브라우저 fetch 구형) 의 DELETE-body 이슈 회피.
    """
    if skill_id not in engine.skills:
        raise HTTPException(404, f"skill {skill_id} not loaded")

    account = await get_or_create_account(phone=body.phone)
    await registry.disable_skill(
        tenant_id=account.personal_tenant_id,
        skill_id=skill_id,
    )
    return {
        "skill_id": skill_id,
        "enabled": False,
        "tenant_id": str(account.personal_tenant_id),
    }
