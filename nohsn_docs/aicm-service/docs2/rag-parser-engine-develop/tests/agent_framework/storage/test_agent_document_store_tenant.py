"""Phase 11 — agent_document_store 의 직접 ``tenant_id`` 컬럼 동작 검증.

migration 030 이후 documents.tenant_id 가 NOT NULL. 본 테스트는:
- create_item 이 d.tenant_id 를 직접 채우는지
- list_items_global_doctype 의 tenant_id kwarg 가 단일 tenant 로 좁히는지
- list_tenants_with_doctype 의 tenant_id kwarg 가 단일 tenant 로 좁히는지
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage.agent_document_store import (
    AGENT_DATA_REPO_NAME,
    create_item,
    list_items_global_doctype,
    list_tenants_with_doctype,
)
from src.common.config import settings


TEST_TENANT_SLUG_PREFIX = "agds_phase11__"


async def _make_tenant(conn, slug: str) -> UUID:
    r = await conn.execute(
        text(
            """
            INSERT INTO tenants
              (id, slug, name, tenant_type, plan, config, context_config, is_active)
            VALUES
              (gen_random_uuid(), :slug, :name, 'personal', 'free',
               '{}'::jsonb, '{}'::jsonb, true)
            RETURNING id
            """
        ),
        {"slug": slug, "name": slug},
    )
    return r.scalar_one()


async def _cleanup_tenant(engine: AsyncEngine, tenant_id: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                DELETE FROM documents
                WHERE repository_id IN (
                    SELECT id FROM repositories
                    WHERE tenant_id = :tid AND name = :repo
                )
                """
            ),
            {"tid": tenant_id, "repo": AGENT_DATA_REPO_NAME},
        )
        await conn.execute(
            text("DELETE FROM repositories WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM document_types WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.DATABASE_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def tenant_a(engine: AsyncEngine):
    slug = f"{TEST_TENANT_SLUG_PREFIX}a_{uuid4().hex[:8]}"
    async with engine.begin() as conn:
        tid = await _make_tenant(conn, slug)
    yield tid
    await _cleanup_tenant(engine, tid)


@pytest_asyncio.fixture
async def tenant_b(engine: AsyncEngine):
    slug = f"{TEST_TENANT_SLUG_PREFIX}b_{uuid4().hex[:8]}"
    async with engine.begin() as conn:
        tid = await _make_tenant(conn, slug)
    yield tid
    await _cleanup_tenant(engine, tid)


@pytest.mark.asyncio
async def test_create_item_populates_direct_tenant_id_column(
    engine: AsyncEngine, tenant_a: UUID
):
    """migration 030 후 create_item 이 documents.tenant_id 를 직접 채우는지."""
    doc_id = await create_item(
        engine, tenant_a, "agent_schedule",
        title="phase11", body={"when": "2026-05-01"},
    )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT tenant_id FROM documents WHERE id = :id"),
                {"id": doc_id},
            )
        ).first()
    assert row is not None
    assert row[0] == tenant_a, "documents.tenant_id 가 직접 채워져야 함"


@pytest.mark.asyncio
async def test_list_items_global_doctype_with_tenant_filter(
    engine: AsyncEngine, tenant_a: UUID, tenant_b: UUID
):
    """tenant_id kwarg 주어지면 해당 tenant 로만 좁힘 — 다른 tenant 안 나옴."""
    await create_item(
        engine, tenant_a, "agent_reminder",
        title="A 의 리마인더", body={"at": "2026-05-01"},
    )
    await create_item(
        engine, tenant_b, "agent_reminder",
        title="B 의 리마인더", body={"at": "2026-05-02"},
    )

    # A 만 — 단일 tenant 모드
    items_a = await list_items_global_doctype(
        engine, "agent_reminder", tenant_id=tenant_a
    )
    titles_a = [i["title"] for i in items_a if i["tenant_id"] == str(tenant_a)]
    assert "A 의 리마인더" in titles_a
    other = [i for i in items_a if i["tenant_id"] != str(tenant_a)]
    assert other == [], f"tenant_id 필터 누락 — 다른 tenant doc 노출: {other}"

    # 필터 없음 — 전역 (legacy 동작 유지)
    items_all = await list_items_global_doctype(engine, "agent_reminder")
    titles_all = [i["title"] for i in items_all]
    assert "A 의 리마인더" in titles_all
    assert "B 의 리마인더" in titles_all


@pytest.mark.asyncio
async def test_list_tenants_with_doctype_with_tenant_filter(
    engine: AsyncEngine, tenant_a: UUID, tenant_b: UUID
):
    """tenant_id kwarg — 단일 tenant 만 검사."""
    await create_item(
        engine, tenant_a, "agent_news_sub",
        title="A 구독", body={"topic": "AI"},
    )
    await create_item(
        engine, tenant_b, "agent_news_sub",
        title="B 구독", body={"topic": "헬스"},
    )

    # A 만
    only_a = await list_tenants_with_doctype(
        engine, "agent_news_sub", tenant_id=tenant_a
    )
    assert tenant_a in only_a
    assert tenant_b not in only_a

    # 필터 없음 — 둘 다
    all_tenants = await list_tenants_with_doctype(engine, "agent_news_sub")
    assert tenant_a in all_tenants
    assert tenant_b in all_tenants
