"""성능 메트릭 수집기 — Redis 카운터 + DB 집계 기반.

검색 레이턴시, 파이프라인 처리량, LLM 사용량을 시계열로 수집하여
Performance Dashboard에 제공한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Float, Integer, cast, func as sa_func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.common.logging import get_logger
from src.core.models.document import Chunk, Document
from src.core.models.search_log import SearchLog

logger = get_logger(__name__)

# Claude 토큰 가격 (USD per 1K tokens) — sonnet 3.5 기준
CLAUDE_INPUT_PRICE_PER_1K = 0.003
CLAUDE_OUTPUT_PRICE_PER_1K = 0.015
# Qwen (self-hosted vLLM) 비용 $0
QWEN_PRICE_PER_1K = 0.0

# 기간 -> timedelta 매핑
PERIOD_MAP: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "1d": timedelta(days=1),
}


async def _get_redis():
    """Redis 클라이언트를 지연 로딩한다."""
    try:
        import redis.asyncio as aioredis

        return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("redis_connection_failed", error=str(exc))
        return None


class MetricsCollector:
    """성능 메트릭 수집기.

    Redis에서 실시간 카운터를 읽고, DB에서 집계 쿼리를 실행하여
    검색 성능, 파이프라인 처리량, LLM 사용량 메트릭을 반환한다.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 검색 성능 메트릭
    # ------------------------------------------------------------------

    async def collect_search_performance(
        self,
        tenant_id: uuid.UUID,
        period: str = "24h",
        repository_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """검색 성능 메트릭을 수집한다.

        Args:
            tenant_id: 테넌트 ID
            period: 기간 (1h, 6h, 24h, 7d, 30d)
            repository_id: 저장소 필터

        Returns:
            total_queries, latency_p50_ms, latency_p95_ms, latency_breakdown, hourly_trend
        """
        delta = PERIOD_MAP.get(period, timedelta(hours=24))
        since = datetime.now(timezone.utc) - delta

        # 기본 필터
        filters = [
            SearchLog.tenant_id == tenant_id,
            SearchLog.created_at >= since,
        ]
        if repository_id:
            filters.append(SearchLog.repository_id == repository_id)

        # 총 쿼리 수
        stmt_count = select(sa_func.count(SearchLog.id)).where(*filters)
        result = await self.db.execute(stmt_count)
        total_queries = result.scalar_one() or 0

        # 레이턴시 분포 (p50, p95)
        latency_p50 = 0.0
        latency_p95 = 0.0
        if total_queries > 0:
            stmt_p50 = select(
                sa_func.percentile_cont(0.5).within_group(SearchLog.latency_ms)
            ).where(*filters, SearchLog.latency_ms.is_not(None))
            result_p50 = await self.db.execute(stmt_p50)
            latency_p50 = float(result_p50.scalar_one() or 0)

            stmt_p95 = select(
                sa_func.percentile_cont(0.95).within_group(SearchLog.latency_ms)
            ).where(*filters, SearchLog.latency_ms.is_not(None))
            result_p95 = await self.db.execute(stmt_p95)
            latency_p95 = float(result_p95.scalar_one() or 0)

        # 레이턴시 분해 — Redis에서 가져오기 (키: aicm:metrics:search_latency:{stage})
        breakdown = await self._get_search_latency_breakdown(tenant_id, period)

        # 시간별 트렌드
        hourly_trend = await self._get_search_hourly_trend(tenant_id, since, repository_id)

        return {
            "total_queries": total_queries,
            "latency_p50_ms": round(latency_p50, 1),
            "latency_p95_ms": round(latency_p95, 1),
            "latency_breakdown": breakdown,
            "hourly_trend": hourly_trend,
        }

    async def _get_search_latency_breakdown(
        self,
        tenant_id: uuid.UUID,
        period: str,
    ) -> dict[str, float]:
        """Redis에서 검색 단계별 평균 레이턴시를 읽는다."""
        defaults = {
            "dense_avg_ms": 0.0,
            "sparse_avg_ms": 0.0,
            "fusion_avg_ms": 0.0,
            "rerank_avg_ms": 0.0,
            "rag_avg_ms": 0.0,
        }
        redis = await _get_redis()
        if redis is None:
            return defaults
        try:
            prefix = f"aicm:metrics:{tenant_id}:search_latency"
            for stage in ["dense", "sparse", "fusion", "rerank", "rag"]:
                key = f"{prefix}:{stage}:{period}"
                val = await redis.get(key)
                if val is not None:
                    defaults[f"{stage}_avg_ms"] = round(float(val), 1)
            await redis.aclose()
        except Exception as exc:
            logger.warning("redis_latency_read_failed", error=str(exc))
        return defaults

    async def _get_search_hourly_trend(
        self,
        tenant_id: uuid.UUID,
        since: datetime,
        repository_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """search_logs에서 시간별 검색 수 + 평균 레이턴시 트렌드를 집계한다."""
        filters = [
            SearchLog.tenant_id == tenant_id,
            SearchLog.created_at >= since,
        ]
        if repository_id:
            filters.append(SearchLog.repository_id == repository_id)

        # date_trunc 사용하여 시간별 집계
        hour_col = sa_func.date_trunc("hour", SearchLog.created_at).label("hour")
        stmt = (
            select(
                hour_col,
                sa_func.count(SearchLog.id).label("count"),
                sa_func.avg(SearchLog.latency_ms).label("avg_latency"),
            )
            .where(*filters)
            .group_by(hour_col)
            .order_by(hour_col)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "hour": row.hour.isoformat() if row.hour else "",
                "count": row.count,
                "avg_latency_ms": round(float(row.avg_latency or 0), 1),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 파이프라인 처리량 메트릭
    # ------------------------------------------------------------------

    async def collect_pipeline_performance(
        self,
        tenant_id: uuid.UUID,
        period: str = "24h",
        repository_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """파이프라인 처리량 메트릭을 수집한다.

        Returns:
            processed_today, processing_now, failure_rate, avg_duration_ms, by_format
        """
        from src.core.models.repository import Repository

        delta = PERIOD_MAP.get(period, timedelta(hours=24))
        since = datetime.now(timezone.utc) - delta

        # 저장소 ID 목록
        repo_filters = [Repository.tenant_id == tenant_id, Repository.is_active.is_(True)]
        if repository_id:
            repo_filters.append(Repository.id == repository_id)
        stmt_repos = select(Repository.id).where(*repo_filters)
        result = await self.db.execute(stmt_repos)
        repo_ids = [r[0] for r in result.all()]

        if not repo_ids:
            return {
                "processed_today": 0,
                "processing_now": 0,
                "failure_rate": 0.0,
                "avg_duration_ms": 0.0,
                "by_format": {},
            }

        base_filters = [Document.repository_id.in_(repo_ids)]

        # 현재 처리 중
        stmt_processing = select(sa_func.count(Document.id)).where(
            *base_filters, Document.status == "processing"
        )
        result = await self.db.execute(stmt_processing)
        processing_now = result.scalar_one() or 0

        # 기간 내 완료 (active) 건수
        stmt_completed = select(sa_func.count(Document.id)).where(
            *base_filters,
            Document.status == "active",
            Document.updated_at >= since,
        )
        result = await self.db.execute(stmt_completed)
        processed = result.scalar_one() or 0

        # 기간 내 실패 건수
        stmt_failed = select(sa_func.count(Document.id)).where(
            *base_filters,
            Document.status == "failed",
            Document.updated_at >= since,
        )
        result = await self.db.execute(stmt_failed)
        failed = result.scalar_one() or 0

        total_attempted = processed + failed
        failure_rate = (failed / total_attempted * 100) if total_attempted > 0 else 0.0

        # 평균 처리 시간 (processing_meta -> 'total_duration_ms')
        # JSONB에서 추출
        avg_duration = 0.0
        try:
            stmt_avg = select(
                sa_func.avg(
                    cast(Document.processing_meta["total_duration_ms"].as_string(), Float)
                )
            ).where(
                *base_filters,
                Document.status == "active",
                Document.updated_at >= since,
                Document.processing_meta["total_duration_ms"].isnot(None),
            )
            result = await self.db.execute(stmt_avg)
            avg_val = result.scalar_one()
            if avg_val is not None:
                avg_duration = round(float(avg_val), 1)
        except Exception:
            pass

        # 포맷별 통계
        stmt_format = (
            select(
                Document.source_format,
                sa_func.count(Document.id),
            )
            .where(*base_filters, Document.updated_at >= since)
            .group_by(Document.source_format)
        )
        result = await self.db.execute(stmt_format)
        by_format = {row[0] or "unknown": row[1] for row in result.all()}

        return {
            "processed_today": processed,
            "processing_now": processing_now,
            "failure_rate": round(failure_rate, 2),
            "avg_duration_ms": avg_duration,
            "by_format": by_format,
        }

    # ------------------------------------------------------------------
    # LLM 사용량 메트릭
    # ------------------------------------------------------------------

    async def collect_llm_performance(
        self,
        tenant_id: uuid.UUID,
        period: str = "24h",
    ) -> dict[str, Any]:
        """LLM 사용량 메트릭을 Redis 카운터에서 수집한다.

        Redis 키 패턴:
          aicm:metrics:{tenant_id}:llm:{model}:requests:{period}
          aicm:metrics:{tenant_id}:llm:{model}:tokens:{period}
          aicm:metrics:{tenant_id}:llm:{model}:latency_sum:{period}
          aicm:metrics:{tenant_id}:llm:{model}:errors:{period}

        Returns:
            claude/qwen 각 모델별 requests, total_tokens, avg_latency_ms, estimated_cost_usd, error_rate
        """
        result = {
            "claude": {
                "requests": 0,
                "total_tokens": 0,
                "avg_latency_ms": 0.0,
                "estimated_cost_usd": 0.0,
                "error_rate": 0.0,
            },
            "qwen": {
                "requests": 0,
                "total_tokens": 0,
                "avg_latency_ms": 0.0,
                "estimated_cost_usd": 0.0,
                "error_rate": 0.0,
            },
            "fallback_count": 0,
        }

        redis = await _get_redis()
        if redis is None:
            return result

        try:
            prefix = f"aicm:metrics:{tenant_id}:llm"
            for model in ["claude", "qwen"]:
                requests = int(await redis.get(f"{prefix}:{model}:requests:{period}") or 0)
                tokens = int(await redis.get(f"{prefix}:{model}:tokens:{period}") or 0)
                latency_sum = float(
                    await redis.get(f"{prefix}:{model}:latency_sum:{period}") or 0
                )
                errors = int(await redis.get(f"{prefix}:{model}:errors:{period}") or 0)

                avg_latency = (latency_sum / requests) if requests > 0 else 0.0
                error_rate = (errors / requests * 100) if requests > 0 else 0.0

                # 비용 추정
                if model == "claude":
                    # 간이 추정: 토큰의 40%가 input, 60%가 output 가정
                    input_tokens = tokens * 0.4
                    output_tokens = tokens * 0.6
                    cost = (
                        input_tokens / 1000 * CLAUDE_INPUT_PRICE_PER_1K
                        + output_tokens / 1000 * CLAUDE_OUTPUT_PRICE_PER_1K
                    )
                else:
                    cost = tokens / 1000 * QWEN_PRICE_PER_1K

                result[model] = {
                    "requests": requests,
                    "total_tokens": tokens,
                    "avg_latency_ms": round(avg_latency, 1),
                    "estimated_cost_usd": round(cost, 4),
                    "error_rate": round(error_rate, 2),
                }

            fallback = int(await redis.get(f"{prefix}:fallback_count:{period}") or 0)
            result["fallback_count"] = fallback
            await redis.aclose()
        except Exception as exc:
            logger.warning("redis_llm_metrics_read_failed", error=str(exc))

        return result

    # ------------------------------------------------------------------
    # 통계 개요 (Stats Overview)
    # ------------------------------------------------------------------

    async def collect_overview_stats(
        self,
        tenant_id: uuid.UUID,
        repository_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """대시보드 개요 통계를 수집한다.

        문서 수, 청크 수, 오늘 검색 수, 평균 레이턴시, 파이프라인 상태,
        상위 검색 쿼리, 무결과 쿼리 등.
        """
        from src.core.models.repository import Repository
        from src.core.models.tenant import Tenant
        from src.core.services.document_service import DocumentService

        doc_svc = DocumentService(self.db)

        # 테넌트 수
        stmt_tenants = select(sa_func.count(Tenant.id)).where(Tenant.is_active.is_(True))
        result = await self.db.execute(stmt_tenants)
        tenant_count = result.scalar_one() or 0

        # 저장소 ID 목록
        if repository_id:
            repo_ids = [repository_id]
        else:
            stmt = select(Repository.id).where(
                Repository.tenant_id == tenant_id,
                Repository.is_active.is_(True),
            )
            result = await self.db.execute(stmt)
            repo_ids = [r[0] for r in result.all()]

        repository_count = len(repo_ids)

        pipeline_status = {"processing": 0, "active": 0, "failed": 0, "archived": 0, "pending_review": 0}
        total_documents = 0
        for rid in repo_ids:
            try:
                for status_key in pipeline_status:
                    count = await doc_svc.count(rid, tenant_id=tenant_id, status=status_key)
                    pipeline_status[status_key] += count
                draft_count = await doc_svc.count(rid, tenant_id=tenant_id, status="draft")
                total_documents = pipeline_status["active"] + pipeline_status["processing"] + pipeline_status["pending_review"]
            except Exception:
                pass

        # 총 청크 수
        chunk_filters = [Chunk.repository_id.in_(repo_ids)] if repo_ids else [sa_func.literal(False)]
        stmt_chunks = select(sa_func.count(Chunk.id)).where(*chunk_filters)
        result = await self.db.execute(stmt_chunks)
        total_chunks = result.scalar_one() or 0

        # 오늘 검색 수
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        search_filters = [
            SearchLog.tenant_id == tenant_id,
            SearchLog.created_at >= today_start,
        ]
        if repository_id:
            search_filters.append(SearchLog.repository_id == repository_id)

        stmt_search_count = select(sa_func.count(SearchLog.id)).where(*search_filters)
        result = await self.db.execute(stmt_search_count)
        total_searches_today = result.scalar_one() or 0

        # 평균 레이턴시 (오늘)
        stmt_avg_latency = select(
            sa_func.avg(SearchLog.latency_ms)
        ).where(*search_filters, SearchLog.latency_ms.is_not(None))
        result = await self.db.execute(stmt_avg_latency)
        avg_latency = result.scalar_one()
        avg_search_latency_ms = round(float(avg_latency), 1) if avg_latency else 0.0

        # 상위 검색 쿼리 (최근 7일)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        stmt_top = (
            select(
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
            )
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= week_ago,
            )
            .group_by(SearchLog.query)
            .order_by(sa_func.count(SearchLog.id).desc())
            .limit(10)
        )
        result = await self.db.execute(stmt_top)
        top_queries = [{"query": row[0], "count": row[1]} for row in result.all()]

        # 무결과 쿼리
        stmt_no_result = (
            select(
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
            )
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= week_ago,
                SearchLog.result_count == 0,
            )
            .group_by(SearchLog.query)
            .order_by(sa_func.count(SearchLog.id).desc())
            .limit(10)
        )
        result = await self.db.execute(stmt_no_result)
        no_result_queries = [{"query": row[0], "count": row[1]} for row in result.all()]

        # 문서타입 분포
        from src.core.models.document_type import DocumentType

        stmt_type_dist = (
            select(
                DocumentType.name,
                sa_func.count(Document.id),
            )
            .join(Document, Document.document_type_id == DocumentType.id)
            .where(Document.repository_id.in_(repo_ids) if repo_ids else sa_func.literal(False))
            .group_by(DocumentType.name)
        )
        result = await self.db.execute(stmt_type_dist)
        doc_type_distribution = {row[0]: row[1] for row in result.all()}

        return {
            "tenant_count": tenant_count,
            "repository_count": repository_count,
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "total_searches_today": total_searches_today,
            "avg_search_latency_ms": avg_search_latency_ms,
            "top_search_queries": top_queries,
            "no_result_queries": no_result_queries,
            "document_type_distribution": doc_type_distribution,
            "category_distribution": {},
            "pipeline_status": pipeline_status,
        }

    # ------------------------------------------------------------------
    # 검색 트렌드 (Stats Search Trends)
    # ------------------------------------------------------------------

    async def collect_search_trends(
        self,
        tenant_id: uuid.UUID,
        period: str = "7d",
        repository_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """검색 트렌드 시계열 데이터를 수집한다."""
        delta = PERIOD_MAP.get(period, timedelta(days=7))
        since = datetime.now(timezone.utc) - delta

        filters = [
            SearchLog.tenant_id == tenant_id,
            SearchLog.created_at >= since,
        ]
        if repository_id:
            filters.append(SearchLog.repository_id == repository_id)

        # 일별 검색 수
        day_col = sa_func.date_trunc("day", SearchLog.created_at).label("day")
        stmt_daily = (
            select(
                day_col,
                sa_func.count(SearchLog.id).label("count"),
            )
            .where(*filters)
            .group_by(day_col)
            .order_by(day_col)
        )
        result = await self.db.execute(stmt_daily)
        daily_searches = [
            {"date": row.day.isoformat() if row.day else "", "count": row.count}
            for row in result.all()
        ]

        # 일별 평균 레이턴시 트렌드
        stmt_latency = (
            select(
                day_col,
                sa_func.avg(SearchLog.latency_ms).label("avg_latency"),
            )
            .where(*filters, SearchLog.latency_ms.is_not(None))
            .group_by(day_col)
            .order_by(day_col)
        )
        result = await self.db.execute(stmt_latency)
        avg_latency_trend = [
            {
                "date": row.day.isoformat() if row.day else "",
                "avg_latency_ms": round(float(row.avg_latency or 0), 1),
            }
            for row in result.all()
        ]

        # 일별 상위 쿼리
        stmt_top_by_day = (
            select(
                day_col,
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
            )
            .where(*filters)
            .group_by(day_col, SearchLog.query)
            .order_by(day_col, sa_func.count(SearchLog.id).desc())
            .limit(50)
        )
        result = await self.db.execute(stmt_top_by_day)
        top_queries_raw = result.all()

        top_queries_by_day: list[dict] = []
        current_day = None
        current_queries: list[dict] = []
        for row in top_queries_raw:
            day_str = row.day.isoformat() if row.day else ""
            if day_str != current_day:
                if current_day is not None:
                    top_queries_by_day.append({
                        "date": current_day,
                        "queries": current_queries[:5],
                    })
                current_day = day_str
                current_queries = []
            current_queries.append({"query": row.query, "count": row.cnt})
        if current_day is not None:
            top_queries_by_day.append({
                "date": current_day,
                "queries": current_queries[:5],
            })

        # 만족도 (helpful / not_helpful)
        stmt_helpful = select(sa_func.count(SearchLog.id)).where(
            *filters, SearchLog.user_feedback == "helpful"
        )
        result = await self.db.execute(stmt_helpful)
        helpful = result.scalar_one() or 0

        stmt_feedback_total = select(sa_func.count(SearchLog.id)).where(
            *filters, SearchLog.user_feedback.is_not(None)
        )
        result = await self.db.execute(stmt_feedback_total)
        feedback_total = result.scalar_one() or 0

        satisfaction_rate = (helpful / feedback_total * 100) if feedback_total > 0 else 0.0

        return {
            "period": period,
            "daily_searches": daily_searches,
            "avg_latency_trend": avg_latency_trend,
            "top_queries_by_day": top_queries_by_day,
            "satisfaction_rate": round(satisfaction_rate, 1),
        }

    # ------------------------------------------------------------------
    # 지식 갭 분석
    # ------------------------------------------------------------------

    async def collect_knowledge_gaps(
        self,
        tenant_id: uuid.UUID,
        repository_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """지식 갭 분석 결과를 반환한다."""
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        filters = [
            SearchLog.tenant_id == tenant_id,
            SearchLog.created_at >= week_ago,
        ]
        if repository_id:
            filters.append(SearchLog.repository_id == repository_id)

        # 무결과 쿼리
        stmt_no_result = (
            select(
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
            )
            .where(*filters, SearchLog.result_count == 0)
            .group_by(SearchLog.query)
            .order_by(sa_func.count(SearchLog.id).desc())
            .limit(20)
        )
        result = await self.db.execute(stmt_no_result)
        no_result_queries = [{"query": row[0], "count": row[1]} for row in result.all()]

        # 낮은 만족도 쿼리
        stmt_low_sat = (
            select(
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
            )
            .where(*filters, SearchLog.user_feedback == "not_helpful")
            .group_by(SearchLog.query)
            .order_by(sa_func.count(SearchLog.id).desc())
            .limit(20)
        )
        result = await self.db.execute(stmt_low_sat)
        low_satisfaction_queries = [{"query": row[0], "count": row[1]} for row in result.all()]

        # 제안사항 생성
        suggestions: list[str] = []
        if no_result_queries:
            suggestions.append(
                f"무결과 쿼리 {len(no_result_queries)}건이 발견되었습니다. "
                "관련 문서를 추가하거나 동의어 매핑을 검토하세요."
            )
        if low_satisfaction_queries:
            suggestions.append(
                f"만족도가 낮은 쿼리 {len(low_satisfaction_queries)}건이 있습니다. "
                "검색 품질 개선이 필요합니다."
            )

        return {
            "no_result_queries": no_result_queries,
            "low_satisfaction_queries": low_satisfaction_queries,
            "suggestions": suggestions,
        }
