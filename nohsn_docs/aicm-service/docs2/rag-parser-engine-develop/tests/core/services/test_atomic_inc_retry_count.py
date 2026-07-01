"""atomic_inc_retry_count — UPDATE RETURNING + expected CAS 검증.

spec §3.5 — publish 전 원자적 retry_count 선점.

DB: 컨테이너의 실 Postgres. 테스트마다 자체 doc INSERT/cleanup.
audit_service 테스트 패턴 (per-test engine — pytest-asyncio loop 충돌 회피) 차용.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.common.config import settings
from src.core.services.document_service import DocumentService


_TEST_TENANT_ID = "00000000-0000-0000-0000-000000000000"
_TEST_REPO_ID = "00000000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture
async def session_factory():
    """테스트별 engine/sessionmaker — pytest-asyncio per-test loop 호환."""
    eng = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=False,
        pool_size=5,
        max_overflow=5,
    )
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await eng.dispose()


@pytest_asyncio.fixture
async def sample_doc_id(session_factory):
    """draft 상태 sample doc — retry_count 0 (processing_meta 비어있음).

    실 DB 에 존재하는 임의 repository 한 건을 선택해 그 tenant/repo 로 doc 생성.
    cleanup 포함.
    """
    did = uuid4()
    async with session_factory() as s:
        row = (await s.execute(
            text("SELECT id, tenant_id FROM repositories LIMIT 1")
        )).first()
        if row is None:
            pytest.skip("no repository in DB to attach test doc to")
        repo_id, tenant_id = row[0], row[1]
        await s.execute(text("""
            INSERT INTO documents (id, tenant_id, repository_id, title,
                                   status, processing_meta)
            VALUES (CAST(:id AS uuid), :tid, :rid,
                    'atomic-inc-test', 'draft', '{}'::jsonb)
        """), {"id": str(did), "tid": tenant_id, "rid": repo_id})
        await s.commit()
    yield did
    async with session_factory() as s:
        await s.execute(
            text("DELETE FROM documents WHERE id=CAST(:id AS uuid)"),
            {"id": str(did)},
        )
        await s.commit()


@pytest.mark.asyncio
async def test_atomic_inc_from_zero(session_factory, sample_doc_id):
    """expected=0 + 실제 retry_count=0 → 1 로 증가, 1 반환."""
    async with session_factory() as s:
        svc = DocumentService(s)
        new_count = await svc.atomic_inc_retry_count(sample_doc_id, expected=0)
    assert new_count == 1

    # DB 검증 — 실제로 1 이 저장되었는지
    async with session_factory() as s:
        row = await s.execute(
            text("SELECT (processing_meta->>'retry_count')::int AS rc "
                 "FROM documents WHERE id=CAST(:id AS uuid)"),
            {"id": str(sample_doc_id)},
        )
        rc = row.scalar()
    assert rc == 1


@pytest.mark.asyncio
async def test_atomic_inc_already_incremented(session_factory, sample_doc_id):
    """expected=0 인데 실제 retry_count=1 (이미 다른 시도가 inc) → None 반환."""
    async with session_factory() as s:
        svc = DocumentService(s)
        first = await svc.atomic_inc_retry_count(sample_doc_id, expected=0)
        assert first == 1
    # 다시 expected=0 으로 호출 — 실제는 이미 1 이라 CAS 실패
    async with session_factory() as s:
        svc = DocumentService(s)
        result = await svc.atomic_inc_retry_count(sample_doc_id, expected=0)
    assert result is None


@pytest.mark.asyncio
async def test_atomic_inc_doc_not_found(session_factory):
    """존재 안 하는 doc → None."""
    async with session_factory() as s:
        svc = DocumentService(s)
        result = await svc.atomic_inc_retry_count(uuid4(), expected=0)
    assert result is None
