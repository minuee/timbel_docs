"""검색 로그 기록 — search_logs 테이블에 비동기 기록."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


class SearchLogRecorder:
    """
    검색 로그를 search_logs 테이블에 비동기로 기록.

    검색 응답을 지연시키지 않도록 fire-and-forget 패턴으로 동작.
    """

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self._engine = engine

    async def _get_engine(self) -> AsyncEngine:
        """지연 초기화된 DB 엔진 반환."""
        if self._engine is None:
            self._engine = create_async_engine(
                settings.DATABASE_URL,
                pool_size=5,
                max_overflow=5,
                echo=settings.DATABASE_ECHO,
            )
        return self._engine

    async def record(
        self,
        tenant_id: UUID,
        repository_id: UUID | None,
        query: str,
        query_source: str | None,
        result_count: int,
        top_chunk_ids: list[UUID],
        top_scores: list[float],
        latency_ms: int,
    ) -> None:
        """검색 로그를 DB에 기록."""
        try:
            engine = await self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :v, true)"),
                    {"v": str(tenant_id)},
                )
                await conn.execute(
                    text("SELECT set_config('app.current_scope', :v, true)"),
                    {"v": "admin"},
                )
                await conn.execute(
                    text("""
                        INSERT INTO search_logs
                            (tenant_id, repository_id, query, query_source,
                             result_count, top_chunk_ids, top_scores, latency_ms)
                        VALUES
                            (:tenant_id, :repository_id, :query, :query_source,
                             :result_count, :top_chunk_ids, :top_scores, :latency_ms)
                    """),
                    {
                        "tenant_id": str(tenant_id),
                        "repository_id": str(repository_id) if repository_id else None,
                        "query": query,
                        "query_source": query_source,
                        "result_count": result_count,
                        "top_chunk_ids": [str(cid) for cid in top_chunk_ids],
                        "top_scores": top_scores,
                        "latency_ms": latency_ms,
                    },
                )
            log.debug(
                "search_log_recorded",
                tenant_id=str(tenant_id),
                query=query[:100],
                result_count=result_count,
            )
        except Exception:
            # 로그 기록 실패가 검색 응답에 영향을 주지 않도록 예외를 삼킴
            log.warning(
                "search_log_record_failed",
                tenant_id=str(tenant_id),
                query=query[:100],
                exc_info=True,
            )

    def record_fire_and_forget(
        self,
        tenant_id: UUID,
        repository_id: UUID | None,
        query: str,
        query_source: str | None,
        result_count: int,
        top_chunk_ids: list[UUID],
        top_scores: list[float],
        latency_ms: int,
    ) -> None:
        """검색 로그를 비동기로 기록 (fire-and-forget). 응답 지연 없음."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.record(
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    query=query,
                    query_source=query_source,
                    result_count=result_count,
                    top_chunk_ids=top_chunk_ids,
                    top_scores=top_scores,
                    latency_ms=latency_ms,
                )
            )
        except RuntimeError:
            log.warning("search_log_no_event_loop")
