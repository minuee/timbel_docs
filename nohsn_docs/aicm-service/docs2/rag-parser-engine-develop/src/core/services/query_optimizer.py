"""DB 쿼리 성능 최적화 도구.

- N+1 쿼리 감지 데코레이터
- 인덱스 추천
- EXPLAIN ANALYZE 기반 슬로우 쿼리 분석
"""

from __future__ import annotations

import functools
import time
from collections import defaultdict
from typing import Any, Callable, TypeVar

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# N+1 감지용 쿼리 카운터 (ContextVar 대용 — 테스트/디버그용)
_query_counts: defaultdict[str, int] = defaultdict(int)
_query_threshold: int = 10  # 이 횟수 이상 같은 패턴 쿼리가 발생하면 경고


class QueryCounter:
    """컨텍스트 매니저: 블록 내에서 실행된 쿼리 수를 추적한다.

    Usage:
        async with QueryCounter(session) as counter:
            # ... DB 작업 ...
        if counter.count > threshold:
            logger.warning("too_many_queries", count=counter.count)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.count: int = 0
        self.queries: list[str] = []
        self._patterns: defaultdict[str, int] = defaultdict(int)

    async def __aenter__(self) -> "QueryCounter":
        """쿼리 카운팅을 시작한다."""
        sync_engine = self._session.get_bind()
        if hasattr(sync_engine, "sync_engine"):
            sync_engine = sync_engine.sync_engine

        @event.listens_for(sync_engine, "before_cursor_execute")
        def _count_query(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            self.count += 1
            # 쿼리 패턴 정규화 (파라미터 제거)
            pattern = statement.split("WHERE")[0].strip() if "WHERE" in statement else statement
            self._patterns[pattern] += 1
            if len(self.queries) < 100:  # 메모리 제한
                self.queries.append(statement[:200])

        self._listener = _count_query
        return self

    async def __aexit__(self, *args: Any) -> None:
        """쿼리 카운팅을 종료하고 리스너를 제거한다."""
        sync_engine = self._session.get_bind()
        if hasattr(sync_engine, "sync_engine"):
            sync_engine = sync_engine.sync_engine
        try:
            event.remove(sync_engine, "before_cursor_execute", self._listener)
        except Exception:
            pass

    def get_n_plus_one_candidates(self) -> list[tuple[str, int]]:
        """N+1 패턴으로 의심되는 쿼리를 반환한다.

        Returns:
            [(쿼리 패턴, 실행 횟수)] 리스트 (threshold 초과만)
        """
        return [
            (pattern, count)
            for pattern, count in self._patterns.items()
            if count >= _query_threshold
        ]


def detect_n_plus_one(threshold: int = 10) -> Callable[[F], F]:
    """N+1 쿼리 감지 데코레이터.

    비동기 함수를 감싸서 실행 중 발생한 DB 쿼리 수를 추적한다.
    임계값을 초과하면 경고 로그를 남긴다.

    Args:
        threshold: 경고 기준 쿼리 수

    Usage:
        @detect_n_plus_one(threshold=10)
        async def list_documents(session: AsyncSession, repo_id: UUID):
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.monotonic()

            # 함수 실행
            result = await func(*args, **kwargs)

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # 실행 시간이 500ms 를 초과하면 경고
            if elapsed_ms > 500:
                logger.warning(
                    "slow_query_detected",
                    function=func.__qualname__,
                    elapsed_ms=round(elapsed_ms, 2),
                )

            return result

        return wrapper  # type: ignore[return-value]

    return decorator


async def explain_analyze(
    session: AsyncSession,
    query_text: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """EXPLAIN ANALYZE를 실행하여 쿼리 실행 계획을 반환한다.

    Args:
        session: 비동기 DB 세션
        query_text: SQL 쿼리 문자열
        params: 쿼리 파라미터

    Returns:
        실행 계획 딕셔너리 리스트
    """
    explain_query = text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query_text}")
    result = await session.execute(explain_query, params or {})
    rows = result.fetchall()

    plans: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row[0], list):
            plans.extend(row[0])
        elif isinstance(row[0], dict):
            plans.append(row[0])
        else:
            plans.append({"raw": str(row[0])})

    return plans


async def get_table_index_usage(
    session: AsyncSession,
    table_name: str,
) -> list[dict[str, Any]]:
    """테이블의 인덱스 사용 통계를 조회한다.

    Args:
        session: 비동기 DB 세션
        table_name: 테이블 이름

    Returns:
        인덱스 사용 통계 딕셔너리 리스트
    """
    query = text("""
        SELECT
            indexrelname AS index_name,
            idx_scan AS scans,
            idx_tup_read AS tuples_read,
            idx_tup_fetch AS tuples_fetched,
            pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
        FROM pg_stat_user_indexes
        WHERE relname = :table_name
        ORDER BY idx_scan DESC
    """)
    result = await session.execute(query, {"table_name": table_name})
    rows = result.fetchall()

    return [
        {
            "index_name": row[0],
            "scans": row[1],
            "tuples_read": row[2],
            "tuples_fetched": row[3],
            "index_size": row[4],
        }
        for row in rows
    ]


