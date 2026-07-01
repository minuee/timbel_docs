"""API 사용량 추적 — Redis 기반 카운터 + 레이턴시 분석 + 이상 탐지.

Phase 2 강화:
- Per-endpoint latency percentiles (p50, p95, p99)
- Error rate tracking
- Daily/weekly/monthly aggregation
- Anomaly detection (spike > 3x average -> alert)
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import redis.asyncio as aioredis
from pydantic import BaseModel

from src.common.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic 모델
# ---------------------------------------------------------------------------


class DailyTrend(BaseModel):
    """일별 사용량 추이."""

    date: str
    count: int


class LatencyPercentiles(BaseModel):
    """레이턴시 백분위수."""

    p50: float
    p95: float
    p99: float


class EndpointStats(BaseModel):
    """엔드포인트별 통계."""

    total_requests: int
    error_count: int
    error_rate: float
    latency: LatencyPercentiles | None = None


class AnomalyAlert(BaseModel):
    """이상 탐지 경고."""

    endpoint: str
    current_count: int
    average_count: float
    spike_ratio: float
    alert_time: str


class UsageStats(BaseModel):
    """API Key 사용량 통계."""

    total_requests: int
    by_endpoint: dict[str, int]
    daily_trend: list[DailyTrend]
    avg_latency_ms: float
    latency_percentiles: LatencyPercentiles | None = None
    endpoint_stats: dict[str, EndpointStats] | None = None
    error_rate: float = 0.0
    total_errors: int = 0
    anomalies: list[AnomalyAlert] | None = None


class AggregatedUsage(BaseModel):
    """기간별 집계 사용량."""

    period: str
    total_requests: int
    total_errors: int
    error_rate: float
    avg_latency_ms: float
    latency_percentiles: LatencyPercentiles | None = None
    by_endpoint: dict[str, int]


# ---------------------------------------------------------------------------
# UsageTracker
# ---------------------------------------------------------------------------


class UsageTracker:
    """API 키별 사용량 추적.

    Redis 키 구조:
    - aicm:usage:{key_id}:daily:{YYYY-MM-DD} — 엔드포인트별 호출 수 (Hash)
    - aicm:usage:{key_id}:errors:{YYYY-MM-DD} — 엔드포인트별 에러 수 (Hash)
    - aicm:usage:{key_id}:latency — 최근 레이턴시 전체 (List, 최대 5000건)
    - aicm:usage:{key_id}:latency:{endpoint} — 엔드포인트별 레이턴시 (List)

    TTL: 90일 자동 만료.
    """

    DAILY_PREFIX = "aicm:usage"
    LATENCY_KEY_SUFFIX = "latency"
    ERRORS_KEY_SUFFIX = "errors"
    TTL_DAYS = 90
    MAX_LATENCY_ENTRIES = 5000
    ANOMALY_SPIKE_THRESHOLD = 3.0  # 3x average 이상이면 알림

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def track(
        self,
        key_id: UUID,
        endpoint: str,
        latency_ms: int,
        is_error: bool = False,
    ) -> None:
        """API 호출 기록. Fire-and-forget 방식으로 호출한다."""
        today = date.today().isoformat()
        daily_key = f"{self.DAILY_PREFIX}:{key_id}:daily:{today}"
        latency_key = f"{self.DAILY_PREFIX}:{key_id}:{self.LATENCY_KEY_SUFFIX}"
        ep_latency_key = (
            f"{self.DAILY_PREFIX}:{key_id}:{self.LATENCY_KEY_SUFFIX}:{endpoint}"
        )
        ttl_seconds = self.TTL_DAYS * 86400

        pipe = self._redis.pipeline(transaction=False)
        # 엔드포인트별 호출 수 증가
        pipe.hincrby(daily_key, endpoint, 1)
        pipe.expire(daily_key, ttl_seconds)
        # 전체 레이턴시 기록
        pipe.lpush(latency_key, latency_ms)
        pipe.ltrim(latency_key, 0, self.MAX_LATENCY_ENTRIES - 1)
        pipe.expire(latency_key, ttl_seconds)
        # 엔드포인트별 레이턴시 기록
        pipe.lpush(ep_latency_key, latency_ms)
        pipe.ltrim(ep_latency_key, 0, self.MAX_LATENCY_ENTRIES - 1)
        pipe.expire(ep_latency_key, ttl_seconds)

        # 에러 추적
        if is_error:
            errors_key = f"{self.DAILY_PREFIX}:{key_id}:{self.ERRORS_KEY_SUFFIX}:{today}"
            pipe.hincrby(errors_key, endpoint, 1)
            pipe.expire(errors_key, ttl_seconds)

        await pipe.execute()

    async def get_usage(
        self,
        key_id: UUID,
        period: str = "7d",
    ) -> UsageStats:
        """사용량 조회 (기본 + 상세).

        Args:
            key_id: API Key ID
            period: 조회 기간 ("1d", "7d", "30d", "90d")
        """
        days = _parse_period(period)
        today = date.today()

        total_requests = 0
        total_errors = 0
        by_endpoint: dict[str, int] = {}
        by_endpoint_errors: dict[str, int] = {}
        daily_trend: list[DailyTrend] = []

        for offset in range(days):
            d = today - timedelta(days=offset)
            d_str = d.isoformat()
            daily_key = f"{self.DAILY_PREFIX}:{key_id}:daily:{d_str}"
            errors_key = f"{self.DAILY_PREFIX}:{key_id}:{self.ERRORS_KEY_SUFFIX}:{d_str}"

            day_data: dict[bytes, bytes] = await self._redis.hgetall(daily_key)
            error_data: dict[bytes, bytes] = await self._redis.hgetall(errors_key)

            day_total = 0
            for ep_bytes, count_bytes in day_data.items():
                ep = ep_bytes.decode() if isinstance(ep_bytes, bytes) else ep_bytes
                count = int(count_bytes)
                by_endpoint[ep] = by_endpoint.get(ep, 0) + count
                day_total += count
                total_requests += count

            for ep_bytes, count_bytes in error_data.items():
                ep = ep_bytes.decode() if isinstance(ep_bytes, bytes) else ep_bytes
                err_count = int(count_bytes)
                by_endpoint_errors[ep] = by_endpoint_errors.get(ep, 0) + err_count
                total_errors += err_count

            daily_trend.append(DailyTrend(date=d_str, count=day_total))

        # 최신순 -> 오래된순 정렬
        daily_trend.reverse()

        # 전체 레이턴시 분석
        latency_key = f"{self.DAILY_PREFIX}:{key_id}:{self.LATENCY_KEY_SUFFIX}"
        latencies_raw = await self._redis.lrange(
            latency_key, 0, self.MAX_LATENCY_ENTRIES - 1
        )
        avg_latency = 0.0
        latency_percentiles = None

        if latencies_raw:
            latencies = sorted([int(v) for v in latencies_raw])
            avg_latency = sum(latencies) / len(latencies)
            latency_percentiles = _compute_percentiles(latencies)

        # 엔드포인트별 상세 통계
        endpoint_stats: dict[str, EndpointStats] = {}
        for ep, req_count in by_endpoint.items():
            err_count = by_endpoint_errors.get(ep, 0)
            error_rate = err_count / req_count if req_count > 0 else 0.0

            # 엔드포인트별 레이턴시
            ep_latency_key = (
                f"{self.DAILY_PREFIX}:{key_id}:{self.LATENCY_KEY_SUFFIX}:{ep}"
            )
            ep_latencies_raw = await self._redis.lrange(ep_latency_key, 0, 999)
            ep_percentiles = None
            if ep_latencies_raw:
                ep_latencies = sorted([int(v) for v in ep_latencies_raw])
                ep_percentiles = _compute_percentiles(ep_latencies)

            endpoint_stats[ep] = EndpointStats(
                total_requests=req_count,
                error_count=err_count,
                error_rate=round(error_rate, 4),
                latency=ep_percentiles,
            )

        # 이상 탐지
        anomalies = await self._detect_anomalies(key_id, by_endpoint, days)

        error_rate = total_errors / total_requests if total_requests > 0 else 0.0

        return UsageStats(
            total_requests=total_requests,
            by_endpoint=by_endpoint,
            daily_trend=daily_trend,
            avg_latency_ms=round(avg_latency, 2),
            latency_percentiles=latency_percentiles,
            endpoint_stats=endpoint_stats,
            error_rate=round(error_rate, 4),
            total_errors=total_errors,
            anomalies=anomalies or None,
        )

    async def get_aggregated_usage(
        self,
        key_id: UUID,
        period: str = "weekly",
    ) -> AggregatedUsage:
        """기간별 집계 사용량 (daily/weekly/monthly).

        Args:
            key_id: API Key ID
            period: "daily", "weekly", "monthly"
        """
        days_map = {"daily": 1, "weekly": 7, "monthly": 30}
        days = days_map.get(period, 7)

        stats = await self.get_usage(key_id, f"{days}d")

        latency_key = f"{self.DAILY_PREFIX}:{key_id}:{self.LATENCY_KEY_SUFFIX}"
        latencies_raw = await self._redis.lrange(latency_key, 0, self.MAX_LATENCY_ENTRIES - 1)
        percentiles = None
        if latencies_raw:
            latencies = sorted([int(v) for v in latencies_raw])
            percentiles = _compute_percentiles(latencies)

        return AggregatedUsage(
            period=period,
            total_requests=stats.total_requests,
            total_errors=stats.total_errors,
            error_rate=stats.error_rate,
            avg_latency_ms=stats.avg_latency_ms,
            latency_percentiles=percentiles,
            by_endpoint=stats.by_endpoint,
        )

    async def _detect_anomalies(
        self,
        key_id: UUID,
        current_by_endpoint: dict[str, int],
        current_days: int,
    ) -> list[AnomalyAlert]:
        """현재 기간의 사용량과 이전 기간 평균을 비교하여 이상 탐지.

        spike > 3x average 이면 경고.
        """
        anomalies: list[AnomalyAlert] = []
        today = date.today()

        # 이전 기간 (동일 길이) 평균 계산
        prev_by_endpoint: dict[str, int] = {}
        for offset in range(current_days, current_days * 2):
            d = today - timedelta(days=offset)
            daily_key = f"{self.DAILY_PREFIX}:{key_id}:daily:{d.isoformat()}"
            day_data = await self._redis.hgetall(daily_key)
            for ep_bytes, count_bytes in day_data.items():
                ep = ep_bytes.decode() if isinstance(ep_bytes, bytes) else ep_bytes
                count = int(count_bytes)
                prev_by_endpoint[ep] = prev_by_endpoint.get(ep, 0) + count

        # 비교
        now_str = datetime.now(timezone.utc).isoformat()
        for ep, current_count in current_by_endpoint.items():
            prev_count = prev_by_endpoint.get(ep, 0)
            if prev_count == 0:
                continue  # 이전 데이터 없으면 비교 불가

            avg_count = prev_count / max(current_days, 1)
            if avg_count > 0 and current_count > avg_count * self.ANOMALY_SPIKE_THRESHOLD:
                spike_ratio = round(current_count / avg_count, 2)
                anomalies.append(
                    AnomalyAlert(
                        endpoint=ep,
                        current_count=current_count,
                        average_count=round(avg_count, 2),
                        spike_ratio=spike_ratio,
                        alert_time=now_str,
                    )
                )
                log.warning(
                    "usage_anomaly_detected",
                    key_id=str(key_id),
                    endpoint=ep,
                    current=current_count,
                    average=round(avg_count, 2),
                    spike_ratio=spike_ratio,
                )

        return anomalies


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _parse_period(period: str) -> int:
    """기간 문자열 -> 일 수. 기본 7일."""
    mapping = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
    return mapping.get(period, 7)


def _compute_percentiles(sorted_values: list[int]) -> LatencyPercentiles:
    """정렬된 값 목록에서 p50, p95, p99 계산."""
    n = len(sorted_values)
    if n == 0:
        return LatencyPercentiles(p50=0.0, p95=0.0, p99=0.0)

    def _percentile(pct: float) -> float:
        idx = (pct / 100.0) * (n - 1)
        lower = int(math.floor(idx))
        upper = min(lower + 1, n - 1)
        weight = idx - lower
        return round(
            sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight,
            2,
        )

    return LatencyPercentiles(
        p50=_percentile(50),
        p95=_percentile(95),
        p99=_percentile(99),
    )
