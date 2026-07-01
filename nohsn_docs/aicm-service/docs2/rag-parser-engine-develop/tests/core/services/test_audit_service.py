"""Phase 1.5A Task 8d — audit_service hash chain test.

검증 항목:
1. test_record_event_insert_ok — 단일 INSERT 후 row_hash 가 valid sha256.
2. test_chain_consistency — 3 연속 INSERT — row[i].prev_row_hash == row[i-1].row_hash.
3. test_concurrent_inserts_serialized — asyncio.gather 두 INSERT 가 chain 깨지지 않음.
4. test_tampering_breaks_chain — row 변조 시 verify_chain 이 broken_index 반환.

DB: 컨테이너의 실 Postgres (DATABASE_URL). 테스트는 자체 transaction 으로
INSERT 후 cleanup 하여 다른 테스트 영향 없게 함 (tenant_id 를 매번 새로 생성).

NOTE: pytest-asyncio 가 테스트마다 새 event loop 를 만들기 때문에 글로벌
async_session_factory 를 직접 쓰면 "Future attached to different loop" 가
발생한다. 테스트에서는 record_event 에 db= 인자로 per-test session 을
넘겨줘서 자체 loop 안에서 모든 IO 가 일어나게 한다.
"""
from __future__ import annotations

import asyncio
import re
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.common.config import settings
from src.core.models.audit_log import AuditLog
from src.core.services.audit_service import (
    compute_row_hash,
    record_event,
    verify_chain,
)


SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@pytest_asyncio.fixture
async def session_factory():
    """테스트 함수 이벤트 루프에 바인딩된 자체 engine + sessionmaker.

    글로벌 src.core.database.async_session_factory 는 import 시점 loop 에
    묶여 있어 pytest-asyncio 의 per-test loop 와 충돌. 여기서는 매 테스트
    별로 engine 을 만들고 dispose 한다.
    """
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
async def fresh_tenant(session_factory):
    """테스트마다 새 tenant_id 사용 — chain 격리. cleanup 포함."""
    tid = uuid4()
    yield tid
    async with session_factory() as s:
        await s.execute(delete(AuditLog).where(AuditLog.tenant_id == tid))
        await s.commit()


async def _insert(session_factory, **kwargs) -> AuditLog:
    """test session 으로 record_event 호출 — own commit 으로 종료."""
    async with session_factory() as s:
        try:
            row = await record_event(db=s, **kwargs)
            await s.commit()
        except Exception:
            await s.rollback()
            raise
    return row


async def _fetch_chain(session_factory, tenant_id) -> list[AuditLog]:
    """tenant 의 audit_log row 를 created_at 오름차순으로 반환."""
    async with session_factory() as s:
        rows = (
            await s.execute(
                select(AuditLog)
                .where(AuditLog.tenant_id == tenant_id)
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            )
        ).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_record_event_insert_ok(session_factory, fresh_tenant):
    """단일 INSERT 가 성공하고 row_hash 가 sha256 형식."""
    actor = uuid4()
    row = await _insert(
        session_factory,
        tenant_id=fresh_tenant,
        actor_id=actor,
        actor_tier="verified",
        event_kind="tool_call",
        tool_name="test.echo",
        args_redacted={"q": "hello"},
        outcome="success",
    )

    assert row.id is not None
    assert row.tenant_id == fresh_tenant
    assert row.user_id == actor
    assert row.event_kind == "tool_call"
    assert row.tool_name == "test.echo"
    assert row.outcome == "success"
    assert row.prev_row_hash is None  # chain head
    assert row.row_hash is not None
    assert SHA256_HEX.match(row.row_hash), f"invalid sha256: {row.row_hash!r}"


