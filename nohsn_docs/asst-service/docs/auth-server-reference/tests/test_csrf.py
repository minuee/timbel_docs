"""쿠키 경로에서만 CSRF 를 요구하는지 확인한다."""

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def csrf_client(private_key_path):
    settings = Settings(
        jwt_private_key_path=private_key_path,
        refresh_grace_seconds=2,
        session_idle_timeout_seconds=0,
        session_absolute_ttl_seconds=0,
        csrf_enabled=True,
        _env_file=None,
    )
    app = create_app(settings=settings, redis_client=FakeRedis())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client


async def test_쿠키_갱신은_CSRF_헤더가_없으면_403(csrf_client):
    await login(csrf_client)
    response = await csrf_client.post("/auth/refresh")
    assert response.status_code == 403
    assert response.json()["error"] == "csrf_failed"


async def test_쿠키_갱신은_CSRF_헤더가_맞으면_통과(csrf_client):
    tokens = await login(csrf_client)
    response = await csrf_client.post("/auth/refresh", headers={"X-CSRF-Token": tokens["csrfToken"]})
    assert response.status_code == 200


async def test_서버간_호출_body_경로는_CSRF_대상이_아니다(csrf_client):
    """앱 백엔드가 refresh 를 body 로 보내는 경로 — 브라우저 자동 자격증명이 없으니 CSRF 가 성립 안 한다."""
    tokens = await login(csrf_client)
    response = await csrf_client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 200
