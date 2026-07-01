"""동기화 소스 관리 라우터 — 등록/목록/트리거/상태."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.integration.api_gateway.dependencies import get_db_session
from src.integration.sync.models import (
    SyncSourceCreateRequest,
    SyncSourceListResponse,
    SyncSourceORM,
    SyncSourceResponse,
    SyncSourceType,
    SyncStatusResponse,
    SyncTriggerResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/sync/sources", tags=["Sync"])

# 스케줄러 인스턴스 (앱 시작 시 초기화)
_scheduler = None


def set_scheduler(scheduler) -> None:
    """앱 시작 시 스케줄러 인스턴스 설정."""
    global _scheduler
    _scheduler = scheduler


@router.post(
    "",
    response_model=SyncSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="동기화 소스 등록",
)
async def register_sync_source(
    request: SyncSourceCreateRequest,
    tenant_id: UUID | None = None,  # TODO: JWT 인증에서 추출
    session: AsyncSession = Depends(get_db_session),
) -> SyncSourceResponse:
    """외부 문서 소스(SharePoint, Confluence) 등록."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    # 소스 타입 유효성
    try:
        SyncSourceType(request.source_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원하지 않는 소스 타입: {request.source_type}. "
            f"지원: {[t.value for t in SyncSourceType]}",
        )

    orm = SyncSourceORM(
        tenant_id=tenant_id,
        repository_id=request.repository_id,
        name=request.name,
        source_type=request.source_type.value,
        config=request.config,
        schedule_cron=request.schedule_cron,
    )
    session.add(orm)
    await session.flush()

    log.info(
        "sync_source_registered",
        source_id=str(orm.id),
        tenant_id=str(tenant_id),
        name=request.name,
        source_type=request.source_type.value,
    )

    return SyncSourceResponse(
        id=orm.id,
        name=orm.name,
        source_type=orm.source_type,
        repository_id=orm.repository_id,
        config=orm.config,
        schedule_cron=orm.schedule_cron,
        created_at=orm.created_at,
    )


@router.get(
    "",
    response_model=SyncSourceListResponse,
    summary="동기화 소스 목록 조회",
)
async def list_sync_sources(
    tenant_id: UUID | None = None,  # TODO: JWT 인증에서 추출
    session: AsyncSession = Depends(get_db_session),
) -> SyncSourceListResponse:
    """테넌트의 활성 동기화 소스 목록."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    stmt = (
        select(SyncSourceORM)
        .where(
            SyncSourceORM.tenant_id == tenant_id,
            SyncSourceORM.is_active.is_(True),
        )
        .order_by(SyncSourceORM.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    sources = [
        SyncSourceResponse(
            id=row.id,
            name=row.name,
            source_type=row.source_type,
            repository_id=row.repository_id,
            config=row.config,
            schedule_cron=row.schedule_cron,
            last_synced_at=row.last_synced_at,
            last_status=row.last_status,
            last_error=row.last_error,
            total_synced=row.total_synced,
            is_active=row.is_active,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return SyncSourceListResponse(sources=sources)


@router.post(
    "/{source_id}/trigger",
    response_model=SyncTriggerResponse,
    summary="수동 동기화 트리거",
)
async def trigger_sync(
    source_id: UUID,
    tenant_id: UUID | None = None,  # TODO: JWT 인증에서 추출
    session: AsyncSession = Depends(get_db_session),
) -> SyncTriggerResponse:
    """동기화 소스의 수동 동기화 실행."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    # 소스 존재 확인
    source = await session.get(SyncSourceORM, source_id)
    if not source or source.tenant_id != tenant_id or not source.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="동기화 소스를 찾을 수 없습니다.",
        )

    if _scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="동기화 스케줄러가 초기화되지 않았습니다.",
        )

    message = await _scheduler.trigger_sync(source_id)

    log.info(
        "sync_manual_trigger",
        source_id=str(source_id),
        message=message,
    )

    return SyncTriggerResponse(
        source_id=source_id,
        status="triggered",
        message=message,
    )


@router.get(
    "/{source_id}/status",
    response_model=SyncStatusResponse,
    summary="동기화 상태 조회",
)
async def get_sync_status(
    source_id: UUID,
    tenant_id: UUID | None = None,  # TODO: JWT 인증에서 추출
    session: AsyncSession = Depends(get_db_session),
) -> SyncStatusResponse:
    """동기화 소스의 현재 상태 및 마지막 결과 조회."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    source = await session.get(SyncSourceORM, source_id)
    if not source or source.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="동기화 소스를 찾을 수 없습니다.",
        )

    return SyncStatusResponse(
        source_id=source.id,
        name=source.name,
        source_type=source.source_type,
        last_synced_at=source.last_synced_at,
        last_status=source.last_status,
        last_error=source.last_error,
        total_synced=source.total_synced,
        is_active=source.is_active,
    )
