"""Block ORM 모델 — 블럭 기반 파이프라인의 벡터화 단위.

specs/06_BLOCK_PIPELINE_REDESIGN.md 2.3 참조.
기존 Chunk 모델과 공존하며, use_block_pipeline 플래그에 따라 선택된다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.document import Document
    from src.core.models.repository import Repository


class Block(UUIDPrimaryKeyMixin, Base):
    """블럭 모델. 의미 완결 단위의 벡터화·검색·편집 단위.

    Attributes:
        document_id: 소속 문서 ID
        repository_id: 소속 저장소 ID (비정규화, 필터 성능)
        block_type: 블럭 유형 (Notion 호환: paragraph/heading_1/.../table/image/summary 등)
        content: 블럭 텍스트 (표는 마크다운)
        block_index: 문서 내 블럭 순서
        block_hash: SHA-256 해시 (변경 감지)
        token_count: 토큰 수
        source_location: 원본 문서 내 위치 정보 (JSONB)
        metadata: 블럭 타입별 부가 정보 (JSONB)
        vector_id: Qdrant point ID
        is_indexed: 벡터 인덱싱 완료 여부
    """

    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("document_id", "block_hash", name="uq_blocks_document_hash"),
        Index("ix_blocks_document_order", "document_id", "block_index"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id"),
        nullable=False,
        index=True,
    )
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_location: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    properties: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Notion 스타일 속성 (code language, callout icon 등)"
    )
    parent_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="중첩 블럭의 부모 블럭 ID (toggle, callout 등)",
    )
    meta_info: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=False
    )

    # Ontology columns (Phase A-5)
    nature: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="fact/opinion/schedule/record/reference/casual"
    )
    time_reference: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment='{"raw": "...", "resolved": "ISO", "basis": "..."}'
    )
    entities: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment='{"speakers": [], "people": [], "orgs": [], "locations": []}'
    )
    domain_category_ids: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment='도메인 카테고리 매핑 [{"id": "uuid", "confidence": 0.9}]'
    )
    validity_status: Mapped[str] = mapped_column(
        String(20), server_default="active", nullable=False, comment="active/superseded/expired"
    )
    classification_provenance: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="분류 추론 과정 (reasoning, model, confidence 등)"
    )
    anonymization_log: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="비식별화 이력",
    )
    validity_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="유효성 상태 변경 시각",
    )
    validity_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="유효성 변경 사유",
    )
    successor_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blocks.id"),
        nullable=True,
        comment="대체 블럭 ID (superseded 시)",
    )

    is_noise: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="true = noise block (excluded from search indexes)",
    )

    legal_hold: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="법적 보존 플래그 — true 시 삭제/비식별화 차단",
    )

    vector_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_indexed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    document: Mapped[Document] = relationship(
        "Document",
        back_populates="blocks",
        foreign_keys=[document_id],
    )
    repository: Mapped[Repository] = relationship("Repository")

    def __repr__(self) -> str:
        return (
            f"<Block(id={self.id}, type='{self.block_type}', "
            f"document_id={self.document_id}, index={self.block_index})>"
        )
