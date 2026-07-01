"""pytest fixtures for scripts/loadtest tests.

Reuses the same sync SQLAlchemy connection idiom as tests/migrations/conftest.py.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine


def _sync_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@pytest.fixture
def db():
    eng = create_engine(_sync_url(), future=True)
    with eng.begin() as conn:
        yield conn
    eng.dispose()
