"""트래픽 이상 탐지 — API 키별 요청 패턴 모니터링.

Redis 기반 rolling window 통계를 사용하여:
- 스파이크 탐지 (>3x rolling average)
- 비정상 엔드포인트 패턴 탐지
- 업무 시간 외 트래픽 탐지

탐지 시 경고 로그 + 선택적 webhook 알림 + 선택적 자동 스로틀링.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from pydantic import BaseModel

from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

WINDOW_SECONDS = 3600  # 1시간 윈도우
BUCKET_SECONDS = 60  # 1분 단위 버킷
SPIKE_MULTIPLIER = 3.0  # 평균 대비 3배 이상이면 스파이크
MIN_BUCKETS_FOR_AVERAGE = 5  # 평균 계산에 필요한 최소 버킷 수
REDIS_KEY_PREFIX = "aicm:anomaly"

# 업무 시간 범위 (UTC 기준, KST 09:00~18:00 = UTC 00:00~09:00)
BUSINESS_HOURS_START = 0  # UTC 0시 = KST 9시
BUSINESS_HOURS_END = 9  # UTC 9시 = KST 18시


class AnomalyEvent(BaseModel):
    """탐지된 이상 이벤트."""

    anomaly_type: str  # "spike" | "unusual_endpoint" | "after_hours"
    api_key_id: str
    description: str
    current_value: float
    threshold: float
    timestamp: str
    metadata: dict[str, Any] = {}


class AnomalyAction(BaseModel):
    """이상 탐지 시 수행할 액션 설정."""

    log_warning: bool = True
    webhook_alert: bool = False
    webhook_url: str | None = None
    auto_throttle: bool = False
    throttle_rate_limit: int = 10  # 자동 스로틀 시 적용할 rate limit


class AnomalyDetector:
    """Redis 기반 트래픽 이상 탐지기.

    Args:
        redis_client: aioredis 클라이언트
        action: 이상 탐지 시 수행할 액션 설정
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        action: AnomalyAction | None = None,
    ) -> None:
        self._redis = redis_client
        self._action = action or AnomalyAction()

    # ------------------------------------------------------------------
    # 요청 기록
    # ------------------------------------------------------------------

    async def record_request(
        self,
        api_key_id: UUID,
        endpoint: str,
    ) -> list[AnomalyEvent]:
        """요청을 기록하고 이상을 탐지한다.

        Args:
            api_key_id: API 키 ID
            endpoint: 요청 엔드포인트

        Returns:
            탐지된 이상 이벤트 목록 (없으면 빈 리스트).
        """
        now = time.time()
        bucket = int(now // BUCKET_SECONDS) * BUCKET_SECONDS
        key_str = str(api_key_id)

        # 1. 요청 카운트 기록
        await self._increment_bucket(key_str, endpoint, bucket)

        # 2. 이상 탐지
        anomalies: list[AnomalyEvent] = []

        spike = await self._detect_spike(key_str, bucket)
        if spike:
            anomalies.append(spike)

        unusual = await self._detect_unusual_endpoint(key_str, endpoint, bucket)
        if unusual:
            anomalies.append(unusual)

        after_hours = self._detect_after_hours(key_str)
        if after_hours:
            anomalies.append(after_hours)

        # 3. 액션 수행
        for event in anomalies:
            await self._handle_anomaly(event)

        return anomalies

    # ------------------------------------------------------------------
    # 통계 조회
    # ------------------------------------------------------------------

    async def get_request_rate(
        self,
        api_key_id: UUID,
        window_minutes: int = 60,
    ) -> dict[str, Any]:
        """API 키의 요청 비율 통계를 조회한다.

        Returns:
            total_requests, requests_per_minute, peak_minute 등.
        """
        key_str = str(api_key_id)
        now = time.time()
        window_start = int((now - window_minutes * 60) // BUCKET_SECONDS) * BUCKET_SECONDS

        rate_key = f"{REDIS_KEY_PREFIX}:rate:{key_str}"
        buckets = await self._redis.zrangebyscore(
            rate_key, window_start, "+inf", withscores=True
        )

        total = 0
        peak = 0
        for _, score in buckets:
            count = int(score)
            total += count
            peak = max(peak, count)

        return {
            "total_requests": total,
            "bucket_count": len(buckets),
            "requests_per_minute": total / max(1, len(buckets)),
            "peak_requests_per_minute": peak,
            "window_minutes": window_minutes,
        }

    # ------------------------------------------------------------------
    # 내부 — 기록
    # ------------------------------------------------------------------

    async def _increment_bucket(
        self,
        key_str: str,
        endpoint: str,
        bucket: int,
    ) -> None:
        """1분 버킷에 요청 카운트를 증가시킨다."""
        rate_key = f"{REDIS_KEY_PREFIX}:rate:{key_str}"
        endpoint_key = f"{REDIS_KEY_PREFIX}:endpoint:{key_str}"

        pipe = self._redis.pipeline()
        # rate 버킷: member=bucket timestamp, score=count
        pipe.zincrby(rate_key, 1, str(bucket))
        # 오래된 버킷 제거 (1시간 윈도우 밖)
        cutoff = bucket - WINDOW_SECONDS
        pipe.zremrangebyscore(rate_key, 0, cutoff)
        pipe.expire(rate_key, WINDOW_SECONDS + BUCKET_SECONDS)

        # 엔드포인트별 카운트
        pipe.hincrby(endpoint_key, endpoint, 1)
        pipe.expire(endpoint_key, WINDOW_SECONDS)

        await pipe.execute()

    # ------------------------------------------------------------------
    # 내부 — 탐지
    # ------------------------------------------------------------------

    async def _detect_spike(
        self,
        key_str: str,
        current_bucket: int,
    ) -> AnomalyEvent | None:
        """현재 버킷의 요청 수가 rolling average의 3배를 초과하는지 탐지."""
        rate_key = f"{REDIS_KEY_PREFIX}:rate:{key_str}"

        # 모든 버킷 조회
        buckets = await self._redis.zrangebyscore(
            rate_key, "-inf", "+inf", withscores=True
        )

        if len(buckets) < MIN_BUCKETS_FOR_AVERAGE:
            return None

        current_count = 0
        other_counts: list[float] = []

        for member, score in buckets:
            member_str = member.decode() if isinstance(member, bytes) else str(member)
            if member_str == str(current_bucket):
                current_count = int(score)
            else:
                other_counts.append(score)

        if not other_counts:
            return None

        avg = sum(other_counts) / len(other_counts)
        threshold = avg * SPIKE_MULTIPLIER

        if avg > 0 and current_count > threshold:
            return AnomalyEvent(
                anomaly_type="spike",
                api_key_id=key_str,
                description=(
                    f"요청 스파이크 감지: 현재 {current_count}건/분, "
                    f"평균 {avg:.1f}건/분 (임계치: {threshold:.1f})"
                ),
                current_value=float(current_count),
                threshold=threshold,
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata={"average": avg, "bucket_count": len(other_counts)},
            )

        return None

    async def _detect_unusual_endpoint(
        self,
        key_str: str,
        endpoint: str,
        bucket: int,
    ) -> AnomalyEvent | None:
        """평소 사용하지 않던 엔드포인트에 갑자기 대량 요청이 오는지 탐지."""
        endpoint_key = f"{REDIS_KEY_PREFIX}:endpoint:{key_str}"
        all_counts = await self._redis.hgetall(endpoint_key)

        if not all_counts:
            return None

        total = sum(int(v) for v in all_counts.values())
        endpoint_bytes = endpoint.encode() if isinstance(endpoint, str) else endpoint
        endpoint_count = int(all_counts.get(endpoint_bytes, all_counts.get(endpoint, 0)))

        if total < 20:
            return None

        # 특정 엔드포인트가 전체의 95% 이상 차지하면 비정상 패턴
        ratio = endpoint_count / total if total > 0 else 0
        if ratio > 0.95 and endpoint_count > 50:
            return AnomalyEvent(
                anomaly_type="unusual_endpoint",
                api_key_id=key_str,
                description=(
                    f"비정상 엔드포인트 패턴: {endpoint}에 "
                    f"{endpoint_count}/{total}건 집중 ({ratio:.1%})"
                ),
                current_value=ratio,
                threshold=0.95,
                timestamp=datetime.now(timezone.utc).isoformat(),
                metadata={"endpoint": endpoint, "endpoint_count": endpoint_count, "total": total},
            )

        return None

    def _detect_after_hours(
        self,
        key_str: str,
    ) -> AnomalyEvent | None:
        """업무 시간 외 트래픽 탐지."""
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour

        if BUSINESS_HOURS_START <= hour < BUSINESS_HOURS_END:
            return None

        return AnomalyEvent(
            anomaly_type="after_hours",
            api_key_id=key_str,
            description=(
                f"업무 시간 외 요청 감지: UTC {now_utc.strftime('%H:%M')} "
                f"(업무시간: UTC {BUSINESS_HOURS_START:02d}:00~{BUSINESS_HOURS_END:02d}:00)"
            ),
            current_value=float(hour),
            threshold=float(BUSINESS_HOURS_END),
            timestamp=now_utc.isoformat(),
        )

    # ------------------------------------------------------------------
    # 내부 — 액션 처리
    # ------------------------------------------------------------------

    async def _handle_anomaly(self, event: AnomalyEvent) -> None:
        """탐지된 이상에 대한 액션을 수행한다."""
        if self._action.log_warning:
            log.warning(
                "traffic_anomaly_detected",
                anomaly_type=event.anomaly_type,
                api_key_id=event.api_key_id,
                description=event.description,
                current_value=event.current_value,
                threshold=event.threshold,
            )

        if self._action.webhook_alert and self._action.webhook_url:
            await self._send_webhook_alert(event)

        if self._action.auto_throttle and event.anomaly_type == "spike":
            await self._apply_throttle(event.api_key_id)

    async def _send_webhook_alert(self, event: AnomalyEvent) -> None:
        """Webhook으로 이상 알림 전송."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    self._action.webhook_url,  # type: ignore[arg-type]
                    json=event.model_dump(),
                    headers={"Content-Type": "application/json"},
                )
            log.info("anomaly_webhook_sent", anomaly_type=event.anomaly_type)
        except Exception as e:
            log.error("anomaly_webhook_failed", error=str(e))

    async def _apply_throttle(self, api_key_id: str) -> None:
        """자동 스로틀 적용 — Redis에 임시 rate limit 설정."""
        throttle_key = f"{REDIS_KEY_PREFIX}:throttle:{api_key_id}"
        await self._redis.setex(
            throttle_key,
            300,  # 5분간 스로틀
            str(self._action.throttle_rate_limit),
        )
        log.warning(
            "auto_throttle_applied",
            api_key_id=api_key_id,
            rate_limit=self._action.throttle_rate_limit,
            duration_seconds=300,
        )
