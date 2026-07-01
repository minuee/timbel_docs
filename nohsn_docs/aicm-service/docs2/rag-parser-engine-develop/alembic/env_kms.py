"""Phase 2 T2.2 — Alembic env for *Lucas-KMS* container (shared + kms only).

기존 ``alembic/env.py`` 는 *모든* 모델을 import (full deployment 호환).
본 파일은 lucas-kms 컨테이너에서 ``alembic -c alembic.kms.ini upgrade kms@head``
호출 시 사용되며, **shared + KMS 모델만** metadata 에 등록한다.

핵심 차이 (env.py 대비):
1. ``from src.core.models import Base`` 로 *전체* 를 import 하지 않는다.
2. shared/kms 도메인 모듈만 명시 import → SQLAlchemy 가 agent table 을 모름.
3. ``alembic upgrade head`` 는 *모든 head* 를 적용하므로 ``kms@head`` 같이
   branch label 을 명시해야 한다. ``alembic.kms.ini`` 가 이 호출 패턴을 강제.

설계 원칙:
- 하드코딩 X — shared/kms branch 의 모델 파일 목록은
  ``tools/alembic_audit/model_branches.json`` 과 정합. 자동 audit
  (tools/alembic_audit/check_branch_consistency.py) 가 회귀 보호.
- 기존 env.py 작동 변경 X — alembic.ini (full) 는 그대로.

실 DB 미적용 — 본 PR 은 파일 작성 만.
"""

import os
import sys

# 프로젝트 루트를 sys.path 에 추가 (env.py 와 동일 패턴).
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.common.config import settings

# ---------------------------------------------------------------------------
# Shared + KMS 모델 import — agent 모듈은 일부러 누락.
#
# 핵심 제약: ``src.core.models.__init__`` 가 AgentDocument 까지 전이 import 하므로
# 단순 모듈 import 만으로는 metadata 격리 불가. 대신 *모든 model 을 load 한 후
# 자기 branch + shared table 만 포함한 새 MetaData 를 구성* (filtered metadata).
# alembic 의 ``target_metadata`` 는 MetaData 객체이므로 본 fitering 으로 OK.
# ---------------------------------------------------------------------------
from sqlalchemy import MetaData

import src.core.models  # noqa: F401 — __init__ 실행으로 전체 모델 load
# __init__.py 가 누락한 shared 모델 명시 import.
import src.core.models.api_key  # noqa: F401
import src.core.models.audit_log  # noqa: F401
import src.core.models.tenant_link  # noqa: F401
import src.core.models.transition  # noqa: F401 (transition_events + lifecycle_policies)
from src.core.models.base import Base

# Alembic Config 객체
config = context.config

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 마이그레이션 대상 메타데이터 — agent table 미포함.
#
# spec Section 4 — KMS branch table list (+ document_categories assoc + shared).
# 하드코딩 X — ``tools/alembic_audit/model_branches.json`` 과 정합. CI audit
# (tools/alembic_audit/check_branch_consistency.py) 가 회귀 차단.
_KMS_TABLES = frozenset({
    # KMS (10) + document_categories assoc (11)
    "blocks", "categories", "chunks", "document_categories", "document_types",
    "documents", "intent_logs", "library_folders", "repositories",
    "search_logs", "sections",
})
_SHARED_TABLES = frozenset({
    "anonymization_logs", "api_keys", "audit_logs", "dlq_messages",
    "integrations", "lifecycle_policies", "llm_usage", "tenant_links",
    "tenants", "transition_events", "user_repository_access", "users",
})
_ALLOWED_TABLES = _KMS_TABLES | _SHARED_TABLES


def _filter_metadata(source: MetaData, allowed: frozenset[str]) -> MetaData:
    """source MetaData 에서 allowed table 만 골라 새 MetaData 반환.

    SQLAlchemy reflection 없이 ``Table.tometadata()`` 로 copy. FK 가 같은 set
    바깥을 가리키면 (예: KMS table 의 user_id FK) 그 FK 는 *target metadata 내부
    참조* 가 안 되지만 ``include_object`` filter 가 아닌 metadata copy 라서 안전
    하다. autogenerate 시는 본 metadata 의 table list 만 비교 대상.
    """
    target = MetaData()
    for tbl_name, tbl in source.tables.items():
        if tbl_name in allowed:
            tbl.to_metadata(target)
    return target


target_metadata = _filter_metadata(Base.metadata, _ALLOWED_TABLES)

_alembic_db_url = settings.DATABASE_URL_MIGRATION or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", _alembic_db_url)


def run_migrations_offline() -> None:
    """오프라인 마이그레이션 (SQL 생성만)."""
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
    """온라인 마이그레이션 (비동기)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
