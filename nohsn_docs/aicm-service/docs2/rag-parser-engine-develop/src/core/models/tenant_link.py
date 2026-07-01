"""최소 TenantLink 스텁 — 크로스 테넌트 검색 참조용."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class TenantLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tenant_links"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    personal_tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    corporate_tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    user_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    corporate_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    link_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
