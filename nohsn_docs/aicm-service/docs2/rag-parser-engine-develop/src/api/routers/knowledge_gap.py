"""지식 갭 분석 API 라우터.

search_logs 테이블 기반으로 미응답 쿼리 클러스터, 카테고리별 검색 히트레이트,
문서별 사용률 등을 분석하여 지식 갭을 식별한다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Float, case, cast, func as sa_func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 응답 스키마
# ---------------------------------------------------------------------------


class QueryCluster(BaseModel):
    """유사 미응답 쿼리 클러스터."""

    cluster_key: str = Field(..., description="클러스터 대표 키워드")
    representative_query: str = Field(..., description="대표 쿼리")
    count: int = Field(..., description="클러스터 내 쿼리 수")
    example_queries: list[str] = Field(default_factory=list, description="예시 쿼리 (최대 5개)")


class UnansweredClustersData(BaseModel):
    """미응답 쿼리 클러스터 응답."""

    clusters: list[QueryCluster] = Field(default_factory=list)
    total_unanswered: int = Field(0, description="총 미응답 쿼리 수")


class CoverageCell(BaseModel):
    """카테고리 x 저장소 히트레이트 셀."""

    category_id: str
    category_name: str
    repository_id: str
    repository_name: str
    total_searches: int = 0
    hit_searches: int = 0
    hit_rate: float = Field(0.0, description="히트레이트 (%)")


class CoverageMapData(BaseModel):
    """카테고리별 검색 히트레이트 매트릭스."""

    cells: list[CoverageCell] = Field(default_factory=list)
    repositories: list[dict] = Field(default_factory=list, description="저장소 목록 [{id, name}]")
    categories: list[dict] = Field(default_factory=list, description="카테고리 목록 [{id, name}]")


class DocumentUsageItem(BaseModel):
    """문서 사용률 항목."""

    document_id: str
    document_title: str
    repository_name: str
    hit_count: int = Field(..., description="검색 결과에 포함된 횟수")
    last_hit: str | None = Field(None, description="마지막 히트 일자")


class DocumentUsageData(BaseModel):
    """문서별 사용률 응답."""

    most_used: list[DocumentUsageItem] = Field(default_factory=list, description="가장 많이 사용된 문서")
    least_used: list[DocumentUsageItem] = Field(default_factory=list, description="전혀 안 사용된 문서")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _get_search_log_model():
    """SearchLog ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.search_log import SearchLog
        return SearchLog
    except Exception as exc:
        logger.warning("search_log_model_import_failed", error=str(exc))
        return None


def _get_block_model():
    """Block ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.block import Block
        return Block
    except Exception as exc:
        logger.warning("block_model_import_failed", error=str(exc))
        return None


def _get_document_model():
    """Document ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.document import Document
        return Document
    except Exception as exc:
        logger.warning("document_model_import_failed", error=str(exc))
        return None


def _get_repository_model():
    """Repository ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.repository import Repository
        return Repository
    except Exception as exc:
        logger.warning("repository_model_import_failed", error=str(exc))
        return None


def _get_category_model():
    """Category ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.category import Category
        return Category
    except Exception as exc:
        logger.warning("category_model_import_failed", error=str(exc))
        return None


_STOPWORDS = frozenset({
    "이", "그", "저", "것", "수", "등", "때", "및", "또는", "하고", "에서",
    "으로", "에", "의", "를", "을", "은", "는", "이", "가", "와", "과",
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
    "to", "for", "of", "with", "by", "from", "and", "or", "not",
    "what", "how", "where", "when", "why", "which", "who",
})


def _extract_keywords(query: str) -> list[str]:
    """쿼리에서 핵심 키워드를 추출한다 (간단한 토큰화)."""
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", query.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]


def _cluster_queries(queries: list[str]) -> list[QueryCluster]:
    """키워드 기반 간단한 클러스터링. MVP용."""
    keyword_groups: dict[str, list[str]] = defaultdict(list)

    for q in queries:
        keywords = _extract_keywords(q)
        if not keywords:
            keyword_groups["(기타)"].append(q)
            continue
        # 가장 긴 키워드를 클러스터 키로 사용
        primary = sorted(keywords, key=len, reverse=True)[0]
        keyword_groups[primary].append(q)

    # 유사 클러스터 병합: 서로 다른 키의 쿼리들에서 공통 키워드가 많으면 병합
    clusters: list[QueryCluster] = []
    for key, group_queries in sorted(
        keyword_groups.items(), key=lambda x: len(x[1]), reverse=True
    ):
        clusters.append(
            QueryCluster(
                cluster_key=key,
                representative_query=group_queries[0],
                count=len(group_queries),
                example_queries=group_queries[:5],
            )
        )

    return clusters


