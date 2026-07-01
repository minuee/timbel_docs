"""IntentLog ORM 모델 — LLM 기반 검색 필요성 분류 결과 축적.

이후 이 로그를 기반으로 룰 필터/소형 전용 분류기를 자동 학습하기 위한 피드백 데이터 소스.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class IntentLog(UUIDPrimaryKeyMixin, Base):
    """사용자 발화의 검색 필요성 분류 로그.

    Attributes:
        tenant_id: 테넌트 ID (nullable — 익명 API 콜도 있음)
        query: 현재 사용자 발화
        conversation_history: 이전 대화 턴 배열 (jsonb)
        search_decision: LLM 분류 결과 (True=검색 필요, False=일상 대화)
        reason: LLM 이 제시한 분류 사유
        latency_ms: 분류 LLM 호출 소요 시간
        model_used: 분류에 사용된 LLM 모델명
        user_feedback: 선택적 사용자 피드백 (agree / disagree). 오분류 수집용.
    """

    __tablename__ = "intent_logs"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_history: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    search_decision: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(200), nullable=True)
    user_feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<IntentLog(id={self.id}, search={self.search_decision}, query='{self.query[:30]}')>"
