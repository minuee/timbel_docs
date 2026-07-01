"""대용량 문서 분할 작업 추적기.

Redis 기반으로 파트 완료 상태를 추적한다.
모든 파트가 완료되면 merge_worker가 블럭을 통합한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

_SPLIT_JOB_TTL = 7200  # 2시간 TTL


class SplitJob(BaseModel):
    """대용량 문서 분할 작업 상태."""

    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    total_parts: int
    completed_parts: list[int] = Field(default_factory=list)
    failed_parts: list[int] = Field(default_factory=list)
    page_ranges: list[list[int]] = Field(default_factory=list)
    minio_source_key: str = ""
    source_path: str = ""
    status: Literal[
        "splitting", "processing", "merging", "completed", "failed"
    ] = "splitting"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SplitTracker:
    """Redis 기반 분할 작업 추적기."""

    def __init__(self) -> None:
        self._redis: object | None = None

    async def _get_redis(self) -> object:
        """Redis 연결을 반환한다."""
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        return self._redis

    def _key(self, document_id: UUID) -> str:
        return f"aicm:split_job:{document_id}"

    async def create_job(self, job: SplitJob) -> None:
        """분할 작업을 Redis에 생성한다."""
        r = await self._get_redis()
        key = self._key(job.document_id)
        await r.set(key, job.model_dump_json(), ex=_SPLIT_JOB_TTL)  # type: ignore[union-attr]
        log.info(
            "split_job_created",
            document_id=str(job.document_id),
            total_parts=job.total_parts,
        )

    async def get_job(self, document_id: UUID) -> Optional[SplitJob]:
        """분할 작업 상태를 조회한다."""
        r = await self._get_redis()
        raw = await r.get(self._key(document_id))  # type: ignore[union-attr]
        if raw is None:
            return None
        return SplitJob.model_validate_json(raw)

    async def mark_part_completed(
        self, document_id: UUID, part_index: int
    ) -> SplitJob:
        """파트 완료를 기록하고 최신 상태를 반환한다."""
        r = await self._get_redis()
        key = self._key(document_id)

        # Atomic read-modify-write (Redis WATCH 대신 단순 구현)
        raw = await r.get(key)  # type: ignore[union-attr]
        if raw is None:
            raise ValueError(f"Split job not found: {document_id}")

        job = SplitJob.model_validate_json(raw)
        if part_index not in job.completed_parts:
            job.completed_parts.append(part_index)
            job.completed_parts.sort()

        # 모든 파트 완료 확인
        if len(job.completed_parts) + len(job.failed_parts) >= job.total_parts:
            job.status = "merging" if not job.failed_parts else "failed"
        else:
            job.status = "processing"

        await r.set(key, job.model_dump_json(), ex=_SPLIT_JOB_TTL)  # type: ignore[union-attr]
        log.info(
            "split_part_completed",
            document_id=str(document_id),
            part_index=part_index,
            completed=f"{len(job.completed_parts)}/{job.total_parts}",
        )
        return job

    async def mark_part_failed(
        self, document_id: UUID, part_index: int
    ) -> SplitJob:
        """파트 실패를 기록한다."""
        r = await self._get_redis()
        key = self._key(document_id)

        raw = await r.get(key)  # type: ignore[union-attr]
        if raw is None:
            raise ValueError(f"Split job not found: {document_id}")

        job = SplitJob.model_validate_json(raw)
        if part_index not in job.failed_parts:
            job.failed_parts.append(part_index)

        if len(job.completed_parts) + len(job.failed_parts) >= job.total_parts:
            job.status = "failed"

        await r.set(key, job.model_dump_json(), ex=_SPLIT_JOB_TTL)  # type: ignore[union-attr]
        log.warning(
            "split_part_failed",
            document_id=str(document_id),
            part_index=part_index,
            failed=len(job.failed_parts),
        )
        return job

    def is_complete(self, job: SplitJob) -> bool:
        """모든 파트가 (성공적으로) 완료되었는지 확인한다."""
        return (
            len(job.completed_parts) == job.total_parts
            and len(job.failed_parts) == 0
        )

    async def mark_merged(self, document_id: UUID) -> None:
        """머지 완료를 기록한다."""
        r = await self._get_redis()
        key = self._key(document_id)
        raw = await r.get(key)  # type: ignore[union-attr]
        if raw:
            job = SplitJob.model_validate_json(raw)
            job.status = "completed"
            await r.set(key, job.model_dump_json(), ex=_SPLIT_JOB_TTL)  # type: ignore[union-attr]

    async def close(self) -> None:
        """Redis 연결을 닫는다."""
        if self._redis is not None:
            await self._redis.aclose()  # type: ignore[union-attr]
            self._redis = None
