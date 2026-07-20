import sys
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def private_key_path(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("keys") / "private.pem"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(path)


@pytest.fixture
def settings(private_key_path) -> Settings:
    return Settings(
        jwt_private_key_path=private_key_path,
        access_ttl_seconds=60,
        refresh_ttl_seconds=600,
        refresh_grace_seconds=2,
        session_idle_timeout_seconds=0,
        session_absolute_ttl_seconds=0,
        csrf_enabled=False,
        _env_file=None,
    )


@pytest_asyncio.fixture
async def client(settings):
    app = create_app(settings=settings, redis_client=FakeRedis())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # lifespan 을 돌려 app.state 를 채운다
        async with app.router.lifespan_context(app):
            yield ac


async def login(client) -> dict:
    response = await client.post("/auth/login", json={"account": "agent01", "password": "password"})
    assert response.status_code == 200, response.text
    return response.json()
