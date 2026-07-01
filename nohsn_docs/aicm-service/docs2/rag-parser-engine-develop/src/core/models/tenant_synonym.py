"""TenantSynonym ORM 모델."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class TenantSynonym(Base):
    """테넌트별 동의어 사전.

    tenant_synonyms 테이블 — 동의어 검색 시 term → synonyms 매칭에 사용.
    ORM 등록 목적: create_all 경로에서 테이블을 생성하기 위함.
    """

    __tablename__ = "tenant_synonyms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "term", name="uq_tenant_synonyms_tenant_term"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        server_default=func.gen_random_uuid(),
        primary_key=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
