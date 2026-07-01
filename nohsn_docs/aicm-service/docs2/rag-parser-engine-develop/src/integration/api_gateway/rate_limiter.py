"""Redis 기반 Sliding Window Rate Limiter."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

import redis.asyncio as aioredis

from src.common.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    """Rate limit 검사 결과."""

    allowed: bool
    remaining: int
    retry_after: int  # 초과 시 대기 시간 (초). 허용 시 0.


class SlidingWindowRateLimiter:
    """Redis Sorted Set 기반 sliding window rate limiter.

    API 키별 + 엔드포인트별 제한을 적용한다.
    윈도우 크기: 60초 (1분).
    """

    WINDOW_SECONDS = 60
    KEY_PREFIX = "aicm:ratelimit:"

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def check(
        self,
        key_id: UUID,
        endpoint: str,
        limit: int,
    ) -> RateLimitResult:
        """Rate limit 검사.

        Args:
            key_id: API Key ID
            endpoint: 엔드포인트 경로 (예: "ext/search")
            limit: 분당 허용 요청 수

        Returns:
            RateLimitResult(allowed, remaining, retry_after)
        """
        redis_key = f"{self.KEY_PREFIX}{key_id}:{endpoint}"
        now = time.time()
        window_start = now - self.WINDOW_SECONDS

        pipe = self._redis.pipeline(transaction=True)
        # 윈도우 밖 요청 제거
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # 현재 요청 추가 (member = timestamp 문자열, score = timestamp)
        member = f"{now}:{id(pipe)}"
        pipe.zadd(redis_key, {member: now})
        # 윈도우 내 요청 수 카운트
        pipe.zcard(redis_key)
        # TTL 설정 (윈도우 + 여유)
        pipe.expire(redis_key, self.WINDOW_SECONDS + 1)
        results = await pipe.execute()

        current_count: int = results[2]
        remaining = max(0, limit - current_count)

        if current_count > limit:
            # 초과 시 — 가장 오래된 요청이 윈도우에서 빠질 때까지 대기
            oldest_entries = await self._redis.zrange(redis_key, 0, 0, withscores=True)
            if oldest_entries:
                oldest_score = oldest_entries[0][1]
                retry_after = max(1, int(oldest_score + self.WINDOW_SECONDS - now) + 1)
            else:
                retry_after = self.WINDOW_SECONDS

            # 초과한 요청 제거 (추가했지만 거부)
            await self._redis.zrem(redis_key, member)

            log.warning(
                "rate_limit_exceeded",
                key_id=str(key_id),
                endpoint=endpoint,
                limit=limit,
                current=current_count,
            )
            return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)

        return RateLimitResult(allowed=True, remaining=remaining, retry_after=0)
