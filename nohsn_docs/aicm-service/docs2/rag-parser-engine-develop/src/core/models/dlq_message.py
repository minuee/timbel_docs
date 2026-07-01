"""DLQ (Dead Letter Queue) 메시지 DB 모델.

인메모리 DLQ에서 DB 기반으로 전환하기 위한 영속 모델.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, UUIDPrimaryKeyMixin


class DLQMessageORM(UUIDPrimaryKeyMixin, Base):
    """DLQ 메시지 영속 모델.

    파이프라인 처리 중 실패한 Kafka 메시지를 DB에 기록한다.

    Attributes:
        topic: 원본 Kafka 토픽
        offset: 원본 Kafka 오프셋
        partition: 원본 Kafka 파티션
        payload: 원본 메시지 페이로드 (JSON 문자열)
        error: 에러 메시지
        error_traceback: 에러 트레이스백
        retry_count: 재시도 횟수
        status: pending / retried / discarded
    """

    __tablename__ = "dlq_messages"

    topic: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partition: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    error_traceback: Mapped[str] = mapped_column(Text, nullable=True, default="")
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    permanent_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DLQMessageORM(id={self.id}, topic='{self.topic}', "
            f"status='{self.status}', retries={self.retry_count})>"
        )
