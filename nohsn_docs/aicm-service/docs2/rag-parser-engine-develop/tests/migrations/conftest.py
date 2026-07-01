"""pytest fixtures for Alembic 028 migration smoke tests.

- Provides a sync SQLAlchemy `db` connection (psycopg2) derived from the
  container's async `DATABASE_URL` by swapping the driver.
- Provides `alembic_upgraded_to_028` which runs `alembic upgrade 028` once
  per test, using the project's existing async alembic env.
"""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

ALEMBIC_INI = "/app/alembic.ini"


def _sync_url() -> str:
    """Return a sync SQLAlchemy URL derived from $DATABASE_URL.

    The container injects an asyncpg URL; tests need a sync driver so we swap
    to psycopg2.
    """
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
    """Yield a sync SQLAlchemy connection inside a single transaction.

    The transaction is committed on success so that DDL-checking queries and
    inserts persist for the scope of the test function.  Errors roll back.
    """
    eng = create_engine(_sync_url(), future=True)
    with eng.begin() as conn:
        yield conn
    eng.dispose()


@pytest.fixture
def alembic_upgraded_to_028():
    """Ensure the DB is upgraded to revision 028 before the test runs."""
    cfg = Config(ALEMBIC_INI)
    command.upgrade(cfg, "028")
    yield
