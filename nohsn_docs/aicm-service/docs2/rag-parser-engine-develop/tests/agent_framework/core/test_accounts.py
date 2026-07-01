"""account / personal_tenant 자동 생성 회귀 (Stage B-1).

테스트 DB 분리 방식:
- kms-api 컨테이너에서 kms_pipeline DB 를 공유하므로, 테스트 phone 에
  ``TEST-`` prefix 를 넣어 충돌/오염 방지.
- 테스트 suite 시작/끝에서 해당 prefix row 를 DELETE 하는 autouse fixture 로 청소.
"""
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text

from src.agent_framework.core import accounts as accounts_mod
from src.agent_framework.core.accounts import (
    DEFAULT_PERSONAL_REPOS,
    _get_engine,
    _reset_engine_for_tests,
    get_account_by_phone,
    get_or_create_account,
    list_tenant_memberships,
)

TEST_PHONE_PREFIX = "010-TEST-"


async def _cleanup() -> None:
    eng = _get_engine()
    async with eng.begin() as conn:
        # 1. account 소속 personal_tenant id 수집 후
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts "
                "WHERE phone LIKE :p"
            ),
            {"p": f"{TEST_PHONE_PREFIX}%"},
        )
        to_wipe = list(rows)

        # 2. memberships → accounts → repositories → tenants 순 삭제 (FK 경로)
        for account_id, tenant_id in to_wipe:
            await conn.execute(
                text(
                    "DELETE FROM tenant_memberships WHERE account_id = :aid"
                ),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM repositories WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await conn.execute(
                text("DELETE FROM tenants WHERE id = :tid"),
                {"tid": tenant_id},
            )


@pytest_asyncio.fixture
async def clean_db():
    """테스트 시작/끝 모두 TEST- prefix row cleanup.

    각 테스트가 자기 event loop 를 갖기 때문에 module-level singleton
    engine 이 이전 loop 에 묶여 있으면 "attached to a different loop"
    RuntimeError 가 난다. 각 테스트 진입/종료 시 engine dispose.
    """
    await _reset_engine_for_tests()
    await _cleanup()
    yield
    await _cleanup()
    await _reset_engine_for_tests()


@pytest.mark.asyncio
async def test_first_visit_creates_account_and_tenant(clean_db):
    phone = f"{TEST_PHONE_PREFIX}0001"
    ctx = await get_or_create_account(phone=phone, name="테스트유저")

    assert isinstance(ctx.account_id, UUID)
    assert isinstance(ctx.personal_tenant_id, UUID)
    assert ctx.phone == phone
    assert ctx.name == "테스트유저"

    # default repositories 6개 생성 확인
    eng = _get_engine()
    async with eng.begin() as conn:
        r = await conn.execute(
            text(
                "SELECT name FROM repositories WHERE tenant_id = :tid "
                "ORDER BY name"
            ),
            {"tid": ctx.personal_tenant_id},
        )
        names = sorted([row[0] for row in r])
    assert names == sorted(DEFAULT_PERSONAL_REPOS)

    # tenant_memberships 에 owner role 확인
    members = await list_tenant_memberships(ctx.account_id)
    assert len(members) == 1
    assert members[0]["role"] == "owner"
    assert members[0]["type"] == "personal"


@pytest.mark.asyncio
async def test_second_visit_same_phone_returns_existing(clean_db):
    phone = f"{TEST_PHONE_PREFIX}0002"
    a1 = await get_or_create_account(phone=phone, name="유저A")
    a2 = await get_or_create_account(phone=phone, name="유저A_갱신시도")

    # 같은 account_id / personal_tenant_id
    assert a1.account_id == a2.account_id
    assert a1.personal_tenant_id == a2.personal_tenant_id
    # 기존 name 유지 (갱신 안 함)
    assert a2.name == "유저A"


@pytest.mark.asyncio
async def test_get_by_phone_missing_returns_none(clean_db):
    r = await get_account_by_phone(f"{TEST_PHONE_PREFIX}DOES-NOT-EXIST")
    assert r is None


@pytest.mark.asyncio
async def test_get_by_phone_returns_after_create(clean_db):
    phone = f"{TEST_PHONE_PREFIX}0003"
    created = await get_or_create_account(phone=phone, name="조회유저")
    fetched = await get_account_by_phone(phone)

    assert fetched is not None
    assert fetched.account_id == created.account_id
    assert fetched.personal_tenant_id == created.personal_tenant_id
    assert fetched.name == "조회유저"
