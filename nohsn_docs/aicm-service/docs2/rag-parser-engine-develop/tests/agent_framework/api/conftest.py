"""API-level test isolation — Redis mock backend autouse flush.

Week 5 polish B: mock state 가 Redis 로 이관되면서 _reset() sync 대신
_redis_store 의 async flush_all_mocks 사용.
"""
import pytest_asyncio

from src.agent_framework.tools import _redis_store


@pytest_asyncio.fixture(autouse=True)
async def _reset_all_mocks():
    await _redis_store._flush_all_mocks()
    yield
    await _redis_store._flush_all_mocks()
