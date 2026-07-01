"""LLM 사용량/비용 추적 ORM 모델."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class LLMUsage(UUIDPrimaryKeyMixin, Base):
    """LLM 호출 사용량 및 비용 기록.

    Attributes:
        tenant_id: 소속 테넌트 ID
        model: 사용한 모델명 (e.g., claude-opus-4-6, gpt-4o)
        task: 호출 용도 (e.g., stage1_understand, stage3_enrich, classify)
        input_tokens: 입력 토큰 수
        output_tokens: 출력 토큰 수
        latency_ms: 응답 지연 (밀리초)
        cost_usd: 추정 비용 (USD)
        document_id: 관련 문서 ID (선택적)
    """

    __tablename__ = "llm_usage"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    task: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<LLMUsage(id={self.id}, model='{self.model}', "
            f"task='{self.task}', tokens={self.input_tokens}+{self.output_tokens})>"
        )
