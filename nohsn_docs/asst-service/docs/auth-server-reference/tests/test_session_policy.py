"""부록 C 세션 정책(유휴·절대 만료)이 설정값만으로 동작하는지 확인한다."""

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import login

pytestmark = pytest.mark.asyncio


def _settings(private_key_path, **overrides) -> Settings:
    base = dict(
        jwt_private_key_path=private_key_path,
        access_ttl_seconds=60,
        refresh_ttl_seconds=600,
        refresh_grace_seconds=2,
        csrf_enabled=False,
        _env_file=None,
    )
    return Settings(**{**base, **overrides})


@pytest_asyncio.fixture
async def make_client():
    async def _make(settings: Settings):
        app = create_app(settings=settings, redis_client=FakeRedis())
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        await client.__aenter__()
        await app.router.lifespan_context(app).__aenter__()
        return client

    return _make


async def test_유휴_타임아웃을_넘기면_갱신이_거부된다(private_key_path, make_client):
    # 무조작 1초만 지나도 만료되는 극단 설정으로 정책이 걸리는지만 본다
    settings = _settings(private_key_path, session_idle_timeout_seconds=1, session_absolute_ttl_seconds=0)
    client = await make_client(settings)

    tokens = await login(client)
    import asyncio

    await asyncio.sleep(2)

    response = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 401
    assert response.json()["error"] == "session_idle_timeout"


async def test_절대_만료를_넘기면_재로그인이_필요하다(private_key_path, make_client):
    settings = _settings(private_key_path, session_idle_timeout_seconds=0, session_absolute_ttl_seconds=1)
    client = await make_client(settings)

    tokens = await login(client)
    import asyncio

    await asyncio.sleep(2)

    response = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 401
    assert response.json()["error"] == "session_absolute_timeout"


async def test_정책을_끄면_계속_갱신된다(private_key_path, make_client):
    settings = _settings(private_key_path, session_idle_timeout_seconds=0, session_absolute_ttl_seconds=0)
    client = await make_client(settings)

    tokens = await login(client)
    response = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 200
