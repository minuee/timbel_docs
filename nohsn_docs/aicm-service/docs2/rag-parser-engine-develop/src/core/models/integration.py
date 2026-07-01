"""Integration ORM 모델 — 외부 서비스 연동 레지스트리."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.tenant import Tenant


# 지원하는 연동 유형 정의
INTEGRATION_TYPES: dict[str, dict[str, str]] = {
    "google_calendar": {"name": "Google Calendar", "icon": "calendar", "auth": "oauth2"},
    "slack": {"name": "Slack", "icon": "message", "auth": "oauth2"},
    "gmail": {"name": "Gmail", "icon": "mail", "auth": "oauth2"},
    "confluence": {"name": "Confluence", "icon": "file", "auth": "api_key"},
    "notion": {"name": "Notion", "icon": "file", "auth": "api_key"},
    "custom_webhook": {"name": "Custom Webhook", "icon": "webhook", "auth": "url"},
}


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """외부 서비스 연동 레지스트리 모델.

    테넌트별로 외부 서비스(Google Calendar, Slack, Confluence 등)와의
    연동을 관리한다.

    Attributes:
        tenant_id: 소속 테넌트 ID
        integration_type: 연동 유형 (google_calendar, slack, gmail, confluence, notion, custom_webhook)
        name: 연동 표시 이름
        config: 연결 설정 (암호화된 자격 증명 참조)
        status: 연동 상태 (inactive, active, error)
        last_sync_at: 마지막 동기화 시각
        sync_frequency: 동기화 주기 (manual, hourly, daily)
        error_message: 마지막 오류 메시지
    """

    __tablename__ = "integrations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    integration_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    config: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="inactive", nullable=False,
        comment="inactive, active, error",
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    sync_frequency: Mapped[str] = mapped_column(
        String(20), server_default="manual", nullable=False,
        comment="manual, hourly, daily",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(1000), nullable=True,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<Integration(id={self.id}, type='{self.integration_type}', "
            f"status='{self.status}')>"
        )
