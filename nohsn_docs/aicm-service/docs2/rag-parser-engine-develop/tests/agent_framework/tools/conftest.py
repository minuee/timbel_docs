"""테스트 격리 — Redis mock state 가 테스트 간에 새지 않게.

Week 5 polish B: mock backend 가 Redis 로 이관되면서 per-test autouse flush 는
`_redis_store._flush_all_mocks()` 로 이관. `AGENT_MOCK_REDIS_DB=2` 환경 변수로
prod Redis DB 0 과 분리.
"""
import os

import pytest
import pytest_asyncio

# prod DB (0) 침범 방지 — fixture 로딩 전에 고정
os.environ.setdefault("AGENT_MOCK_REDIS_DB", "2")

from src.agent_framework.tools import _redis_store  # noqa: E402


async def _safe_flush():
    """Redis 가 없는 환경(CI/로컬)에서도 graceful 하게 skip."""
    import redis.exceptions
    try:
        await _redis_store._flush_all_mocks()
    except (redis.exceptions.ConnectionError, OSError):
        pass


@pytest_asyncio.fixture(autouse=True)
async def _reset_mocks():
    """모든 agent_mock:* 키를 test DB 에서 flush (전/후)."""
    await _safe_flush()
    yield
    await _safe_flush()
