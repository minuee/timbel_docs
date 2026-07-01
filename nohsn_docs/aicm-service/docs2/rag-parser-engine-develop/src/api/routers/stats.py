"""통계/대시보드 API 라우터 — 실 데이터 기반 집계."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/overview",
    response_model=ApiResponse[dict],
    summary="대시보드 개요 통계",
)
async def get_overview_stats(
    repository_id: UUID | None = Query(None, description="저장소 필터 (미입력 시 전체)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """대시보드 개요 통계를 반환한다.

    문서 수, 청크 수, 오늘 검색 수, 평균 레이턴시, 파이프라인 상태 등.
    MetricsCollector를 통해 DB 기반 실 데이터를 집계한다.
    """
    from src.api.services.metrics_collector import MetricsCollector

    collector = MetricsCollector(db)
    try:
        data = await collector.collect_overview_stats(
            tenant_id=tenant_id,
            repository_id=repository_id,
        )
    except Exception as exc:
        logger.warning("overview_stats_error", error=str(exc))
        data = {
            "total_documents": 0,
            "total_chunks": 0,
            "total_searches_today": 0,
            "avg_search_latency_ms": 0,
            "top_search_queries": [],
            "no_result_queries": [],
            "document_type_distribution": {},
            "category_distribution": {},
            "pipeline_status": {"processing": 0, "active": 0, "failed": 0, "archived": 0},
        }

    return ApiResponse(data=data)


@router.get(
    "/search-trends",
    response_model=ApiResponse[dict],
    summary="검색 트렌드",
)
async def get_search_trends(
    period: str = Query("7d", pattern=r"^(1d|7d|30d)$", description="기간"),
    repository_id: UUID | None = Query(None),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """검색 트렌드 (시계열) 데이터를 반환한다.

    search_logs 테이블 기반 실 데이터 집계.
    """
    from src.api.services.metrics_collector import MetricsCollector

    collector = MetricsCollector(db)
    try:
        data = await collector.collect_search_trends(
            tenant_id=tenant_id,
            period=period,
            repository_id=repository_id,
        )
    except Exception as exc:
        logger.warning("search_trends_error", error=str(exc))
        data = {
            "period": period,
            "daily_searches": [],
            "avg_latency_trend": [],
            "top_queries_by_day": [],
            "satisfaction_rate": 0.0,
        }

    return ApiResponse(data=data)


@router.get(
    "/knowledge-gaps",
    response_model=ApiResponse[dict],
    summary="지식 갭 분석",
)
async def get_knowledge_gaps(
    repository_id: UUID | None = Query(None),
    period_days: int = Query(30, ge=1, le=365, description="분석 기간 (일)"),
    min_occurrence: int = Query(2, ge=1, description="최소 반복 횟수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """지식 갭 분석 결과를 반환한다.

    검색했으나 결과가 없거나 만족도가 낮은 질의를 분석한다.
    KnowledgeGapAnalyzer를 사용하여 search_logs 기반 실 데이터 집계.
    """
    from src.search.analytics.knowledge_gap import KnowledgeGapAnalyzer

    analyzer = KnowledgeGapAnalyzer(session=db)
    try:
        report = await analyzer.analyze(
            tenant_id=tenant_id,
            repository_id=repository_id,
            period_days=period_days,
            min_occurrence=min_occurrence,
        )
        data = {
            "no_result_queries": [q.model_dump() for q in report.no_result_queries],
            "low_confidence_queries": [
                q.model_dump() for q in report.low_confidence_queries
            ],
            "suggestions": [s.model_dump() for s in report.suggestions],
            "total_searches": report.total_searches,
            "gap_rate": report.gap_rate,
            "analysis_period_days": report.analysis_period_days,
        }
    except Exception as exc:
        logger.warning("knowledge_gaps_error", error=str(exc))
        data = {
            "no_result_queries": [],
            "low_confidence_queries": [],
            "suggestions": [],
            "total_searches": 0,
            "gap_rate": 0.0,
            "analysis_period_days": period_days,
        }

    return ApiResponse(data=data)
