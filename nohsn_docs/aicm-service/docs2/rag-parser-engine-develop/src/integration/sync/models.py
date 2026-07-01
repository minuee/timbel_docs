"""동기화 커넥터 ORM 모델 및 Pydantic 스키마."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SyncSourceType(str, Enum):
    """동기화 소스 유형."""

    SHAREPOINT = "sharepoint"
    CONFLUENCE = "confluence"


class SyncStatus(str, Enum):
    """동기화 상태."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# SQLAlchemy ORM
# ---------------------------------------------------------------------------


class SyncSourceORM(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """동기화 소스 등록 테이블."""

    __tablename__ = "sync_sources"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schedule_cron: Mapped[str] = mapped_column(
        String(100), nullable=False, default="*/5 * * * *"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SyncStatus.IDLE.value
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_synced: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return (
            f"<SyncSourceORM(id={self.id}, name='{self.name}', "
            f"type='{self.source_type}')>"
        )


class SyncMappingORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """원격 문서 ↔ AICM 문서 매핑 테이블."""

    __tablename__ = "sync_mappings"

    sync_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    remote_id: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    remote_name: Mapped[str] = mapped_column(String(500), nullable=False)
    remote_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<SyncMappingORM(remote_id='{self.remote_id}', "
            f"document_id={self.document_id})>"
        )


# ---------------------------------------------------------------------------
# Pydantic 스키마 — API 요청/응답
# ---------------------------------------------------------------------------


class RemoteDocumentMeta(BaseModel):
    """원격 문서 메타데이터."""

    remote_id: str
    name: str
    modified_at: datetime | None = None
    size_bytes: int | None = None
    mime_type: str | None = None
    download_url: str | None = None


class SyncSourceCreateRequest(BaseModel):
    """동기화 소스 등록 요청."""

    name: str = Field(..., min_length=1, max_length=300)
    source_type: SyncSourceType
    repository_id: uuid.UUID
    config: dict = Field(default_factory=dict)
    schedule_cron: str = Field(default="*/5 * * * *", max_length=100)


class SyncSourceResponse(BaseModel):
    """동기화 소스 응답."""

    id: uuid.UUID
    name: str
    source_type: str
    repository_id: uuid.UUID
    config: dict
    schedule_cron: str
    last_synced_at: datetime | None = None
    last_status: str = SyncStatus.IDLE.value
    last_error: str | None = None
    total_synced: int = 0
    is_active: bool = True
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class SyncSourceListResponse(BaseModel):
    """동기화 소스 목록 응답."""

    sources: list[SyncSourceResponse]


class SyncTriggerResponse(BaseModel):
    """동기화 트리거 응답."""

    source_id: uuid.UUID
    status: str
    message: str


class SyncStatusResponse(BaseModel):
    """동기화 상태 조회 응답."""

    source_id: uuid.UUID
    name: str
    source_type: str
    last_synced_at: datetime | None = None
    last_status: str
    last_error: str | None = None
    total_synced: int = 0
    is_active: bool = True
