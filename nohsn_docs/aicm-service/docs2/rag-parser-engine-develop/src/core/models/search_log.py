"""SearchLog ORM 모델."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class SearchLog(UUIDPrimaryKeyMixin, Base):
    """검색 로그 모델. 검색 품질 모니터링 및 분석에 활용.

    Attributes:
        tenant_id: 테넌트 ID
        repository_id: 저장소 ID (선택)
        query: 검색 쿼리
        query_source: 검색 소스 (admin_ui / advisor / callbot / chatbot / api)
        result_count: 검색 결과 수
        top_chunk_ids: 상위 결과 청크 ID 배열
        top_scores: 상위 결과 스코어 배열
        latency_ms: 검색 소요 시간 (ms)
        user_feedback: 사용자 피드백 (helpful / not_helpful / null)
    """

    __tablename__ = "search_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
    top_scores: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<SearchLog(id={self.id}, query='{self.query[:30]}...', results={self.result_count})>"
