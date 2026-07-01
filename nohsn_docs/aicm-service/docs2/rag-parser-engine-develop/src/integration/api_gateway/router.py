"""API Key 관리 라우터 + 사용량 조회."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.common.logging import get_logger
from src.integration.api_gateway.dependencies import get_api_key_manager, get_usage_tracker
from src.integration.api_gateway.models import (
    VALID_SCOPES,
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyListResponse,
)
from src.integration.api_gateway.usage_tracker import UsageStats

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/api-keys", tags=["API Keys"])


@router.post(
    "",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="API Key 발급",
)
async def create_api_key(
    request: APIKeyCreateRequest,
    tenant_id: UUID = None,  # TODO: JWT 인증에서 추출 (관리자용)
    tenant_slug: str = "default",  # TODO: JWT 인증에서 추출
    manager=Depends(get_api_key_manager),
) -> APIKeyCreateResponse:
    """API Key 발급. 원본 키는 응답에서 1회만 반환된다.

    관리자 UI에서 호출. tenant_id/slug는 JWT 인증 미들웨어에서 주입 예정.
    """
    # scope 유효성 검증
    invalid_scopes = set(request.scopes) - VALID_SCOPES
    if invalid_scopes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 scope: {invalid_scopes}. 허용: {VALID_SCOPES}",
        )

    # TODO: tenant_id를 JWT에서 추출하도록 변경. 임시로 헤더/쿼리에서 받음.
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    result = await manager.create_key(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        name=request.name,
        scopes=request.scopes,
        rate_limit=request.rate_limit,
        expires_at=request.expires_at,
    )
    return result


@router.get(
    "",
    response_model=APIKeyListResponse,
    summary="API Key 목록 조회",
)
async def list_api_keys(
    tenant_id: UUID = None,  # TODO: JWT 인증에서 추출
    manager=Depends(get_api_key_manager),
) -> APIKeyListResponse:
    """테넌트의 활성 API Key 목록 조회."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    keys = await manager.list_keys(tenant_id=tenant_id)
    return APIKeyListResponse(keys=keys)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="API Key 폐기",
)
async def revoke_api_key(
    key_id: UUID,
    tenant_id: UUID = None,  # TODO: JWT 인증에서 추출
    manager=Depends(get_api_key_manager),
) -> None:
    """API Key 비활성화 (소프트 삭제)."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id가 필요합니다.",
        )

    success = await manager.revoke_key(key_id=key_id, tenant_id=tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key를 찾을 수 없습니다.",
        )


@router.get(
    "/{key_id}/usage",
    response_model=UsageStats,
    summary="API Key 사용량 조회",
)
async def get_api_key_usage(
    key_id: UUID,
    period: str = "7d",
    tracker=Depends(get_usage_tracker),
) -> UsageStats:
    """API Key별 사용량 통계 조회."""
    if period not in {"1d", "7d", "30d", "90d"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period는 1d, 7d, 30d, 90d 중 하나여야 합니다.",
        )

    return await tracker.get_usage(key_id=key_id, period=period)
