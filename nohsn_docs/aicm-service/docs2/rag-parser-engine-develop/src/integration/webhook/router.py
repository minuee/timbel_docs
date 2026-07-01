"""Webhook 관리 라우터 — 등록/목록/삭제."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.common.logging import get_logger
from src.integration.api_gateway.dependencies import get_db_session
from src.integration.webhook.models import (
    SUPPORTED_EVENTS,
    WebhookConfigORM,
    WebhookListItem,
    WebhookListResponse,
    WebhookRegisterRequest,
    WebhookRegisterResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@router.post(
    "",
    response_model=WebhookRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Webhook 등록",
)
async def register_webhook(
    request: WebhookRegisterRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WebhookRegisterResponse:
    """Webhook 등록. 지정된 이벤트 발생 시 URL로 HTTP POST 전송."""
    # 이벤트 유효성 검증
    invalid_events = set(request.events) - SUPPORTED_EVENTS
    if invalid_events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 이벤트: {invalid_events}. 지원: {sorted(SUPPORTED_EVENTS)}",
        )

    orm = WebhookConfigORM(
        tenant_id=tenant_id,
        url=request.url,
        events=request.events,
        secret=request.secret,
        description=request.description,
    )
    session.add(orm)
    await session.flush()

    log.info(
        "webhook_registered",
        webhook_id=str(orm.id),
        tenant_id=str(tenant_id),
        url=request.url[:80],
        events=request.events,
    )

    return WebhookRegisterResponse(
        webhook_id=orm.id,
        url=orm.url,
        events=orm.events,
        created_at=orm.created_at,
    )


@router.get(
    "",
    response_model=WebhookListResponse,
    summary="Webhook 목록 조회",
)
async def list_webhooks(
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WebhookListResponse:
    """테넌트의 활성 Webhook 목록 조회."""

    stmt = (
        select(WebhookConfigORM)
        .where(
            WebhookConfigORM.tenant_id == tenant_id,
            WebhookConfigORM.is_active.is_(True),
        )
        .order_by(WebhookConfigORM.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    items = [
        WebhookListItem(
            webhook_id=row.id,
            url=row.url,
            events=row.events,
            description=row.description,
            failure_count=row.failure_count,
            is_active=row.is_active,
            last_triggered_at=row.last_triggered_at,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return WebhookListResponse(webhooks=items)


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Webhook 삭제",
)
async def delete_webhook(
    webhook_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Webhook 비활성화 (소프트 삭제)."""

    stmt = (
        update(WebhookConfigORM)
        .where(
            WebhookConfigORM.id == webhook_id,
            WebhookConfigORM.tenant_id == tenant_id,
        )
        .values(is_active=False)
        .returning(WebhookConfigORM.id)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook을 찾을 수 없습니다.",
        )

    log.info("webhook_deleted", webhook_id=str(webhook_id))
