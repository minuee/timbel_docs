"""SkillRegistry 가 tenant_skills 기반으로 account 별 스킬 필터링.

Stage B-Core-1.

테스트 DB 분리:
- phone prefix ``010-REG-`` 사용, teardown 에서 해당 row + personal tenant 삭제.
- ``tenant_skills`` 는 tenant_id CASCADE 이므로 tenant 삭제 시 동반 정리.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.agent_framework.core import accounts as accounts_mod
from src.agent_framework.core.accounts import (
    _get_engine,
    _reset_engine_for_tests,
    get_or_create_account,
)
from src.agent_framework.core.skill_registry import SkillRegistry
from src.agent_framework.runtime.engine import SKILLS_DIR
from src.agent_framework.runtime.loader import load_all_skills
from src.common.config import settings


TEST_PHONE_PREFIX = "010-REG-"


async def _cleanup() -> None:
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts WHERE phone LIKE :p"
            ),
            {"p": f"{TEST_PHONE_PREFIX}%"},
        )
        to_wipe = list(rows)
        for account_id, tenant_id in to_wipe:
            # tenant_skills 는 tenant CASCADE 로 같이 지워지지만 명시적으로 정리
            await conn.execute(
                text("DELETE FROM tenant_skills WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await conn.execute(
                text("DELETE FROM tenant_memberships WHERE account_id = :aid"),
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
    await _reset_engine_for_tests()
    await _cleanup()
    yield
    await _cleanup()
    await _reset_engine_for_tests()


@pytest_asyncio.fixture
async def registry():
    """SkillRegistry 는 자체 engine 을 들고 있음 — 테스트마다 dispose."""
    eng = create_async_engine(settings.DATABASE_URL)
    skills = load_all_skills(SKILLS_DIR)
    try:
        yield SkillRegistry(eng, skills)
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_new_account_gets_personal_auto_skills(registry, clean_db):
    """personal/all + auto 스킬은 account 생성 시 자동 enable."""
    ctx = await get_or_create_account(
        phone=f"{TEST_PHONE_PREFIX}T01", name="Reg Test"
    )
    labels = await registry.list_available_labels_for_account(ctx.account_id)
    # diary_personal(log_diary, recall_diary), schedule_personal(create_schedule),
    # news_daily_report(configure_news)
    assert "log_diary" in labels
    assert "recall_diary" in labels
    assert "create_schedule" in labels
    assert "configure_news" in labels


@pytest.mark.asyncio
async def test_new_account_does_not_see_business_opt_in_skills(
    registry, clean_db
):
    """appointment_derm 은 business_only + opt-in → personal tenant 기본 포함 X."""
    ctx = await get_or_create_account(
        phone=f"{TEST_PHONE_PREFIX}T02", name="Reg Test B"
    )
    labels = await registry.list_available_labels_for_account(ctx.account_id)
    assert "book_appointment" not in labels
    assert "ask_treatment" not in labels
    assert "ask_doctors" not in labels
    assert "ask_hours" not in labels


@pytest.mark.asyncio
async def test_explicit_enable_adds_skill(registry, clean_db):
    """business_only + opt-in 스킬을 수동 enable 하면 라벨에 등장."""
    ctx = await get_or_create_account(
        phone=f"{TEST_PHONE_PREFIX}T03", name="Reg Test C"
    )
    await registry.enable_skill(
        tenant_id=ctx.personal_tenant_id,
        skill_id="appointment_derm",
        by_account_id=ctx.account_id,
    )
    labels = await registry.list_available_labels_for_account(ctx.account_id)
    assert "book_appointment" in labels


@pytest.mark.asyncio
async def test_disable_removes_skill(registry, clean_db):
    """disable 시 해당 skill 의 라벨 제거."""
    ctx = await get_or_create_account(
        phone=f"{TEST_PHONE_PREFIX}T04", name="Reg Test D"
    )
    await registry.disable_skill(
        tenant_id=ctx.personal_tenant_id,
        skill_id="diary_personal",
    )
    labels = await registry.list_available_labels_for_account(ctx.account_id)
    assert "log_diary" not in labels
    assert "recall_diary" not in labels
    # 다른 personal skill 은 그대로
    assert "create_schedule" in labels
