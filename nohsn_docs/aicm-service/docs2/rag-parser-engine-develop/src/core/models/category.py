"""Category ORM 모델."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, SoftDeleteMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.repository import Repository


class Category(UUIDPrimaryKeyMixin, SoftDeleteMixin, Base):
    """카테고리 모델. 저장소 내 업무/직무별 분류 체계.

    다단계 계층 구조를 지원하며 (parent_id 자기 참조),
    하나의 문서가 복수 카테고리에 속할 수 있다 (N:M).

    Attributes:
        repository_id: 소속 저장소 ID
        name: 카테고리 이름
        description: 카테고리 설명
        parent_id: 상위 카테고리 ID (다단계 계층)
        sort_order: 정렬 순서
    """

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "name", "parent_id", name="uq_categories_repo_name_parent"
        ),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id"),
        nullable=True,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- 버전 관리 컬럼 ---
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False,
        comment="카테고리 버전 (스키마/분류체계 변경 시 증가)",
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=True,
        comment="현재 버전 적용 시점",
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="폐기(deprecated) 시점 — 설정 시 신규 분류에서 제외",
    )
    successor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id"),
        nullable=True,
        comment="후속 카테고리 ID (deprecated 시 대체 카테고리)",
    )

    # --- 온톨로지 확장 컬럼 (Phase A-1) ---
    synonyms: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True,
        comment="동의어 목록 (자동 분류 시 매칭용)",
    )
    embedding: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="카테고리 임베딩 벡터 (1024d, JSON 배열)",
    )
    auto_classify: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False,
        comment="자동 분류 대상 여부",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    repository: Mapped[Repository] = relationship(
        "Repository",
        back_populates="categories",
    )
    parent: Mapped[Category | None] = relationship(
        "Category",
        remote_side="Category.id",
        foreign_keys="[Category.parent_id]",
        back_populates="children",
        lazy="joined",
    )
    children: Mapped[list[Category]] = relationship(
        "Category",
        foreign_keys="[Category.parent_id]",
        back_populates="parent",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}', parent_id={self.parent_id})>"