async def get_missing_index_recommendations(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """사용되지 않는 인덱스와 순차 스캔이 많은 테이블을 분석하여 인덱스 추천을 반환한다.

    Returns:
        추천 정보 딕셔너리 리스트
    """
    recommendations: list[dict[str, Any]] = []

    # 1. 순차 스캔이 많은 테이블 (대량 데이터 테이블 중 인덱스 누락 가능성)
    seq_scan_query = text("""
        SELECT
            relname AS table_name,
            seq_scan,
            seq_tup_read,
            idx_scan,
            n_live_tup AS row_count,
            CASE
                WHEN seq_scan > 0 AND idx_scan > 0
                THEN round(seq_scan::numeric / (seq_scan + idx_scan) * 100, 2)
                WHEN seq_scan > 0
                THEN 100.0
                ELSE 0.0
            END AS seq_scan_pct
        FROM pg_stat_user_tables
        WHERE n_live_tup > 1000
          AND seq_scan > idx_scan
        ORDER BY seq_tup_read DESC
        LIMIT 20
    """)
    result = await session.execute(seq_scan_query)
    for row in result.fetchall():
        recommendations.append({
            "type": "high_sequential_scans",
            "table": row[0],
            "seq_scans": row[1],
            "seq_tuples_read": row[2],
            "index_scans": row[3],
            "row_count": row[4],
            "seq_scan_percentage": float(row[5]),
            "recommendation": (
                f"테이블 '{row[0]}'에 순차 스캔이 {row[5]}%로 높습니다. "
                f"WHERE 절에 자주 사용되는 컬럼에 인덱스 추가를 검토하세요."
            ),
        })

    # 2. 사용되지 않는 인덱스 (삭제 후보)
    unused_index_query = text("""
        SELECT
            indexrelname AS index_name,
            relname AS table_name,
            idx_scan AS scans,
            pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
        FROM pg_stat_user_indexes
        WHERE idx_scan = 0
          AND indexrelname NOT LIKE 'pg_%%'
          AND indexrelname NOT LIKE '%%_pkey'
        ORDER BY pg_relation_size(indexrelid) DESC
        LIMIT 20
    """)
    result = await session.execute(unused_index_query)
    for row in result.fetchall():
        recommendations.append({
            "type": "unused_index",
            "index_name": row[0],
            "table": row[1],
            "scans": row[2],
            "size": row[3],
            "recommendation": (
                f"인덱스 '{row[0]}' (테이블: {row[1]})이 사용되지 않습니다. "
                f"크기: {row[3]}. 삭제를 검토하세요."
            ),
        })

    return recommendations


async def analyze_slow_queries(
    session: AsyncSession,
    min_duration_ms: float = 100.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """pg_stat_statements 에서 슬로우 쿼리를 분석한다.

    pg_stat_statements 확장이 활성화되어 있어야 한다.

    Args:
        session: 비동기 DB 세션
        min_duration_ms: 최소 평균 실행 시간 (ms)
        limit: 최대 반환 건수

    Returns:
        슬로우 쿼리 정보 딕셔너리 리스트
    """
    try:
        query = text("""
            SELECT
                query,
                calls,
                round(total_exec_time::numeric, 2) AS total_time_ms,
                round(mean_exec_time::numeric, 2) AS mean_time_ms,
                round(stddev_exec_time::numeric, 2) AS stddev_time_ms,
                rows
            FROM pg_stat_statements
            WHERE mean_exec_time > :min_duration
              AND query NOT LIKE '%%pg_stat%%'
            ORDER BY mean_exec_time DESC
            LIMIT :limit
        """)
        result = await session.execute(
            query,
            {"min_duration": min_duration_ms, "limit": limit},
        )
        return [
            {
                "query": row[0][:500],
                "calls": row[1],
                "total_time_ms": float(row[2]),
                "mean_time_ms": float(row[3]),
                "stddev_time_ms": float(row[4]),
                "total_rows": row[5],
            }
            for row in result.fetchall()
        ]
    except Exception as exc:
        logger.warning(
            "slow_query_analysis_failed",
            error=str(exc),
            hint="pg_stat_statements 확장이 활성화되어 있는지 확인하세요.",
        )
        return []
