"""AnonymizationLog ORM 모델 — 익명화 이력 추적."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class AnonymizationLog(UUIDPrimaryKeyMixin, Base):
    """익명화 이력 모델.

    Level 1-3의 익명화 작업에 대해 원본 데이터를 보관하여 되돌리기를 지원한다.
    Level 4(완전 삭제)는 원본을 보관하지 않으며 되돌리기 불가.

    Attributes:
        block_id: 대상 블럭 ID
        tenant_id: 테넌트 ID
        level: 익명화 레벨 (1-4)
        original_content: 원본 콘텐츠 (Level 1-3)
        original_entities: 원본 엔터티 데이터
        anonymized_content: 익명화된 콘텐츠
        performed_at: 수행 시각
        reverted_at: 되돌리기 시각 (None=미되돌림)
        performed_by: 수행자 사용자 ID
    """

    __tablename__ = "anonymization_logs"

    block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="익명화 레벨: 1=이름 대체, 2=엔터티 제거, 3=맥락 제거, 4=완전 삭제",
    )
    original_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="원본 콘텐츠 (Level 1-3에서 되돌리기용)",
    )
    original_entities: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="원본 엔터티 데이터",
    )
    anonymized_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="익명화 후 콘텐츠",
    )
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    reverted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    performed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    # Relationships
    block = relationship("Block", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<AnonymizationLog(id={self.id}, block_id={self.block_id}, "
            f"level={self.level}, reverted={'yes' if self.reverted_at else 'no'})>"
        )
