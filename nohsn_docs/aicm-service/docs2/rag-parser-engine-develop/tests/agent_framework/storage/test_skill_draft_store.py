"""skill_draft_store CRUD — Task 35 Phase A.

Postgres 통합 테스트. accounts + tenants 가 있어야 FK 제약을 통과하므로
각 케이스가 자체 tenant + account 를 만들고 teardown 에서 삭제.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage import skill_draft_store
from src.agent_framework.storage.skill_draft_store import SkillDraft
from src.common.config import settings


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.DATABASE_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


async def _make_tenant_and_account(
    conn,
) -> tuple[UUID, UUID]:
    """테스트용 tenant + account 한 쌍 생성. teardown 에서 둘 다 제거."""
    slug = f"sdt_test_{uuid4().hex[:8]}"
    tr = await conn.execute(
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
    tenant_id: UUID = tr.scalar_one()

    phone = f"+test-{uuid4().hex[:10]}"
    ar = await conn.execute(
        text(
            """
            INSERT INTO accounts (id, phone, name, personal_tenant_id)
            VALUES (gen_random_uuid(), :phone, :name, :tid)
            RETURNING id
            """
        ),
        {"phone": phone, "name": slug, "tid": tenant_id},
    )
    account_id: UUID = ar.scalar_one()
    return tenant_id, account_id


async def _cleanup(engine: AsyncEngine, tenant_id: UUID, account_id: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM skill_drafts WHERE account_id = :aid"),
            {"aid": account_id},
        )
        await conn.execute(
            text("DELETE FROM accounts WHERE id = :aid"), {"aid": account_id}
        )
        await conn.execute(
            text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )


@pytest_asyncio.fixture
async def account_ctx(engine: AsyncEngine):
    async with engine.begin() as conn:
        tenant_id, account_id = await _make_tenant_and_account(conn)
    yield tenant_id, account_id
    await _cleanup(engine, tenant_id, account_id)


def _mk_draft() -> SkillDraft:
    return SkillDraft(
        title="포트폴리오 점검",
        yaml_text=(
            "skill:\n"
            "  id: user_defined_foo\n"
            '  version: "1.1"\n'
            "  domain: personal\n"
            '  description: "테스트"\n'
            "triggers:\n  - intent: x\n"
            "slots: []\n"
            "initial_state: s0\n"
            "states:\n  - id: s0\n"
        ),
        rationale="사용자 요청으로 정리함",
    )


@pytest.mark.asyncio
async def test_create_and_get_roundtrip(engine, account_ctx):
    tenant_id, account_id = account_ctx
    draft = _mk_draft()
    did = await skill_draft_store.create(
        engine,
        draft,
        account_id=account_id,
        tenant_id=tenant_id,
        session_id="sess-1",
        source_user_message="이런 기능 만들어 줘",
    )
    row = await skill_draft_store.get(engine, did)
    assert row is not None
    assert row["status"] == "pending"
    assert row["draft_title"] == draft.title
    assert "user_defined_foo" in row["draft_yaml"]
    assert row["source_user_message"] == "이런 기능 만들어 줘"
    assert row["session_id"] == "sess-1"
    assert row["account_id"] == str(account_id)


@pytest.mark.asyncio
async def test_list_by_account_filters_by_status(engine, account_ctx):
    tenant_id, account_id = account_ctx
    d1 = await skill_draft_store.create(
        engine,
        _mk_draft(),
        account_id=account_id,
        tenant_id=tenant_id,
        session_id=None,
        source_user_message="m1",
    )
    d2 = await skill_draft_store.create(
        engine,
        _mk_draft(),
        account_id=account_id,
        tenant_id=tenant_id,
        session_id=None,
        source_user_message="m2",
    )
    # 하나만 rejected 로 전환
    await skill_draft_store.update_status(
        engine, d2, "rejected", reviewer_account_id=account_id
    )

    all_rows = await skill_draft_store.list_by_account(engine, account_id)
    assert {r["id"] for r in all_rows} == {str(d1), str(d2)}

    pending = await skill_draft_store.list_by_account(
        engine, account_id, status="pending"
    )
    assert [r["id"] for r in pending] == [str(d1)]

    rejected = await skill_draft_store.list_by_account(
        engine, account_id, status="rejected"
    )
    assert [r["id"] for r in rejected] == [str(d2)]


@pytest.mark.asyncio
async def test_update_status_sets_reviewed_fields(engine, account_ctx):
    tenant_id, account_id = account_ctx
    did = await skill_draft_store.create(
        engine,
        _mk_draft(),
        account_id=account_id,
        tenant_id=tenant_id,
        session_id=None,
        source_user_message="m",
    )
    ok = await skill_draft_store.update_status(
        engine, did, "approved", reviewer_account_id=account_id
    )
    assert ok is True
    row = await skill_draft_store.get(engine, did)
    assert row["status"] == "approved"
    assert row["reviewed_by_account_id"] == str(account_id)
    assert row["reviewed_at"] is not None


@pytest.mark.asyncio
async def test_update_status_rejects_invalid_value(engine, account_ctx):
    tenant_id, account_id = account_ctx
    did = await skill_draft_store.create(
        engine,
        _mk_draft(),
        account_id=account_id,
        tenant_id=tenant_id,
        session_id=None,
        source_user_message="m",
    )
    with pytest.raises(ValueError):
        await skill_draft_store.update_status(engine, did, "launched")


@pytest.mark.asyncio
async def test_delete_removes_row(engine, account_ctx):
    tenant_id, account_id = account_ctx
    did = await skill_draft_store.create(
        engine,
        _mk_draft(),
        account_id=account_id,
        tenant_id=tenant_id,
        session_id=None,
        source_user_message="m",
    )
    ok = await skill_draft_store.delete(engine, did)
    assert ok is True
    assert await skill_draft_store.get(engine, did) is None
    # idempotent 두 번째 delete 는 False
    assert await skill_draft_store.delete(engine, did) is False
