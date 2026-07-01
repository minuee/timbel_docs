"""AuditLog ORM — append-only + sha256 row hash chain.

Phase 1.5A Task 8d: stub 였던 모델에 hash chain + guardrail 필드 추가.
"""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    SEARCH = "SEARCH"
    VIEW = "VIEW"
    DOWNLOAD = "DOWNLOAD"
    EXPORT = "EXPORT"
    SHARE = "SHARE"


class AuditResourceType(str, enum.Enum):
    DOCUMENT = "DOCUMENT"
    BLOCK = "BLOCK"
    REPOSITORY = "REPOSITORY"
    CATEGORY = "CATEGORY"
    USER = "USER"


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    # === legacy fields (004 / 011 마이그레이션) ===
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    user_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    action: Mapped[AuditAction | None] = mapped_column(
        Enum(AuditAction), index=True, nullable=True
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(100), index=True, nullable=True
    )
    resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # === Phase 1.5A Task 8d — guardrail extension ===
    # actor_id 는 user_id 와 동일 의미 (별칭) — 신규 코드는 actor_id 권장.
    actor_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    args_redacted: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # === Phase 1.5A Task 8d — sha256 hash chain ===
    prev_row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # === D24 §1 (alembic 076) — agent 단위 audit row 격리 메타 ===
    # owner_scope: 'admin' | 'agent' | 'role' | NULL (legacy pre-D24).
    # owner_agent_id: agent 가 produce 한 audit row 의 source agent FK.
    #   FK agents.id ON DELETE SET NULL — agent 삭제 시 row 보존.
    # NOTE: hash chain payload (_build_payload) 에 *불포함* — legacy row 와
    #   hash 호환 유지 (기존 verify_chain 그대로 통과).
    owner_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_agent_id: Mapped[UUID | None] = mapped_column(nullable=True)

    @property
    def actor_id(self) -> UUID | None:
        """actor_id 는 user_id 의 alias (신규 가드레일 용어)."""
        return self.user_id
