"""검색 분석(Analytics) API 라우터.

search_logs 테이블 기반으로 검색 트렌드, 미응답 쿼리, 인기 쿼리,
전체 개요 통계를 제공한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 응답 스키마 (인라인)
# ---------------------------------------------------------------------------


class DailyCount(BaseModel):
    """일별 검색 건수."""

    date: str = Field(..., description="날짜 (YYYY-MM-DD)")
    count: int = Field(..., description="검색 건수")


class SearchTrendsData(BaseModel):
    """검색 트렌드 응답 데이터."""

    trends: list[DailyCount]
    total: int = Field(..., description="기간 내 총 검색 건수")


class UnansweredQueryItem(BaseModel):
    """미응답/저결과 쿼리 항목."""

    query: str
    count: int = Field(..., description="반복 횟수")
    last_searched: str = Field(..., description="마지막 검색 일자 (YYYY-MM-DD)")


class UnansweredQueriesData(BaseModel):
    """미응답 쿼리 응답 데이터."""

    queries: list[UnansweredQueryItem]


class PopularQueryItem(BaseModel):
    """인기 쿼리 항목."""

    query: str
    count: int = Field(..., description="검색 횟수")


class PopularQueriesData(BaseModel):
    """인기 쿼리 응답 데이터."""

    queries: list[PopularQueryItem]


class OverviewData(BaseModel):
    """검색 개요 통계."""

    total_searches: int
    unique_users: int
    avg_latency_ms: float
    success_rate: float = Field(..., description="결과가 1건 이상인 검색 비율 (%)")


# ---------------------------------------------------------------------------
# 헬퍼: SearchLog 모델 지연 임포트
# ---------------------------------------------------------------------------


def _get_search_log_model():
    """SearchLog ORM 모델을 지연 로딩한다. 테이블 없으면 None 반환."""
    try:
        from src.core.models.search_log import SearchLog

        return SearchLog
    except Exception as exc:
        logger.warning("search_log_model_import_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# 1. GET /analytics/search-trends
# ---------------------------------------------------------------------------


@router.get(
    "/search-trends",
    response_model=ApiResponse[SearchTrendsData],
    summary="검색 트렌드 (일별 검색 건수)",
)
async def get_search_trends(
    days: int = Query(7, ge=1, le=365, description="조회 기간 (일)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SearchTrendsData]:
    """현재 테넌트의 일별 검색 건수를 반환한다."""
    SearchLog = _get_search_log_model()
    if SearchLog is None:
        logger.warning("search_logs_table_unavailable")
        return ApiResponse(data=SearchTrendsData(trends=[], total=0))

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        day_col = sa_func.date_trunc("day", SearchLog.created_at).label("day")
        stmt = (
            select(
                day_col,
                sa_func.count(SearchLog.id).label("count"),
            )
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= since,
            )
            .group_by(day_col)
            .order_by(day_col)
        )
        result = await db.execute(stmt)
        rows = result.all()

        trends = [
            DailyCount(
                date=row.day.strftime("%Y-%m-%d") if row.day else "",
                count=row.count,
            )
            for row in rows
        ]
        total = sum(t.count for t in trends)

        return ApiResponse(data=SearchTrendsData(trends=trends, total=total))

    except Exception as exc:
        logger.warning("search_trends_query_failed", error=str(exc))
        return ApiResponse(data=SearchTrendsData(trends=[], total=0))


# ---------------------------------------------------------------------------
# 2. GET /analytics/unanswered-queries
# ---------------------------------------------------------------------------


@router.get(
    "/unanswered-queries",
    response_model=ApiResponse[UnansweredQueriesData],
    summary="미응답/저결과 쿼리 목록",
)
async def get_unanswered_queries(
    days: int = Query(7, ge=1, le=365, description="조회 기간 (일)"),
    limit: int = Query(20, ge=1, le=100, description="최대 반환 건수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UnansweredQueriesData]:
    """결과가 0건이거나 3건 미만인 쿼리를 빈도순으로 반환한다."""
    SearchLog = _get_search_log_model()
    if SearchLog is None:
        logger.warning("search_logs_table_unavailable")
        return ApiResponse(data=UnansweredQueriesData(queries=[]))

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        stmt = (
            select(
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
                sa_func.max(SearchLog.created_at).label("last_searched"),
            )
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= since,
                SearchLog.result_count < 3,
            )
            .group_by(SearchLog.query)
            .order_by(sa_func.count(SearchLog.id).desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()

        queries = [
            UnansweredQueryItem(
                query=row.query,
                count=row.cnt,
                last_searched=(
                    row.last_searched.strftime("%Y-%m-%d")
                    if row.last_searched
                    else ""
                ),
            )
            for row in rows
        ]

        return ApiResponse(data=UnansweredQueriesData(queries=queries))

    except Exception as exc:
        logger.warning("unanswered_queries_failed", error=str(exc))
        return ApiResponse(data=UnansweredQueriesData(queries=[]))


# ---------------------------------------------------------------------------
# 3. GET /analytics/popular-queries
# ---------------------------------------------------------------------------


@router.get(
    "/popular-queries",
    response_model=ApiResponse[PopularQueriesData],
    summary="인기 검색어 목록",
)
async def get_popular_queries(
    days: int = Query(7, ge=1, le=365, description="조회 기간 (일)"),
    limit: int = Query(20, ge=1, le=100, description="최대 반환 건수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PopularQueriesData]:
    """테넌트의 가장 빈번한 검색 쿼리를 반환한다."""
    SearchLog = _get_search_log_model()
    if SearchLog is None:
        logger.warning("search_logs_table_unavailable")
        return ApiResponse(data=PopularQueriesData(queries=[]))

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        stmt = (
            select(
                SearchLog.query,
                sa_func.count(SearchLog.id).label("cnt"),
            )
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= since,
            )
            .group_by(SearchLog.query)
            .order_by(sa_func.count(SearchLog.id).desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()

        queries = [
            PopularQueryItem(query=row.query, count=row.cnt) for row in rows
        ]

        return ApiResponse(data=PopularQueriesData(queries=queries))

    except Exception as exc:
        logger.warning("popular_queries_failed", error=str(exc))
        return ApiResponse(data=PopularQueriesData(queries=[]))


# ---------------------------------------------------------------------------
# 4. GET /analytics/overview
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=ApiResponse[OverviewData],
    summary="검색 분석 개요",
)
async def get_analytics_overview(
    days: int = Query(7, ge=1, le=365, description="조회 기간 (일)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[OverviewData]:
    """총 검색 수, 고유 사용자 수, 평균 레이턴시, 성공률을 반환한다.

    성공률은 result_count > 0인 검색의 비율이다.
    """
    SearchLog = _get_search_log_model()
    if SearchLog is None:
        logger.warning("search_logs_table_unavailable")
        return ApiResponse(
            data=OverviewData(
                total_searches=0,
                unique_users=0,
                avg_latency_ms=0.0,
                success_rate=0.0,
            )
        )

    since = datetime.now(timezone.utc) - timedelta(days=days)
    base_filters = [
        SearchLog.tenant_id == tenant_id,
        SearchLog.created_at >= since,
    ]

    try:
        # 총 검색 수 + 고유 사용자 수 (user_id가 없는 모델이므로 query_source 활용)
        # SearchLog에 user_id 컬럼이 없으므로 unique_users는 고유 query_source 수로 대체
        # (실제 user_id 컬럼이 추가되면 수정 필요)
        stmt_summary = select(
            sa_func.count(SearchLog.id).label("total"),
            sa_func.count(sa_func.distinct(SearchLog.query_source)).label("unique_sources"),
            sa_func.avg(SearchLog.latency_ms).label("avg_latency"),
        ).where(*base_filters)
        result = await db.execute(stmt_summary)
        row = result.one()

        total_searches = row.total or 0
        unique_users = row.unique_sources or 0
        avg_latency = round(float(row.avg_latency or 0), 1)

        # 성공률: result_count > 0
        success_count = 0
        if total_searches > 0:
            stmt_success = select(sa_func.count(SearchLog.id)).where(
                *base_filters,
                SearchLog.result_count > 0,
            )
            result = await db.execute(stmt_success)
            success_count = result.scalar_one() or 0

        success_rate = round(
            (success_count / total_searches * 100) if total_searches > 0 else 0.0,
            1,
        )

        return ApiResponse(
            data=OverviewData(
                total_searches=total_searches,
                unique_users=unique_users,
                avg_latency_ms=avg_latency,
                success_rate=success_rate,
            )
        )

    except Exception as exc:
        logger.warning("analytics_overview_failed", error=str(exc))
        return ApiResponse(
            data=OverviewData(
                total_searches=0,
                unique_users=0,
                avg_latency_ms=0.0,
                success_rate=0.0,
            )
        )
