"""agent_framework 테스트 공통 conftest.

- Redis mock DB 는 테스트 전용 DB 2 로 분리 (AGENT_MOCK_REDIS_DB=2).
  → _redis_store 가 import 될 때 이 값을 읽음.
- redis_client fixture 는 DB 2 flushdb 후 client 반환.
"""
import os

# Agent mock Redis DB 를 테스트용 2 로 고정 — prod DB 0 침범 방지.
# 이 설정은 _redis_store._current_db() 가 매 호출 읽어가므로 import 시점 무관.
os.environ.setdefault("AGENT_MOCK_REDIS_DB", "2")

import pytest_asyncio
import redis.asyncio as aioredis

from src.common.config import settings


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # 테스트 DB 2 사용, 시작/끝 flushdb
    await client.execute_command("SELECT", "2")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()
