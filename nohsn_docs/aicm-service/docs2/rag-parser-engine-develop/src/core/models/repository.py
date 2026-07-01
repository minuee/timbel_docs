"""Repository ORM 모델."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.agent import Agent
    from src.core.models.category import Category
    from src.core.models.document import Document
    from src.core.models.tenant import Tenant


class Repository(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """저장소 모델. 테넌트 내 최상위 격리 공간.

    저장소 간 검색은 절대 교차하지 않는다.
    생성 시 Qdrant 컬렉션 + Elasticsearch 인덱스가 자동 생성된다.

    Attributes:
        tenant_id: 소속 테넌트 ID
        name: 저장소 이름
        description: 저장소 설명
        config: 저장소별 검색/파이프라인 설정 오버라이드
    """

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_repositories_tenant_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)

    # --- Phase 1.5E (alembic 065) — agent 전용 namespace 격리 컬럼 ---
    # agent_id NULL = 공용 repo (admin 만 접근). FK ON DELETE SET NULL — agent
    # 삭제 시 자료 보존 + 공용 demote. 동일 tenant 안 role agent 는 자기 agent_id
    # 매칭 + NULL 만 접근 (knowledge_isolation 별 strict/priority/broad 분기).
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=False,  # 별도 partial index (alembic 065) 가 cover.
        comment="소유 agent. NULL = 공용 repo.",
    )
    namespace: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="agents.repo_namespace 와 sync. UI grouping / 검색 결과 표기.",
    )

    # --- 온톨로지 확장 컬럼 (Phase A-1) ---
    search_mode: Mapped[str] = mapped_column(
        String(20), server_default="simple", nullable=False,
        comment="검색 모드: simple/ontology/hybrid",
    )
    display_config: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False,
        comment="UI 표시 설정 (카테고리 트리 노출, 필터 등)",
    )
    llm_config: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False,
        comment="LLM 설정 (모델, 프롬프트 오버라이드 등)",
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="repositories",
    )
    categories: Mapped[list[Category]] = relationship(
        "Category",
        back_populates="repository",
        lazy="selectin",
    )
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="repository",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<Repository(id={self.id}, name='{self.name}')>"
