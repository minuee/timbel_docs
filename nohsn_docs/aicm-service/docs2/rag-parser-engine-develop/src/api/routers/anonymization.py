"""익명화 API 라우터 — 블럭 비식별화 및 되돌리기."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.models.block import Block
from src.pipeline.services.anonymizer import (
    AnonymizationResult,
    Anonymizer,
    RevertResult,
)

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 요청 스키마
# ---------------------------------------------------------------------------


class AnonymizeRequest(BaseModel):
    """익명화 요청."""

    block_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    level: int = Field(..., ge=1, le=4, description="익명화 레벨 (1-4)")
    tenant_id: UUID
    performed_by: UUID | None = Field(default=None, description="수행자 사용자 ID")
    confirm_level4: bool = Field(
        default=False,
        description="Level 4 (완전 삭제) 확인 플래그. Level 4 요청 시 반드시 True.",
    )


class RevertRequest(BaseModel):
    """되돌리기 요청."""

    block_ids: list[UUID] = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/anonymize",
    response_model=ApiResponse[AnonymizationResult],
    summary="블럭 익명화",
    description=(
        "지정된 블럭을 선택한 레벨로 익명화한다.\n\n"
        "- Level 1: 이름 대체 (홍길동 -> 사용자A)\n"
        "- Level 2: 엔터티 제거 (이름, 조직, 장소 삭제)\n"
        "- Level 3: 맥락 제거 (블럭 내용을 요약으로 대체)\n"
        "- Level 4: 완전 삭제 (블럭 + 벡터 + ES 인덱스 삭제) — 비가역적\n\n"
        "Level 1-3은 되돌리기 가능. Level 4는 confirm_level4=True 필수."
    ),
)
async def anonymize_blocks(
    body: AnonymizeRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AnonymizationResult]:
    """블럭을 익명화한다."""
    # Level 4 안전 장치
    if body.level == 4 and not body.confirm_level4:
        raise HTTPException(
            status_code=400,
            detail=(
                "Level 4 (완전 삭제)는 비가역적입니다. "
                "confirm_level4=true를 설정하여 확인해 주세요."
            ),
        )

    # 법적 보존 플래그 확인 — legal_hold=True 블럭은 익명화 차단
    from sqlalchemy import select
    from src.core.models.block import Block as BlockModel

    held_stmt = (
        select(BlockModel.id)
        .where(BlockModel.id.in_(body.block_ids), BlockModel.legal_hold.is_(True))
    )
    held_result = await db.execute(held_stmt)
    held_ids = {row[0] for row in held_result.fetchall()}

    if held_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                f"법적 보존(legal_hold) 상태인 블럭이 포함되어 있습니다. "
                f"해당 블럭은 익명화할 수 없습니다: {[str(h) for h in held_ids]}"
            ),
        )

    anonymizer = Anonymizer(db)
    result = await anonymizer.anonymize(
        block_ids=body.block_ids,
        level=body.level,
        tenant_id=body.tenant_id,
        performed_by=body.performed_by,
    )

    logger.info(
        "anonymization_completed",
        level=body.level,
        total=result.total,
        success=result.success_count,
        failed=result.failed_count,
    )
    return ApiResponse(data=result)


@router.post(
    "/revert",
    response_model=ApiResponse[RevertResult],
    summary="익명화 되돌리기",
    description=(
        "Level 1-3 익명화를 되돌린다. "
        "anonymization_log에 보관된 원본 콘텐츠를 복원한다.\n\n"
        "Level 4 (완전 삭제)는 되돌리기 불가."
    ),
)
async def revert_anonymization(
    body: RevertRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevertResult]:
    """익명화를 되돌린다."""
    anonymizer = Anonymizer(db)
    result = await anonymizer.revert(block_ids=body.block_ids)

    logger.info(
        "anonymization_reverted",
        total=result.total,
        reverted=result.reverted_count,
        irreversible=result.irreversible_count,
    )
    return ApiResponse(data=result)


@router.get(
    "/blocks",
    response_model=ApiResponse,
    summary="익명화 대상 블럭 목록",
)
async def list_anonymizable_blocks(
    repository_id: UUID | None = Query(None),
    status: str | None = Query(None, description="anonymized / original"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """테넌트의 블럭 중 익명화 가능/완료된 블럭 목록을 반환한다."""
    from src.core.models.repository import Repository

    # 테넌트 소속 저장소 필터
    repo_stmt = select(Repository.id).where(Repository.tenant_id == tenant_id)
    if repository_id:
        repo_stmt = repo_stmt.where(Repository.id == repository_id)

    stmt = (
        select(Block)
        .where(Block.repository_id.in_(repo_stmt))
        .order_by(Block.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    count_stmt = (
        select(func.count())
        .select_from(Block)
        .where(Block.repository_id.in_(repo_stmt))
    )

    if status == "anonymized":
        stmt = stmt.where(Block.meta_info["anonymization_log"].isnot(None))
        count_stmt = count_stmt.where(Block.meta_info["anonymization_log"].isnot(None))

    total = (await db.execute(count_stmt)).scalar() or 0
    result = await db.execute(stmt)
    blocks = result.scalars().all()

    items = []
    for b in blocks:
        meta = b.meta_info or {}
        items.append({
            "block_id": str(b.id),
            "document_id": str(b.document_id),
            "block_type": b.block_type,
            "content_preview": (b.content or "")[:100],
            "nature": b.nature,
            "validity_status": b.validity_status,
            "has_pii": bool(meta.get("entities")),
            "anonymization_level": meta.get("anonymization_log", {}).get("level") if meta.get("anonymization_log") else None,
        })

    return ApiResponse(data={"total": total, "blocks": items})
