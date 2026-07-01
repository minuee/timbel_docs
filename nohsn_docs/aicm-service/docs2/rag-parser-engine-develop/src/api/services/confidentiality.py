"""기밀 등급(Confidentiality Level) 관리 서비스.

문서의 processing_meta JSONB에 confidentiality_level 을 저장하여
마이그레이션 없이 기밀 등급을 관리한다.
감사 추적(audit trail)은 processing_meta['confidentiality_history'] 에 누적된다.

등급별 접근 제어:
  - public: 테넌트 내 모든 사용자
  - internal: guest(api_consumer) 제외 전원
  - confidential: editor + admin
  - restricted: admin only
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.models.document import Document
from src.core.models.user import UserRole

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 기밀 등급 정의
# ---------------------------------------------------------------------------


class ConfidentialityLevel(str, enum.Enum):
    """기밀 등급."""

    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


# 등급별 최소 요구 역할 매핑
LEVEL_MIN_ROLE: dict[ConfidentialityLevel, UserRole] = {
    ConfidentialityLevel.public: UserRole.api_consumer,     # 모든 사용자
    ConfidentialityLevel.internal: UserRole.viewer,          # guest 제외
    ConfidentialityLevel.confidential: UserRole.editor,      # editor + admin
    ConfidentialityLevel.restricted: UserRole.tenant_admin,  # admin only
}


# ---------------------------------------------------------------------------
# 응답 스키마
# ---------------------------------------------------------------------------


class ConfidentialityAuditEntry(BaseModel):
    """기밀 등급 변경 이력 항목."""

    changed_at: str
    changed_by: UUID | None = None
    old_level: str | None = None
    new_level: str
    reason: str


class ConfidentialityResponse(BaseModel):
    """기밀 등급 조회 응답."""

    document_id: UUID
    level: str = Field(default="internal")
    history: list[ConfidentialityAuditEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 서비스 함수
# ---------------------------------------------------------------------------


async def get_confidentiality(
    document_id: UUID,
    db: AsyncSession,
) -> ConfidentialityResponse:
    """문서의 현재 기밀 등급 및 변경 이력을 반환한다."""
    from src.core.exceptions import DocumentNotFoundError

    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError(str(document_id))

    meta: dict[str, Any] = doc.processing_meta or {}
    level = meta.get("confidentiality_level", "internal")
    raw_history = meta.get("confidentiality_history", [])

    history = [
        ConfidentialityAuditEntry(**entry)
        for entry in raw_history
    ]

    return ConfidentialityResponse(
        document_id=doc.id,
        level=level,
        history=history,
    )


async def set_confidentiality(
    document_id: UUID,
    level: ConfidentialityLevel,
    reason: str,
    changed_by: UUID | None,
    db: AsyncSession,
) -> ConfidentialityResponse:
    """문서의 기밀 등급을 변경하고 이력을 기록한다.

    Args:
        document_id: 문서 ID
        level: 새 기밀 등급
        reason: 변경 사유
        changed_by: 변경 수행자 UUID
        db: 비동기 DB 세션

    Returns:
        변경 후 ConfidentialityResponse
    """
    from src.core.exceptions import DocumentNotFoundError

    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError(str(document_id))

    meta: dict[str, Any] = dict(doc.processing_meta or {})
    old_level = meta.get("confidentiality_level", "internal")

    # 이력 항목 추가
    history: list[dict[str, Any]] = list(meta.get("confidentiality_history", []))
    history.append({
        "changed_at": datetime.utcnow().isoformat(),
        "changed_by": str(changed_by) if changed_by else None,
        "old_level": old_level,
        "new_level": level.value,
        "reason": reason,
    })

    meta["confidentiality_level"] = level.value
    meta["confidentiality_history"] = history

    doc.processing_meta = meta
    await db.flush()

    logger.info(
        "confidentiality_level_changed",
        document_id=str(document_id),
        old_level=old_level,
        new_level=level.value,
        changed_by=str(changed_by) if changed_by else None,
    )

    return ConfidentialityResponse(
        document_id=doc.id,
        level=level.value,
        history=[ConfidentialityAuditEntry(**e) for e in history],
    )


def can_access_document(user_role: UserRole, confidentiality_level: str) -> bool:
    """사용자 역할이 해당 기밀 등급의 문서에 접근 가능한지 확인한다.

    Args:
        user_role: 사용자 역할
        confidentiality_level: 문서 기밀 등급

    Returns:
        접근 가능 여부
    """
    from src.core.models.user import ROLE_HIERARCHY, role_gte

    try:
        level = ConfidentialityLevel(confidentiality_level)
    except ValueError:
        # 알 수 없는 등급은 internal 기본값으로 처리
        level = ConfidentialityLevel.internal

    min_role = LEVEL_MIN_ROLE[level]
    return role_gte(user_role, min_role)