@pytest.mark.asyncio
async def test_chain_consistency(session_factory, fresh_tenant):
    """3 연속 INSERT — chain 이 정확히 이어지는지 확인."""
    actor = uuid4()
    rows = []
    for i in range(3):
        r = await _insert(
            session_factory,
            tenant_id=fresh_tenant,
            actor_id=actor,
            actor_tier="verified",
            event_kind="tool_call",
            tool_name=f"test.step_{i}",
            args_redacted={"i": i},
            outcome="success",
        )
        rows.append(r)

    # row[0] 은 head — prev None
    assert rows[0].prev_row_hash is None
    # row[1].prev_row_hash == row[0].row_hash
    assert rows[1].prev_row_hash == rows[0].row_hash
    # row[2].prev_row_hash == row[1].row_hash
    assert rows[2].prev_row_hash == rows[1].row_hash

    # DB 에서 다시 조회해서 verify_chain 통과
    fetched = await _fetch_chain(session_factory, fresh_tenant)
    assert len(fetched) == 3
    ok, broken = verify_chain(fetched)
    assert ok, f"chain broken at index {broken}"


@pytest.mark.asyncio
async def test_concurrent_inserts_serialized(session_factory, fresh_tenant):
    """asyncio.gather 로 동시 INSERT — advisory lock 으로 chain 안전.

    같은 tenant 에 동시에 INSERT 가 들어와도 advisory lock 이 serialize 해서
    chain 이 fork 되지 않는다. 각 INSERT 는 독립 transaction (자체 session).
    """
    actor = uuid4()

    async def one(i: int):
        return await _insert(
            session_factory,
            tenant_id=fresh_tenant,
            actor_id=actor,
            actor_tier="verified",
            event_kind="tool_call",
            tool_name=f"test.parallel_{i}",
            args_redacted={"i": i},
            outcome="success",
        )

    # 3 개 동시 — gather
    results = await asyncio.gather(one(0), one(1), one(2))
    assert len(results) == 3
    assert all(r.row_hash for r in results)

    # DB 다시 조회 → verify_chain
    fetched = await _fetch_chain(session_factory, fresh_tenant)
    assert len(fetched) == 3
    ok, broken = verify_chain(fetched)
    assert ok, (
        f"concurrent chain broken at index {broken} — "
        f"fetched hashes: {[r.row_hash for r in fetched]} "
        f"prev_hashes: {[r.prev_row_hash for r in fetched]}"
    )


@pytest.mark.asyncio
async def test_tampering_breaks_chain(session_factory, fresh_tenant):
    """row 의 args_redacted 를 변조하면 verify_chain 이 mismatch 검출.

    DB row 를 직접 UPDATE — 실 운영에서는 DB role 권한으로 막아야 함이지만,
    여기서는 hash 검증 로직이 정확한지 단위테스트.
    """
    actor = uuid4()
    rows = []
    for i in range(3):
        r = await _insert(
            session_factory,
            tenant_id=fresh_tenant,
            actor_id=actor,
            actor_tier="verified",
            event_kind="tool_call",
            tool_name=f"test.step_{i}",
            args_redacted={"i": i, "secret": "keep"},
            outcome="success",
        )
        rows.append(r)

    # 정상 chain
    fetched = await _fetch_chain(session_factory, fresh_tenant)
    ok, _ = verify_chain(fetched)
    assert ok

    # 변조: row[1] 의 args_redacted 수정 (메모리에서만)
    fetched[1].args_redacted = {"i": 999, "evil": True}

    ok, broken = verify_chain(fetched)
    assert ok is False
    assert broken == 1, f"expected broken at index 1, got {broken}"


def test_compute_row_hash_pure():
    """compute_row_hash 는 deterministic — 같은 input → 같은 output."""
    h1 = compute_row_hash(None, '{"a":1}')
    h2 = compute_row_hash(None, '{"a":1}')
    assert h1 == h2
    assert SHA256_HEX.match(h1)

    # prev 가 다르면 결과가 다름
    h3 = compute_row_hash("deadbeef" * 8, '{"a":1}')
    assert h1 != h3

    # body 가 다르면 결과가 다름
    h4 = compute_row_hash(None, '{"a":2}')
    assert h1 != h4
