from __future__ import annotations
from uuid import UUID, uuid4
from sqlalchemy import Boolean, ForeignKey, Text, LargeBinary, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID, JSONB as PgJSONB
from sqlalchemy.orm import Mapped, mapped_column
from src.core.models.base import Base, TimestampMixin


class CustomTool(Base, TimestampMixin):
    __tablename__ = "custom_tools"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="custom")
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False, default="POST")
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    input_schema: Mapped[dict] = mapped_column(PgJSONB, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(PgJSONB, nullable=False, default=dict)
    # Phase 1.5A — admin 이 등록 시 입력하는 거버넌스 메타 (risk_tier, approval,
    # rate_limit, budget 등). dispatcher/guardrail 이 의사결정에 활용.
    risk_metadata: Mapped[dict] = mapped_column(
        PgJSONB, nullable=False, default=dict, server_default="{}"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="custom_tools_tenant_name_uq"),
        CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
            name="custom_tools_method_check",
        ),
    )
