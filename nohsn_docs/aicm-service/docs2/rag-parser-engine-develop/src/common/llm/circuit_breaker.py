"""Redis 기반 LLM Circuit Breaker.

프로바이더별 연속 실패를 추적하고, 임계값 초과 시 일시적으로 해당 프로바이더를 건너뛴다.
- 실패 10회 / 5분 내 → circuit OPEN (2분간 요청 차단)
- 2분 경과 → circuit HALF-OPEN (1회 시도 허용)
- 성공 → circuit CLOSED (카운터 리셋)
"""

from __future__ import annotations

import asyncio
import time

import redis.asyncio as aioredis

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

# Redis 키 패턴
_CB_FAIL_COUNT_KEY = "aicm:llm_cb:{provider}:fail_count"
_CB_OPENED_AT_KEY = "aicm:llm_cb:{provider}:opened_at"

# 임계값 상수
FAILURE_THRESHOLD = 10
"""circuit이 열리기까지 필요한 실패 횟수 (5분 윈도우 내)."""

FAILURE_WINDOW_SECONDS = 300
"""실패 카운트 윈도우 (5분)."""

OPEN_DURATION_SECONDS = 120
"""circuit이 열린 후 차단 기간 (2분)."""


class CircuitBreaker:
    """Redis 기반 Circuit Breaker.

    프로바이더 이름을 키로 사용하여 독립적으로 관리한다.
    Redis 연결 실패 시에는 circuit을 닫힌 것으로 간주하여
    LLM 라우팅 자체가 중단되지 않도록 한다.
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        """Redis 클라이언트를 lazy 초기화하여 반환한다."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL, decode_responses=True
            )
        return self._redis

    async def is_open(self, provider: str) -> bool:
        """해당 프로바이더의 circuit이 열려 있는지(=차단 상태인지) 확인한다.

        Returns:
            True이면 해당 프로바이더를 건너뛰어야 함.
        """
        try:
            r = await self._get_redis()
            opened_at_str = await r.get(
                _CB_OPENED_AT_KEY.format(provider=provider)
            )
            if opened_at_str is None:
                return False

            opened_at = float(opened_at_str)
            elapsed = time.time() - opened_at
            if elapsed >= OPEN_DURATION_SECONDS:
                # HALF-OPEN: 시간 경과 → 1회 시도 허용 (opened_at 삭제)
                await r.delete(_CB_OPENED_AT_KEY.format(provider=provider))
                log.info(
                    "llm_circuit_half_open",
                    provider=provider,
                    elapsed_seconds=round(elapsed, 1),
                )
                return False
            return True
        except Exception as exc:
            log.warning(
                "llm_circuit_breaker_redis_error",
                provider=provider,
                action="is_open",
                error=str(exc),
            )
            # Redis 장애 시 circuit closed로 간주
            return False

    async def record_failure(self, provider: str) -> None:
        """실패 1건을 기록하고, 임계값 초과 시 circuit을 연다."""
        try:
            r = await self._get_redis()
            fail_key = _CB_FAIL_COUNT_KEY.format(provider=provider)

            count = await r.incr(fail_key)
            if count == 1:
                # 첫 실패 — 윈도우 TTL 설정
                await r.expire(fail_key, FAILURE_WINDOW_SECONDS)

            if count >= FAILURE_THRESHOLD:
                opened_key = _CB_OPENED_AT_KEY.format(provider=provider)
                await r.set(
                    opened_key,
                    str(time.time()),
                    ex=OPEN_DURATION_SECONDS + 60,  # 여유 TTL
                )
                # 실패 카운터 리셋 (다음 윈도우 시작)
                await r.delete(fail_key)
                log.warning(
                    "llm_circuit_opened",
                    provider=provider,
                    failure_count=count,
                    open_duration_seconds=OPEN_DURATION_SECONDS,
                )
        except Exception as exc:
            log.warning(
                "llm_circuit_breaker_redis_error",
                provider=provider,
                action="record_failure",
                error=str(exc),
            )

    async def record_success(self, provider: str) -> None:
        """성공 시 실패 카운터를 리셋하고, circuit이 열려 있었다면 닫는다."""
        try:
            r = await self._get_redis()
            fail_key = _CB_FAIL_COUNT_KEY.format(provider=provider)
            opened_key = _CB_OPENED_AT_KEY.format(provider=provider)

            pipe = r.pipeline()
            pipe.delete(fail_key)
            pipe.delete(opened_key)
            await pipe.execute()

            log.debug("llm_circuit_success_recorded", provider=provider)
        except Exception as exc:
            log.warning(
                "llm_circuit_breaker_redis_error",
                provider=provider,
                action="record_success",
                error=str(exc),
            )

    async def reset(self, provider: str) -> None:
        """수동으로 circuit 상태를 초기화한다."""
        try:
            r = await self._get_redis()
            fail_key = _CB_FAIL_COUNT_KEY.format(provider=provider)
            opened_key = _CB_OPENED_AT_KEY.format(provider=provider)

            pipe = r.pipeline()
            pipe.delete(fail_key)
            pipe.delete(opened_key)
            await pipe.execute()

            log.info("llm_circuit_reset", provider=provider)
        except Exception as exc:
            log.warning(
                "llm_circuit_breaker_redis_error",
                provider=provider,
                action="reset",
                error=str(exc),
            )

    async def get_status(self, provider: str) -> dict:
        """프로바이더의 현재 circuit breaker 상태를 반환한다.

        Returns:
            {"state": "closed"|"open"|"half_open", "fail_count": int, "opened_at": float|None}
        """
        try:
            r = await self._get_redis()
            fail_key = _CB_FAIL_COUNT_KEY.format(provider=provider)
            opened_key = _CB_OPENED_AT_KEY.format(provider=provider)

            fail_count_str, opened_at_str = await asyncio.gather(
                r.get(fail_key),
                r.get(opened_key),
            )

            fail_count = int(fail_count_str) if fail_count_str else 0
            opened_at = float(opened_at_str) if opened_at_str else None

            if opened_at is not None:
                elapsed = time.time() - opened_at
                if elapsed >= OPEN_DURATION_SECONDS:
                    state = "half_open"
                else:
                    state = "open"
            else:
                state = "closed"

            return {
                "state": state,
                "fail_count": fail_count,
                "opened_at": opened_at,
            }
        except Exception as exc:
            log.warning(
                "llm_circuit_breaker_redis_error",
                provider=provider,
                action="get_status",
                error=str(exc),
            )
            return {
                "state": "unknown",
                "fail_count": 0,
                "opened_at": None,
                "error": str(exc),
            }


# 싱글턴 인스턴스
circuit_breaker = CircuitBreaker()
