"""Redis 클라이언트 유틸리티.

공통 Redis 연결 생성 및 관리를 제공한다.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)


async def get_redis_client(*, decode_responses: bool = True) -> aioredis.Redis:
    """Redis 비동기 클라이언트를 생성하여 반환한다.

    Args:
        decode_responses: 응답을 문자열로 디코딩할지 여부

    Returns:
        aioredis.Redis 클라이언트

    Raises:
        ConnectionError: Redis 연결 실패 시
    """
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=decode_responses)
    await client.ping()
    return client
