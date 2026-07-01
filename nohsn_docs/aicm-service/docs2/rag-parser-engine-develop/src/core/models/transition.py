"""최소 TransitionEvent/LifecyclePolicy 스텁 — cascade_analyzer 참조용."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class TransitionEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transition_events"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LifecyclePolicy(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lifecycle_policies"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
