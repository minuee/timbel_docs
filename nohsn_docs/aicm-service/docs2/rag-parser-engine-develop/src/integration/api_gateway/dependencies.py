"""FastAPI 의존성 주입: DB 세션, Redis, 매니저 인스턴스."""

from __future__ import annotations

from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.common.config import settings

# ---------------------------------------------------------------------------
# Engine & Session factory (애플리케이션 수명에 한 번 생성)
# ---------------------------------------------------------------------------

_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    echo=settings.DATABASE_ECHO,
)

_async_session_factory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Redis pool
# ---------------------------------------------------------------------------

_redis_pool: aioredis.Redis | None = None


def _get_redis_pool() -> aioredis.Redis:
    """Redis 커넥션 풀 싱글턴."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=False,
        )
    return _redis_pool


# ---------------------------------------------------------------------------
# FastAPI Depends
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """요청 스코프 DB 세션."""
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> aioredis.Redis:
    """Redis 커넥션."""
    return _get_redis_pool()


async def get_api_key_manager():
    """APIKeyManager 의존성."""
    from src.integration.api_gateway.api_key_manager import APIKeyManager

    async with _async_session_factory() as session:
        redis = _get_redis_pool()
        manager = APIKeyManager(session=session, redis=redis)
        yield manager
        await session.commit()


async def get_rate_limiter():
    """SlidingWindowRateLimiter 의존성."""
    from src.integration.api_gateway.rate_limiter import SlidingWindowRateLimiter

    redis = _get_redis_pool()
    return SlidingWindowRateLimiter(redis=redis)


async def get_usage_tracker():
    """UsageTracker 의존성."""
    from src.integration.api_gateway.usage_tracker import UsageTracker

    redis = _get_redis_pool()
    return UsageTracker(redis=redis)
