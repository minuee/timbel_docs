"""Webhook ORM 모델 및 Pydantic 스키마."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


# ---------------------------------------------------------------------------
# 지원 이벤트 타입
# ---------------------------------------------------------------------------

class WebhookEventType(str, Enum):
    """지원 Webhook 이벤트 타입."""

    DOCUMENT_INDEXED = "document.indexed"
    DOCUMENT_FAILED = "document.failed"
    DOCUMENT_UPDATED = "document.updated"
    DOCUMENT_DELETED = "document.deleted"
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_PROCESSED = "document.processed"
    BLOCK_REVIEWED = "block.reviewed"
    SEARCH_NO_RESULT = "search.no_result"
    SEARCH_LOW_CONFIDENCE = "search.low_confidence"
    SEARCH_PERFORMED = "search.performed"
    RAG_PERFORMED = "rag.performed"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"


SUPPORTED_EVENTS = {e.value for e in WebhookEventType}


# ---------------------------------------------------------------------------
# SQLAlchemy ORM
# ---------------------------------------------------------------------------

class WebhookConfigORM(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Webhook 등록 테이블."""

    __tablename__ = "webhook_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    secret: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<WebhookConfigORM(id={self.id}, url='{self.url[:50]}', events={self.events})>"


# ---------------------------------------------------------------------------
# Pydantic 스키마
# ---------------------------------------------------------------------------

class WebhookRegisterRequest(BaseModel):
    """Webhook 등록 요청."""

    url: str = Field(..., min_length=10, max_length=2000)
    events: list[str] = Field(..., min_length=1)
    secret: str = Field(..., min_length=16, max_length=256)
    description: str | None = None


class WebhookRegisterResponse(BaseModel):
    """Webhook 등록 응답."""

    webhook_id: uuid.UUID
    url: str
    events: list[str]
    created_at: datetime


class WebhookListItem(BaseModel):
    """Webhook 목록 아이템."""

    webhook_id: uuid.UUID
    url: str
    events: list[str]
    description: str | None = None
    failure_count: int = 0
    is_active: bool = True
    last_triggered_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    """Webhook 목록 응답."""

    webhooks: list[WebhookListItem]


class WebhookDeadLetterORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Webhook Dead Letter Queue — 최종 전송 실패 이벤트 보관."""

    __tablename__ = "webhook_dead_letters"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_body: Mapped[str] = mapped_column(String, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<WebhookDeadLetterORM(id={self.id}, webhook_id={self.webhook_id}, "
            f"event_type='{self.event_type}')>"
        )


# ---------------------------------------------------------------------------
# Pydantic 스키마
# ---------------------------------------------------------------------------

class WebhookEvent(BaseModel):
    """Webhook 이벤트 페이로드."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    timestamp: datetime
    tenant_id: uuid.UUID
    payload: dict
