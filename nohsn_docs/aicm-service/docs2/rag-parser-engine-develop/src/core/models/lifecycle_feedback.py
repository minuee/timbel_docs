"""최소 LifecycleFeedback 스텁 — 블럭/피드백 라우터 참조용."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class LifecycleFeedback(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lifecycle_feedback"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    block_id: Mapped[UUID] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    feedback_type: Mapped[str] = mapped_column(String(20), default="correction")
    reason: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
