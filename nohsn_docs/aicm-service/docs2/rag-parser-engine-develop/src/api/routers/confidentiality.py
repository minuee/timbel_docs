"""기밀 등급(Confidentiality Level) 관리 API 라우터.

문서의 기밀 등급을 조회/변경하고, 변경 이력(audit trail)을 제공한다.
tenant_admin 전용.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.schemas.common import ApiResponse
from src.api.services.confidentiality import (
    ConfidentialityLevel,
    ConfidentialityResponse,
    get_confidentiality,
    set_confidentiality,
)
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.audit_log import AuditAction
from src.core.models.user import UserRole
from src.core.services.audit_service import fire_and_forget_audit

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 요청 스키마
# ---------------------------------------------------------------------------


class ConfidentialityUpdateRequest(BaseModel):
    """기밀 등급 변경 요청."""

    level: ConfidentialityLevel = Field(..., description="새 기밀 등급")
    reason: str = Field(
        ..., min_length=1, max_length=500, description="변경 사유"
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}/confidentiality",
    response_model=ApiResponse[ConfidentialityResponse],
    summary="문서 기밀 등급 조회",
    description="현재 기밀 등급 및 변경 이력(audit trail)을 반환한다.",
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def get_document_confidentiality(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ConfidentialityResponse]:
    """문서의 기밀 등급을 조회한다."""
    result = await get_confidentiality(document_id, db)
    return ApiResponse(data=result)


@router.patch(
    "/documents/{document_id}/confidentiality",
    response_model=ApiResponse[ConfidentialityResponse],
    summary="문서 기밀 등급 변경",
    description=(
        "문서의 기밀 등급을 변경한다. tenant_admin 전용.\n\n"
        "- public: 테넌트 내 모든 사용자 접근 가능\n"
        "- internal: guest 제외 전원 (기본값)\n"
        "- confidential: editor + admin만\n"
        "- restricted: admin만"
    ),
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def update_document_confidentiality(
    document_id: UUID,
    body: ConfidentialityUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
) -> ApiResponse[ConfidentialityResponse]:
    """문서의 기밀 등급을 변경한다."""
    # 기존 등급 조회 (감사 로그용)
    old = await get_confidentiality(document_id, db)

    result = await set_confidentiality(
        document_id=document_id,
        level=body.level,
        reason=body.reason,
        changed_by=user_id,
        db=db,
    )

    # 감사 로그 (fire-and-forget)
    fire_and_forget_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        resource_type="document_confidentiality",
        resource_id=document_id,
        old_value={"level": old.level},
        new_value={"level": result.level, "reason": body.reason},
    )

    return ApiResponse(data=result)
