"""최소 Tenant 스텁 — 파이프라인 FK 참조 + relationship용."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.document_type import DocumentType
    from src.core.models.repository import Repository


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    plan: Mapped[str] = mapped_column(String(50), default="standard")
    tenant_type: Mapped[str] = mapped_column(String(20), default="corporate")
    context_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 2026-05-07 (alembic 073) — runtime feature flag toggle.
    # env 변수가 kill-switch 우선 — DB 는 env unset 일 때만 권위.
    # admin UI 토글 → PATCH /api/v1/admin/settings/feature-flags 가 jsonb_set 원자 업데이트.
    feature_flags: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Relationships (back_populates from child models)
    document_types: Mapped[list[DocumentType]] = relationship(back_populates="tenant")
    repositories: Mapped[list[Repository]] = relationship(back_populates="tenant")
