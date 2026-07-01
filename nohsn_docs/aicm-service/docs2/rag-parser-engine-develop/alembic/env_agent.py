"""Phase 2 T2.2 — Alembic env for *Lucas-Agent* container (shared + agent only).

env_kms.py 의 mirror. lucas-agent 컨테이너에서
``alembic -c alembic.agent.ini upgrade agent@head`` 호출 시 사용.

shared + Agent 모델만 metadata 에 등록 — KMS 모델 (block/document/chunk 등)
은 import 하지 않으므로 agent 컨테이너 알 필요 없음.

실 DB 미적용 — 본 PR 은 파일 작성 만.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.common.config import settings

# ---------------------------------------------------------------------------
# Shared + Agent 모델 import — KMS 모듈은 일부러 누락.
#
# env_kms.py 와 동일 패턴 — 전체 model load 후 filtered MetaData 구성.
# ---------------------------------------------------------------------------
from sqlalchemy import MetaData

import src.core.models  # noqa: F401 — __init__ 실행으로 전체 모델 load
# __init__.py 가 누락한 shared + agent 모델 명시 import.
import src.core.models.api_key  # noqa: F401
import src.core.models.audit_log  # noqa: F401
import src.core.models.tenant_link  # noqa: F401
import src.core.models.transition  # noqa: F401 (transition_events + lifecycle_policies)
import src.core.models.agent  # noqa: F401 (Agent + AgentChannel + ChannelInboundDedup + ChannelUserMapping)
import src.core.models.custom_tool  # noqa: F401
import src.core.models.scheduled_action  # noqa: F401
import src.core.models.lifecycle_feedback  # noqa: F401
from src.core.models.base import Base

# Alembic Config 객체
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 마이그레이션 대상 메타데이터 — kms table 미포함.
#
# spec Section 4 — Agent branch table list + shared. 하드코딩 X — audit
# (tools/alembic_audit/check_branch_consistency.py) 가 model_branches.json 과
# 정합 회귀 차단.
_AGENT_TABLES = frozenset({
    "agents", "agent_channels", "channel_inbound_dedup",
    "channel_user_mappings", "agent_documents", "custom_tools",
    "lifecycle_feedback", "scheduled_actions",
})
_SHARED_TABLES = frozenset({
    "anonymization_logs", "api_keys", "audit_logs", "dlq_messages",
    "integrations", "lifecycle_policies", "llm_usage", "tenant_links",
    "tenants", "transition_events", "user_repository_access", "users",
})
_ALLOWED_TABLES = _AGENT_TABLES | _SHARED_TABLES


def _filter_metadata(source: MetaData, allowed: frozenset[str]) -> MetaData:
    """source MetaData 에서 allowed table 만 골라 새 MetaData 반환."""
    target = MetaData()
    for tbl_name, tbl in source.tables.items():
        if tbl_name in allowed:
            tbl.to_metadata(target)
    return target


target_metadata = _filter_metadata(Base.metadata, _ALLOWED_TABLES)

_alembic_db_url = settings.DATABASE_URL_MIGRATION or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", _alembic_db_url)


def run_migrations_offline() -> None:
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
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
