"""skill_drafts API — Task 36 Phase A.

사용자가 채팅에서 "이런 기능 만들어 줘" 라고 요청하면 엔진이 draft 를 만들어
DB 에 쌓는다. 이 라우터는 검토·승인 관리 엔드포인트를 제공한다 (UI 는 Phase B).

경로:
- GET    /agent/skill_drafts?phone=...             — account 가 소유한 draft 목록
- GET    /agent/skill_drafts/{id}                  — 상세 (yaml + rationale)
- POST   /agent/skill_drafts/{id}/approve          — 승인 → active skill 로 promote
- POST   /agent/skill_drafts/{id}/reject           — 거절
- DELETE /agent/skill_drafts/{id}                  — 관리자 / cleanup

**인증**: v1 internal — phone 을 body/query 로 받아 account 를 resolve.

### Approve flow
1. draft.yaml 파싱 → Skill pydantic 검증.
2. ``agent_document_store.create_item`` 로 documents 에 agent_skill 삽입.
3. SkillRegistry.enable_skill 로 personal tenant 에 활성화.
4. draft.status='approved' + reviewed_by/at 기록.
5. 엔진 메모리에는 다음 재시작(또는 cache clear) 때 반영됨 — 응답 note 로 고지.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from src.agent_framework.api.dependencies import (
    _get_or_create_db_engine,
    get_agent_engine,
    get_skill_registry,
)
from src.agent_framework.core.accounts import get_or_create_account
from src.agent_framework.core.skill_registry import SkillRegistry
from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.schema import Skill
from src.agent_framework.storage import agent_document_store, skill_draft_store
from src.agent_framework.storage.skill_draft_store import SkillDraft
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/agent/skill_drafts", tags=["agent-skill-drafts"])


class _PhoneBody(BaseModel):
    phone: str


class RejectBody(BaseModel):
    """반려 요청 body. ``reason`` 은 검토자가 입력한 사유 (선택)."""

    phone: str
    reason: str | None = None


class CreateDraftBody(BaseModel):
    """신규 draft 등록 body — '신규 YAML' UI 에서 사용.

    - ``yaml`` 은 필수, 비어있지 않아야 함.
    - ``title`` 미지정 시 yaml 의 ``meta.id`` 또는 'untitled' 로 fallback.
    - ``phone`` 은 body 또는 ?phone= 쿼리 둘 중 하나로 받는다 (호환성).
    """

    phone: str | None = None
    title: str | None = None
    yaml: str
    rationale: str | None = None


@router.get("")
async def list_drafts(
    phone: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """account 의 draft 목록. status 필터 선택적."""
    if status is not None and status not in skill_draft_store.VALID_STATUSES:
        raise HTTPException(
            400,
            f"invalid status {status!r}; must be one of "
            f"{sorted(skill_draft_store.VALID_STATUSES)}",
        )
    try:
        account = await get_or_create_account(phone=phone)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"account resolve failed: {e}")
    engine = _get_or_create_db_engine()
    rows = await skill_draft_store.list_by_account(
        engine, account.account_id, status=status
    )
    return rows


@router.post("")
async def create_draft(
    body: CreateDraftBody,
    phone: str | None = None,
) -> dict[str, Any]:
    """신규 skill draft 등록 (검토 큐로 들어감).

    프론트의 '신규 YAML' 탭에서 호출. account 의 personal_tenant 에 pending 으로
    insert 되며, 이후 검토자(본인 또는 관리자)가 approve/reject 한다.
    """
    actor_phone = body.phone or phone
    if not actor_phone:
        raise HTTPException(
            400, "phone is required (body.phone or ?phone= query)"
        )
    if not body.yaml or not body.yaml.strip():
        raise HTTPException(400, "yaml is required and non-empty")

    # YAML 형식만 가볍게 검증 (approve 시 Skill schema 로 풀 검증). 등록 단계에서
    # 너무 엄격히 거르면 사용자가 점진적으로 다듬는 흐름을 막는다.
    try:
        parsed = yaml.safe_load(body.yaml)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"yaml parse failed: {e}")
    if parsed is not None and not isinstance(parsed, dict):
        raise HTTPException(400, "yaml root must be a mapping")

    # title fallback: body.title → meta.id → 'untitled'
    title = (body.title or "").strip()
    if not title:
        meta = (parsed or {}).get("meta") if isinstance(parsed, dict) else None
        if isinstance(meta, dict) and isinstance(meta.get("id"), str):
            title = meta["id"]
    if not title:
        title = "untitled"
    # draft_title 은 VARCHAR(200) 제약.
    title = title[:200]

    try:
        account = await get_or_create_account(phone=actor_phone)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"account resolve failed: {e}")

    db_engine = _get_or_create_db_engine()
    draft = SkillDraft(
        title=title,
        yaml_text=body.yaml,
        rationale=body.rationale,
    )
    try:
        new_id = await skill_draft_store.create(
            db_engine,
            draft,
            account_id=account.account_id,
            tenant_id=account.personal_tenant_id,
            session_id=None,
            source_user_message="(manual yaml upload via UI)",
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "skill_draft_create_failed",
            phone=actor_phone,
            error=str(e),
        )
        raise HTTPException(500, f"draft create failed: {e}")

    log.info(
        "skill_draft_created_via_ui",
        draft_id=str(new_id),
        account_id=str(account.account_id),
        tenant_id=str(account.personal_tenant_id),
        title=title,
    )

    row = await skill_draft_store.get(db_engine, new_id)
    if row is None:  # 직후 조회 실패는 실질적으로 발생하지 않지만 방어.
        raise HTTPException(500, "draft created but immediate fetch returned None")
    return row


@router.get("/{draft_id}")
async def get_draft(draft_id: UUID) -> dict[str, Any]:
    engine = _get_or_create_db_engine()
    row = await skill_draft_store.get(engine, draft_id)
    if row is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    return row


def _parse_skill_from_yaml(yaml_text: str) -> Skill:
    """approve 단계에서 YAML → Skill 검증. 실패는 400."""
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"yaml parse failed: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(400, "yaml root must be a mapping")
    try:
        return Skill.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(400, f"skill schema invalid: {e}")


@router.post("/{draft_id}/approve")
async def approve_draft(
    draft_id: UUID,
    body: _PhoneBody,
    engine_: AgentEngine = Depends(get_agent_engine),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict[str, Any]:
    """Approve a draft:

    1. 검증된 YAML 로 agent_skill document 생성
    2. personal_tenant 에 활성화 (enable_skill)
    3. draft.status='approved'
    """
    db_engine = _get_or_create_db_engine()
    draft = await skill_draft_store.get(db_engine, draft_id)
    if draft is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    if draft["status"] != "pending":
        raise HTTPException(
            409,
            f"draft already {draft['status']}; only 'pending' can be approved",
        )

    skill = _parse_skill_from_yaml(draft["draft_yaml"])

    try:
        reviewer = await get_or_create_account(phone=body.phone)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"account resolve failed: {e}")

    tenant_id = UUID(draft["tenant_id"])

    # 1. KMS documents 에 agent_skill row 삽입 (kms_skill_loader 규약과 호환).
    doc_id = await agent_document_store.create_item(
        db_engine,
        tenant_id,
        "agent_skill",
        title=skill.meta.id,
        body={"yaml": draft["draft_yaml"]},
    )

    # 2. tenant 에 활성화
    await registry.enable_skill(
        tenant_id=tenant_id,
        skill_id=skill.meta.id,
        by_account_id=reviewer.account_id,
    )

    # 3. draft 상태 전환
    ok = await skill_draft_store.update_status(
        db_engine,
        draft_id,
        "approved",
        reviewer_account_id=reviewer.account_id,
    )
    if not ok:
        log.warning("skill_draft_status_update_noop", draft_id=str(draft_id))

    # 4. 엔진 메모리 맵은 프로세스 재시작 시 재로드. in-place reload 는 Phase B.
    _reload_engine_cache()
    log.info(
        "skill_draft_approved",
        draft_id=str(draft_id),
        skill_id=skill.meta.id,
        document_id=str(doc_id),
        tenant_id=str(tenant_id),
    )

    return {
        "status": "approved",
        "skill_id": skill.meta.id,
        "document_id": str(doc_id),
        "tenant_id": str(tenant_id),
        "active": True,
        "note": "새 기능은 다음 API 재시작 시 활성화됩니다.",
    }


@router.post("/{draft_id}/reject")
async def reject_draft(
    draft_id: UUID,
    body: RejectBody,
) -> dict[str, Any]:
    db_engine = _get_or_create_db_engine()
    draft = await skill_draft_store.get(db_engine, draft_id)
    if draft is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    if draft["status"] != "pending":
        raise HTTPException(
            409,
            f"draft already {draft['status']}; only 'pending' can be rejected",
        )

    try:
        reviewer = await get_or_create_account(phone=body.phone)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"account resolve failed: {e}")

    reason = (body.reason or "").strip() or None
    ok = await skill_draft_store.update_status(
        db_engine,
        draft_id,
        "rejected",
        reviewer_account_id=reviewer.account_id,
        reject_reason=reason,
    )
    log.info(
        "skill_draft_rejected",
        draft_id=str(draft_id),
        reviewer=str(reviewer.account_id),
        has_reason=reason is not None,
        ok=ok,
    )
    return {
        "status": "rejected",
        "draft_id": str(draft_id),
        "reject_reason": reason,
        "ok": ok,
    }


@router.delete("/{draft_id}")
async def delete_draft(draft_id: UUID) -> dict[str, Any]:
    """관리자 / cleanup. rejected/expired row 를 완전히 지우고 싶을 때."""
    db_engine = _get_or_create_db_engine()
    ok = await skill_draft_store.delete(db_engine, draft_id)
    if not ok:
        raise HTTPException(404, f"draft {draft_id} not found")
    log.info("skill_draft_deleted", draft_id=str(draft_id))
    return {"deleted": True, "draft_id": str(draft_id)}


def _reload_engine_cache() -> None:
    """``_build_engine`` lru_cache 를 clear — 다음 turn 요청 때 재로드 유발.

    Phase A 한정: skill 맵이 새 스킬을 포함하도록 프로세스 재시작 대신 캐시만 비움.
    in-place skill map 갱신은 Phase B 범위.
    """
    try:
        from src.agent_framework.api import dependencies

        dependencies._build_engine.cache_clear()
        log.info("agent_engine_cache_cleared_for_new_skill")
    except Exception as e:  # noqa: BLE001
        log.warning("agent_engine_cache_clear_failed", error=str(e))
