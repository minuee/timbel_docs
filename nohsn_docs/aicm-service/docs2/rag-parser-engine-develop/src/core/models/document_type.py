"""DocumentType ORM 모델."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.tenant import Tenant


class DocumentType(UUIDPrimaryKeyMixin, Base):
    """문서타입 모델. 문서의 용도와 성격을 구분하는 태그.

    시스템 기본 타입(guideline, script, manual, faq)과
    고객 정의 타입(sop, msds 등)을 지원한다.

    Attributes:
        tenant_id: 소속 테넌트 ID
        name: 문서타입 이름
        description: 문서타입 설명
        icon: UI 표시용 아이콘 코드
        is_system: 시스템 기본 타입 여부
    """

    __tablename__ = "document_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_document_types_tenant_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="document_types",
    )

    def __repr__(self) -> str:
        return f"<DocumentType(id={self.id}, name='{self.name}', is_system={self.is_system})>"


# 시스템 기본 문서타입 시드 데이터
SYSTEM_DOCUMENT_TYPES: list[dict[str, str | bool]] = [
    {
        "name": "guideline",
        "description": "업무 지침 — 공식 규정, 정책, 약관",
        "icon": "book-open",
        "is_system": True,
    },
    {
        "name": "script",
        "description": "스크립트 — 응대 대본, 안내 멘트",
        "icon": "message-square",
        "is_system": True,
    },
    {
        "name": "manual",
        "description": "매뉴얼 — 시스템 조작법, 절차 가이드",
        "icon": "file-text",
        "is_system": True,
    },
    {
        "name": "faq",
        "description": "FAQ — 자주 묻는 질문과 답변",
        "icon": "help-circle",
        "is_system": True,
    },
]
