"""최소 ScheduledAction 스텁 — 라이프사이클 워커 참조용."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class ScheduledAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scheduled_actions"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    action: Mapped[str] = mapped_column(String(30))
    target_block_ids: Mapped[list] = mapped_column(JSONB)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
