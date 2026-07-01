"""Alembic 비동기 마이그레이션 환경 설정."""

import os
import sys

# 프로젝트 루트를 sys.path에 추가하여 src 패키지를 import 가능하게 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.common.config import settings
from src.core.models import Base  # noqa: F401 — 모든 모델을 임포트하여 메타데이터 등록

# Alembic Config 객체
config = context.config

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 마이그레이션 대상 메타데이터
target_metadata = Base.metadata

# D32 §1 — alembic 은 항상 BYPASSRLS role (kms migration) 사용. settings 의
# DATABASE_URL_MIGRATION 우선, 부재 시 DATABASE_URL fallback (legacy 호환).
# GPT-5 §1 patch (옵션 A): KMS_DB_ROLE 강제 제거 — settings 재평가 race 회피.
_alembic_db_url = settings.DATABASE_URL_MIGRATION or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", _alembic_db_url)


def run_migrations_offline() -> None:
    """오프라인 마이그레이션 (SQL 생성만).

    DB 연결 없이 SQL 스크립트를 생성한다.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """마이그레이션 컨텍스트를 설정하고 실행한다."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """비동기 엔진으로 마이그레이션을 실행한다."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """온라인 마이그레이션 (비동기).

    asyncpg 드라이버를 사용하여 비동기로 마이그레이션한다.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