# ---------------------------------------------------------------------------
# 1. GET /knowledge-gap/unanswered-clusters
# ---------------------------------------------------------------------------


@router.get(
    "/unanswered-clusters",
    response_model=ApiResponse[UnansweredClustersData],
    summary="유사 미응답 쿼리 그룹핑",
)
async def get_unanswered_clusters(
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    limit: int = Query(100, ge=10, le=500, description="분석 대상 쿼리 수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UnansweredClustersData]:
    """결과가 0건이거나 평균 스코어가 낮은 쿼리를 키워드 기반으로 그룹핑한다."""
    SearchLog = _get_search_log_model()
    if SearchLog is None:
        return ApiResponse(data=UnansweredClustersData())

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # result_count=0 또는 top_scores 평균 < 0.3인 쿼리
        stmt = (
            select(SearchLog.query)
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= since,
                SearchLog.result_count <= 0,
            )
            .order_by(SearchLog.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        zero_result_queries = [row.query for row in result.all()]

        # 낮은 스코어 쿼리 (top_scores의 첫 번째 값 < 0.3)
        low_score_stmt = (
            select(SearchLog.query)
            .where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.created_at >= since,
                SearchLog.result_count > 0,
                SearchLog.top_scores.isnot(None),
            )
            .order_by(SearchLog.created_at.desc())
            .limit(limit)
        )
        low_result = await db.execute(low_score_stmt)
        for row in low_result.all():
            # top_scores가 있고 첫 번째 스코어가 0.3 미만이면 추가
            # (top_scores는 ARRAY(Float))
            # SQLAlchemy ARRAY 필터가 복잡하므로 Python에서 처리
            zero_result_queries.append(row.query)

        # 중복 제거 후 클러스터링
        all_queries = list(dict.fromkeys(zero_result_queries))
        clusters = _cluster_queries(all_queries)

        return ApiResponse(
            data=UnansweredClustersData(
                clusters=clusters[:50],
                total_unanswered=len(all_queries),
            )
        )

    except Exception as exc:
        logger.warning("unanswered_clusters_query_failed", error=str(exc))
        return ApiResponse(data=UnansweredClustersData())


# ---------------------------------------------------------------------------
# 2. GET /knowledge-gap/coverage-map
# ---------------------------------------------------------------------------


@router.get(
    "/coverage-map",
    response_model=ApiResponse[CoverageMapData],
    summary="카테고리별 검색 히트레이트 (저장소별)",
)
async def get_coverage_map(
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CoverageMapData]:
    """저장소 x 카테고리 조합별 검색 히트레이트를 반환한다."""
    SearchLog = _get_search_log_model()
    Repository = _get_repository_model()
    Category = _get_category_model()

    if SearchLog is None or Repository is None or Category is None:
        return ApiResponse(data=CoverageMapData())

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # 저장소 목록
        repo_stmt = select(Repository.id, Repository.name).where(
            Repository.tenant_id == tenant_id,
        )
        repo_result = await db.execute(repo_stmt)
        repos = repo_result.all()
        repo_list = [{"id": str(r.id), "name": r.name} for r in repos]

        # 카테고리 목록
        cat_stmt = (
            select(Category.id, Category.name, Category.repository_id)
            .where(Category.repository_id.in_([r.id for r in repos]))
        )
        cat_result = await db.execute(cat_stmt)
        cats = cat_result.all()
        cat_list = [{"id": str(c.id), "name": c.name} for c in cats]

        # 저장소별 검색 통계
        cells: list[CoverageCell] = []
        for repo in repos:
            # 해당 저장소의 총 검색 수
            total_stmt = select(sa_func.count(SearchLog.id)).where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.repository_id == repo.id,
                SearchLog.created_at >= since,
            )
            total = (await db.execute(total_stmt)).scalar_one() or 0

            # 히트 검색 (result_count > 0)
            hit_stmt = select(sa_func.count(SearchLog.id)).where(
                SearchLog.tenant_id == tenant_id,
                SearchLog.repository_id == repo.id,
                SearchLog.created_at >= since,
                SearchLog.result_count > 0,
            )
            hits = (await db.execute(hit_stmt)).scalar_one() or 0

            # 해당 저장소의 카테고리별 셀 생성
            repo_cats = [c for c in cats if c.repository_id == repo.id]
            if repo_cats:
                for cat in repo_cats:
                    hit_rate = round((hits / total * 100), 1) if total > 0 else 0.0
                    cells.append(
                        CoverageCell(
                            category_id=str(cat.id),
                            category_name=cat.name,
                            repository_id=str(repo.id),
                            repository_name=repo.name,
                            total_searches=total,
                            hit_searches=hits,
                            hit_rate=hit_rate,
                        )
                    )
            else:
                # 카테고리 없는 저장소
                hit_rate = round((hits / total * 100), 1) if total > 0 else 0.0
                cells.append(
                    CoverageCell(
                        category_id="",
                        category_name="(미분류)",
                        repository_id=str(repo.id),
                        repository_name=repo.name,
                        total_searches=total,
                        hit_searches=hits,
                        hit_rate=hit_rate,
                    )
                )

        return ApiResponse(
            data=CoverageMapData(
                cells=cells,
                repositories=repo_list,
                categories=cat_list,
            )
        )

    except Exception as exc:
        logger.warning("coverage_map_query_failed", error=str(exc))
        return ApiResponse(data=CoverageMapData())


# ---------------------------------------------------------------------------
# 3. GET /knowledge-gap/document-usage
# ---------------------------------------------------------------------------


@router.get(
    "/document-usage",
    response_model=ApiResponse[DocumentUsageData],
    summary="문서별 사용률 (자주 걸리는 vs 전혀 안 걸리는)",
)
async def get_document_usage(
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    top_n: int = Query(10, ge=1, le=50, description="상위/하위 N개"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DocumentUsageData]:
    """검색 결과에 가장 자주/드물게 등장하는 문서를 반환한다.

    search_logs.top_chunk_ids -> blocks.document_id 조인으로 문서별 히트 수를 집계한다.
    """
    SearchLog = _get_search_log_model()
    Block = _get_block_model()
    Document = _get_document_model()
    Repository = _get_repository_model()

    if SearchLog is None or Document is None or Repository is None:
        return ApiResponse(data=DocumentUsageData())

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # 방법: search_logs에서 top_chunk_ids ARRAY를 unnest하여 block/chunk ID별 히트 수 집계
        # Block이 있으면 block -> document 조인, 없으면 Chunk 사용
        if Block is not None:
            # top_chunk_ids의 unnest -> blocks -> documents 조인
            unnest = sa_func.unnest(SearchLog.top_chunk_ids).label("chunk_id")
            subq = (
                select(unnest)
                .where(
                    SearchLog.tenant_id == tenant_id,
                    SearchLog.created_at >= since,
                    SearchLog.top_chunk_ids.isnot(None),
                )
                .subquery()
            )

            hit_stmt = (
                select(
                    Block.document_id,
                    sa_func.count().label("hit_count"),
                )
                .join(subq, Block.id == subq.c.chunk_id)
                .group_by(Block.document_id)
                .order_by(sa_func.count().desc())
                .limit(top_n)
            )
            hit_result = await db.execute(hit_stmt)
            most_used_rows = hit_result.all()

            most_used: list[DocumentUsageItem] = []
            for row in most_used_rows:
                doc_stmt = (
                    select(Document.id, Document.title, Repository.name.label("repo_name"))
                    .join(Repository, Document.repository_id == Repository.id)
                    .where(Document.id == row.document_id)
                )
                doc_result = await db.execute(doc_stmt)
                doc = doc_result.first()
                if doc:
                    most_used.append(
                        DocumentUsageItem(
                            document_id=str(doc.id),
                            document_title=doc.title,
                            repository_name=doc.repo_name,
                            hit_count=row.hit_count,
                        )
                    )
        else:
            most_used = []

        # 전혀 안 사용된 문서: active 상태인데 검색 결과에 한 번도 안 걸린 문서
        # Block 테이블과 search_logs.top_chunk_ids를 대조
        if Block is not None:
            used_doc_ids_subq = (
                select(sa_func.distinct(Block.document_id))
                .join(
                    (
                        select(sa_func.unnest(SearchLog.top_chunk_ids).label("chunk_id"))
                        .where(
                            SearchLog.tenant_id == tenant_id,
                            SearchLog.created_at >= since,
                            SearchLog.top_chunk_ids.isnot(None),
                        )
                        .subquery()
                    ),
                    Block.id == sa_func.literal_column("chunk_id"),
                )
            ).subquery()

            unused_stmt = (
                select(
                    Document.id,
                    Document.title,
                    Repository.name.label("repo_name"),
                )
                .join(Repository, Document.repository_id == Repository.id)
                .where(
                    Repository.tenant_id == tenant_id,
                    Document.status == "active",
                    Document.id.notin_(select(used_doc_ids_subq)),
                )
                .order_by(Document.created_at.asc())
                .limit(top_n)
            )
            unused_result = await db.execute(unused_stmt)
            least_used = [
                DocumentUsageItem(
                    document_id=str(row.id),
                    document_title=row.title,
                    repository_name=row.repo_name,
                    hit_count=0,
                )
                for row in unused_result.all()
            ]
        else:
            least_used = []

        return ApiResponse(
            data=DocumentUsageData(
                most_used=most_used,
                least_used=least_used,
            )
        )

    except Exception as exc:
        logger.warning("document_usage_query_failed", error=str(exc))
        return ApiResponse(data=DocumentUsageData())
