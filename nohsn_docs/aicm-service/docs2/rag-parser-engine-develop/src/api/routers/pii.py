"""PII 스캐너 API 라우터.

문서의 블럭 콘텐츠에서 개인식별정보(PII)를 탐지하고,
탐지 결과를 조회/해결(오탐 처리 또는 익명화 연계)하는 엔드포인트를 제공한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.schemas.common import ApiResponse
from src.api.services.pii_scanner import PIIMatch, PIIScanResult, scan_document
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.audit_log import AuditAction
from src.core.models.document import Document
from src.core.models.repository import Repository
from src.core.models.user import UserRole
from src.core.services.audit_service import fire_and_forget_audit

logger = get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory PII 결과 저장소 (프로덕션에서는 DB 테이블로 전환)
# ---------------------------------------------------------------------------

_scan_results: dict[uuid.UUID, PIIScanResult] = {}


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class PIIResolveRequest(BaseModel):
    """PII 매칭 해결 요청."""

    action: str = Field(
        ...,
        description="해결 액션: false_positive(오탐 처리) 또는 anonymize(익명화 연계)",
    )
    reason: str = Field(
        default="",
        max_length=500,
        description="해결 사유",
    )


class PIIResolveResponse(BaseModel):
    """PII 매칭 해결 응답."""

    match_id: uuid.UUID
    action: str
    resolved: bool = True
    resolved_at: str


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/pii-scan",
    response_model=ApiResponse[PIIScanResult],
    summary="PII 스캔 실행",
    description=(
        "문서의 모든 블럭 콘텐츠에서 PII (주민등록번호, 전화번호, 이메일, "
        "신용카드번호, 계좌번호, 영문 이름 등)를 정규식으로 탐지한다."
    ),
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def trigger_pii_scan(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    user_id: uuid.UUID | None = Depends(get_current_user_id),
) -> ApiResponse[PIIScanResult]:
    """문서의 PII 스캔을 실행한다."""
    # 테넌트 격리 확인: 문서 소속 저장소가 현재 테넌트 소속인지
    doc_stmt = (
        select(Document)
        .join(Repository, Document.repository_id == Repository.id)
        .where(Document.id == document_id, Repository.tenant_id == tenant_id)
    )
    doc_result = await db.execute(doc_stmt)
    if doc_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    result = await scan_document(document_id, db)

    # 결과 캐시 (in-memory)
    _scan_results[document_id] = result

    # 감사 로그
    fire_and_forget_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        resource_type="pii_scan",
        resource_id=document_id,
        new_value={
            "total_blocks_scanned": result.total_blocks_scanned,
            "total_matches": result.total_matches,
        },
    )

    logger.info(
        "pii_scan_triggered",
        document_id=str(document_id),
        matches=result.total_matches,
    )

    return ApiResponse(data=result)


@router.get(
    "/documents/{document_id}/pii-matches",
    response_model=ApiResponse[PIIScanResult],
    summary="PII 탐지 결과 조회",
    description="최근 스캔 결과의 PII 매칭 목록을 반환한다.",
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def list_pii_matches(
    document_id: uuid.UUID,
    pattern_type: str | None = Query(None, description="PII 유형 필터"),
    resolved: bool | None = Query(None, description="해결 상태 필터"),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[PIIScanResult]:
    """문서의 PII 탐지 결과를 반환한다."""
    # 테넌트 격리
    doc_stmt = (
        select(Document.id)
        .join(Repository, Document.repository_id == Repository.id)
        .where(Document.id == document_id, Repository.tenant_id == tenant_id)
    )
    doc_result = await db.execute(doc_stmt)
    if doc_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    cached = _scan_results.get(document_id)
    if cached is None:
        # 스캔 결과가 없으면 빈 결과 반환
        return ApiResponse(
            data=PIIScanResult(
                document_id=document_id,
                total_blocks_scanned=0,
                total_matches=0,
                matches=[],
            )
        )

    # 필터 적용
    matches = cached.matches
    if pattern_type is not None:
        matches = [m for m in matches if m.pattern_type == pattern_type]
    if resolved is not None:
        matches = [m for m in matches if m.resolved == resolved]

    filtered = PIIScanResult(
        document_id=cached.document_id,
        total_blocks_scanned=cached.total_blocks_scanned,
        total_matches=len(matches),
        matches=matches,
        scanned_at=cached.scanned_at,
    )
    return ApiResponse(data=filtered)


@router.post(
    "/documents/{document_id}/pii-matches/{match_id}/resolve",
    response_model=ApiResponse[PIIResolveResponse],
    summary="PII 매칭 해결",
    description=(
        "탐지된 PII 매칭을 오탐(false_positive)으로 처리하거나 "
        "익명화(anonymize)를 트리거한다."
    ),
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def resolve_pii_match(
    document_id: uuid.UUID,
    match_id: uuid.UUID,
    body: PIIResolveRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    user_id: uuid.UUID | None = Depends(get_current_user_id),
) -> ApiResponse[PIIResolveResponse]:
    """PII 매칭을 해결(오탐 또는 익명화)한다."""
    if body.action not in ("false_positive", "anonymize"):
        raise HTTPException(
            status_code=400,
            detail="action은 'false_positive' 또는 'anonymize' 중 하나여야 합니다.",
        )

    cached = _scan_results.get(document_id)
    if cached is None:
        raise HTTPException(status_code=404, detail="스캔 결과가 없습니다. 먼저 PII 스캔을 실행하세요.")

    # 매칭 찾기
    target_match: PIIMatch | None = None
    for m in cached.matches:
        if m.match_id == match_id:
            target_match = m
            break

    if target_match is None:
        raise HTTPException(status_code=404, detail="해당 PII 매칭을 찾을 수 없습니다.")

    # 해결 처리
    target_match.resolved = True
    target_match.resolved_action = body.action

    # 감사 로그
    fire_and_forget_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        resource_type="pii_match",
        resource_id=document_id,
        new_value={
            "match_id": str(match_id),
            "action": body.action,
            "reason": body.reason,
            "pattern_type": target_match.pattern_type,
        },
    )

    logger.info(
        "pii_match_resolved",
        document_id=str(document_id),
        match_id=str(match_id),
        action=body.action,
    )

    return ApiResponse(
        data=PIIResolveResponse(
            match_id=match_id,
            action=body.action,
            resolved=True,
            resolved_at=datetime.utcnow().isoformat(),
        )
    )
