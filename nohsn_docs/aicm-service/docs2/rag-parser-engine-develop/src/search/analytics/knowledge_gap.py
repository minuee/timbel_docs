"""지식 갭 분석 — 미응답/저신뢰도 질의 수집 및 제안 생성."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger

log = get_logger(__name__)


class GapQuery(BaseModel):
    """지식 갭 질의 항목."""

    query: str
    count: int
    gap_type: str  # "no_result" | "low_confidence"
    last_occurred: datetime | None = None
    avg_top_score: float | None = None


class GapSuggestion(BaseModel):
    """지식 갭 해결 제안."""

    query_pattern: str
    occurrence_count: int
    suggestion: str
    priority: str  # "high" | "medium" | "low"


class KnowledgeGapReport(BaseModel):
    """지식 갭 분석 보고서."""

    no_result_queries: list[GapQuery] = Field(default_factory=list)
    low_confidence_queries: list[GapQuery] = Field(default_factory=list)
    suggestions: list[GapSuggestion] = Field(default_factory=list)
    analysis_period_days: int = 30
    total_searches: int = 0
    gap_rate: float = 0.0  # (no_result + low_confidence) / total_searches


class KnowledgeGapAnalyzer:
    """
    미응답 질의 수집 + 지식 갭 분석.

    데이터 소스: search_logs 테이블
    분석:
    1. result_count=0 인 질의 집계 (no_result)
    2. top_score < 0.3 인 질의 집계 (low_confidence)
    3. 반복되는 미응답 질의 집계
    4. 제안: "XX 관련 문서를 추가하세요"
    """

    LOW_CONFIDENCE_THRESHOLD = 0.3

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def analyze(
        self,
        tenant_id: UUID,
        repository_id: UUID | None = None,
        period_days: int = 30,
        min_occurrence: int = 2,
        limit: int = 50,
    ) -> KnowledgeGapReport:
        """
        지식 갭 분석 수행.

        Args:
            tenant_id: 테넌트 ID
            repository_id: 저장소 필터 (None이면 전체)
            period_days: 분석 기간 (일)
            min_occurrence: 최소 반복 횟수 (이 이상 반복된 질의만 포함)
            limit: 최대 반환 건수

        Returns:
            KnowledgeGapReport
        """
        since = datetime.now(timezone.utc) - timedelta(days=period_days)

        try:
            # 전체 검색 수
            total_searches = await self._count_total_searches(
                tenant_id, repository_id, since
            )

            # no_result 질의 집계
            no_result_queries = await self._aggregate_no_result(
                tenant_id, repository_id, since, min_occurrence, limit
            )

            # low_confidence 질의 집계
            low_confidence_queries = await self._aggregate_low_confidence(
                tenant_id, repository_id, since, min_occurrence, limit
            )

            # 제안 생성
            suggestions = self._generate_suggestions(
                no_result_queries, low_confidence_queries
            )

            # 갭 비율 계산
            gap_count = sum(q.count for q in no_result_queries) + sum(
                q.count for q in low_confidence_queries
            )
            gap_rate = gap_count / total_searches if total_searches > 0 else 0.0

            report = KnowledgeGapReport(
                no_result_queries=no_result_queries,
                low_confidence_queries=low_confidence_queries,
                suggestions=suggestions,
                analysis_period_days=period_days,
                total_searches=total_searches,
                gap_rate=round(gap_rate, 4),
            )

            log.info(
                "knowledge_gap_analysis_complete",
                tenant_id=str(tenant_id),
                total_searches=total_searches,
                no_result_count=len(no_result_queries),
                low_confidence_count=len(low_confidence_queries),
                gap_rate=report.gap_rate,
            )
            return report

        except Exception:
            log.exception(
                "knowledge_gap_analysis_failed",
                tenant_id=str(tenant_id),
            )
            return KnowledgeGapReport(analysis_period_days=period_days)

    async def _count_total_searches(
        self,
        tenant_id: UUID,
        repository_id: UUID | None,
        since: datetime,
    ) -> int:
        """분석 기간 내 전체 검색 수."""
        params: dict = {"tenant_id": str(tenant_id), "since": since}
        repo_filter = ""
        if repository_id:
            repo_filter = "AND repository_id = :repository_id"
            params["repository_id"] = str(repository_id)

        result = await self._session.execute(
            text(f"""
                SELECT COUNT(*) FROM search_logs
                WHERE tenant_id = :tenant_id
                {repo_filter}
                AND created_at >= :since
            """),
            params,
        )
        row = result.scalar()
        return int(row) if row else 0

    async def _aggregate_no_result(
        self,
        tenant_id: UUID,
        repository_id: UUID | None,
        since: datetime,
        min_occurrence: int,
        limit: int,
    ) -> list[GapQuery]:
        """result_count=0 인 질의 집계."""
        params: dict = {
            "tenant_id": str(tenant_id),
            "since": since,
            "min_occurrence": min_occurrence,
            "limit": limit,
        }
        repo_filter = ""
        if repository_id:
            repo_filter = "AND repository_id = :repository_id"
            params["repository_id"] = str(repository_id)

        result = await self._session.execute(
            text(f"""
                SELECT query, COUNT(*) as cnt, MAX(created_at) as last_occurred
                FROM search_logs
                WHERE tenant_id = :tenant_id
                {repo_filter}
                AND created_at >= :since
                AND result_count = 0
                GROUP BY query
                HAVING COUNT(*) >= :min_occurrence
                ORDER BY cnt DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()

        return [
            GapQuery(
                query=row[0],
                count=int(row[1]),
                gap_type="no_result",
                last_occurred=row[2],
            )
            for row in rows
        ]

    async def _aggregate_low_confidence(
        self,
        tenant_id: UUID,
        repository_id: UUID | None,
        since: datetime,
        min_occurrence: int,
        limit: int,
    ) -> list[GapQuery]:
        """top_score < threshold 인 질의 집계."""
        params: dict = {
            "tenant_id": str(tenant_id),
            "since": since,
            "min_occurrence": min_occurrence,
            "limit": limit,
            "threshold": self.LOW_CONFIDENCE_THRESHOLD,
        }
        repo_filter = ""
        if repository_id:
            repo_filter = "AND repository_id = :repository_id"
            params["repository_id"] = str(repository_id)

        result = await self._session.execute(
            text(f"""
                SELECT query, COUNT(*) as cnt, MAX(created_at) as last_occurred,
                       AVG(top_scores[1]) as avg_top_score
                FROM search_logs
                WHERE tenant_id = :tenant_id
                {repo_filter}
                AND created_at >= :since
                AND result_count > 0
                AND top_scores[1] < :threshold
                GROUP BY query
                HAVING COUNT(*) >= :min_occurrence
                ORDER BY cnt DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()

        return [
            GapQuery(
                query=row[0],
                count=int(row[1]),
                gap_type="low_confidence",
                last_occurred=row[2],
                avg_top_score=float(row[3]) if row[3] is not None else None,
            )
            for row in rows
        ]

    @staticmethod
    def _generate_suggestions(
        no_result: list[GapQuery],
        low_confidence: list[GapQuery],
    ) -> list[GapSuggestion]:
        """지식 갭 해결 제안 생성."""
        suggestions: list[GapSuggestion] = []

        # no_result 질의 -> 문서 추가 제안
        for gap in no_result[:20]:
            priority = "high" if gap.count >= 10 else ("medium" if gap.count >= 5 else "low")
            suggestions.append(
                GapSuggestion(
                    query_pattern=gap.query,
                    occurrence_count=gap.count,
                    suggestion=f"'{gap.query}' 관련 문서를 추가하세요. "
                    f"({gap.count}회 검색되었으나 결과 없음)",
                    priority=priority,
                )
            )

        # low_confidence 질의 -> 문서 보강 제안
        for gap in low_confidence[:20]:
            avg_score = f" (평균 신뢰도: {gap.avg_top_score:.2f})" if gap.avg_top_score else ""
            priority = "medium" if gap.count >= 5 else "low"
            suggestions.append(
                GapSuggestion(
                    query_pattern=gap.query,
                    occurrence_count=gap.count,
                    suggestion=f"'{gap.query}' 관련 문서 내용을 보강하세요{avg_score}. "
                    f"({gap.count}회 검색 시 낮은 신뢰도)",
                    priority=priority,
                )
            )

        # 우선순위별 정렬: high > medium > low, 같은 우선순위 내에서는 occurrence_count 내림차순
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(
            key=lambda s: (priority_order.get(s.priority, 99), -s.occurrence_count)
        )

        return suggestions
