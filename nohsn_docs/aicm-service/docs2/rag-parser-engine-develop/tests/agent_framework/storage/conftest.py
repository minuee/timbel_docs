import os
import pytest
from sqlalchemy import create_engine


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")


@pytest.fixture
def db():
    url = _sync_url(os.environ["DATABASE_URL"])
    eng = create_engine(url)
    conn = eng.connect()
    try:
        yield conn
    finally:
        conn.close()
        eng.dispose()
