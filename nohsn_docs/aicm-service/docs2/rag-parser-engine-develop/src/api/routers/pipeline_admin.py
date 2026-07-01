"""Pipeline Admin API -- DLQ 관리 엔드포인트.

Phase 3: DLQ 메시지 조회, 재시도, 폐기 API.
DB 기반으로 전환 — 인메모리 핸들러가 없어도 DB에서 직접 조회 가능.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.database import get_db
from src.core.models.dlq_message import DLQMessageORM

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/pipeline")


# ---------------------------------------------------------------------------
# 응답 스키마
# ---------------------------------------------------------------------------

class DLQMessageResponse(BaseModel):
    """DLQ 메시지 응답."""

    msg_id: str
    original_topic: str
    error_message: str
    error_traceback: str | None = None
    retry_count: int
    created_at: str
    updated_at: str
    status: str
    original_offset: int
    original_partition: int


class DLQListResponse(BaseModel):
    """DLQ 목록 응답."""

    success: bool = True
    data: list[DLQMessageResponse]
    total: int


class DLQDetailResponse(BaseModel):
    """DLQ 상세 응답."""

    success: bool = True
    data: DLQMessageResponse
    payload: str | None = None


class DLQRetryResponse(BaseModel):
    """DLQ 재시도 응답."""

    success: bool
    msg_id: str
    message: str


class DLQDiscardResponse(BaseModel):
    """DLQ 폐기 응답."""

    success: bool
    msg_id: str
    message: str


class DLQRetryAllResponse(BaseModel):
    """DLQ 전체 재시도 응답."""

    success: bool = True
    republished: int
    failed: int
    permanent: int
    skipped: int
    message: str


class DLQStatsResponse(BaseModel):
    """DLQ 통계 응답."""

    success: bool = True
    total: int
    pending: int
    retried: int
    discarded: int
    permanent_failure: int
    retryable: int


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _get_dlq_handler():
    """글로벌 DLQ 핸들러를 가져온다 (있으면)."""
    try:
        from src.pipeline.workers.main import get_dlq_handler
        return get_dlq_handler()
    except Exception:
        return None


def _orm_to_response(m: DLQMessageORM) -> DLQMessageResponse:
    """DB ORM 모델을 응답 스키마로 변환한다."""
    return DLQMessageResponse(
        msg_id=str(m.id),
        original_topic=m.topic,
        error_message=m.error,
        error_traceback=m.error_traceback,
        retry_count=m.retry_count,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
        status=m.status,
        original_offset=m.offset,
        original_partition=m.partition,
    )


# ---------------------------------------------------------------------------
# 엔드포인트 (고정 경로를 먼저 정의하여 {msg_id} 와 충돌 방지)
# ---------------------------------------------------------------------------

@router.post("/dlq/retry-all", response_model=DLQRetryAllResponse, tags=["파이프라인 관리"])
async def retry_all_dlq_messages() -> DLQRetryAllResponse:
    """재처리 가능한 모든 DLQ 메시지를 즉시 원본 토픽으로 재발행한다.

    permanent_failure 이거나 retry_count >= 5 인 메시지는 제외된다.
    Kafka producer 가 사용 가능하면 실제 재발행, 아니면 DB 상태만 변경한다.
    """
    from src.pipeline.workers.dlq_scheduler import retry_all_eligible

    # Kafka producer 가져오기 시도
    handler = _get_dlq_handler()
    producer = handler._producer if handler is not None else None

    stats = await retry_all_eligible(producer=producer)

    return DLQRetryAllResponse(
        republished=stats["republished"],
        failed=stats["failed"],
        permanent=stats["permanent"],
        skipped=stats.get("skipped", 0),
        message=f"{stats['republished']}개 메시지 재발행 완료, {stats['failed']}개 실패, {stats['permanent']}개 영구 실패 처리.",
    )


@router.get("/dlq/stats", response_model=DLQStatsResponse, tags=["파이프라인 관리"])
async def get_dlq_stats_endpoint() -> DLQStatsResponse:
    """DLQ 메시지 상태별 통계를 반환한다."""
    from src.pipeline.workers.dlq_scheduler import get_dlq_stats

    stats = await get_dlq_stats()

    return DLQStatsResponse(**stats)


@router.get("/dlq", response_model=DLQListResponse, tags=["파이프라인 관리"])
async def list_dlq_messages(
    status: str | None = Query(None, description="필터: pending / retried / discarded"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DLQListResponse:
    """DLQ 메시지 목록을 조회한다 (DB 기반)."""
    stmt = select(DLQMessageORM)
    count_stmt = select(func.count()).select_from(DLQMessageORM)

    if status:
        stmt = stmt.where(DLQMessageORM.status == status)
        count_stmt = count_stmt.where(DLQMessageORM.status == status)

    stmt = stmt.order_by(DLQMessageORM.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    total = (await db.execute(count_stmt)).scalar() or 0

    return DLQListResponse(
        data=[_orm_to_response(m) for m in rows],
        total=total,
    )


@router.get("/dlq/{msg_id}", response_model=DLQDetailResponse, tags=["파이프라인 관리"])
async def get_dlq_message(
    msg_id: str,
    db: AsyncSession = Depends(get_db),
) -> DLQDetailResponse:
    """특정 DLQ 메시지를 조회한다 (페이로드 포함)."""
    from uuid import UUID

    stmt = select(DLQMessageORM).where(DLQMessageORM.id == UUID(msg_id))
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()

    if msg is None:
        raise HTTPException(status_code=404, detail=f"DLQ 메시지를 찾을 수 없습니다: {msg_id}")

    return DLQDetailResponse(
        data=_orm_to_response(msg),
        payload=msg.payload,
    )


@router.post("/dlq/{msg_id}/retry", response_model=DLQRetryResponse, tags=["파이프라인 관리"])
async def retry_dlq_message(
    msg_id: str,
    db: AsyncSession = Depends(get_db),
) -> DLQRetryResponse:
    """DLQ 메시지를 원본 토픽으로 재발행한다.

    인메모리 핸들러가 있으면 Kafka 재발행을 시도하고,
    없으면 DB 상태만 retried로 변경한다.
    """
    from uuid import UUID

    handler = _get_dlq_handler()

    if handler is not None:
        success = await handler.retry_message(msg_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"DLQ 메시지 재시도에 실패했습니다: {msg_id}",
            )
    else:
        # DB 상태만 업데이트
        stmt = (
            update(DLQMessageORM)
            .where(DLQMessageORM.id == UUID(msg_id))
            .values(status="retried")
            .returning(DLQMessageORM.id)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"DLQ 메시지를 찾을 수 없습니다: {msg_id}",
            )

    return DLQRetryResponse(
        success=True,
        msg_id=msg_id,
        message="메시지가 원본 토픽으로 재발행되었습니다.",
    )


@router.delete("/dlq/{msg_id}", response_model=DLQDiscardResponse, tags=["파이프라인 관리"])
async def discard_dlq_message(
    msg_id: str,
    db: AsyncSession = Depends(get_db),
) -> DLQDiscardResponse:
    """DLQ 메시지를 폐기한다."""
    from uuid import UUID

    handler = _get_dlq_handler()

    if handler is not None:
        handler.discard_message(msg_id)

    # DB 상태도 업데이트
    stmt = (
        update(DLQMessageORM)
        .where(DLQMessageORM.id == UUID(msg_id))
        .values(status="discarded")
        .returning(DLQMessageORM.id)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None and handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"DLQ 메시지를 찾을 수 없습니다: {msg_id}",
        )

    return DLQDiscardResponse(
        success=True,
        msg_id=msg_id,
        message="메시지가 폐기되었습니다.",
    )
