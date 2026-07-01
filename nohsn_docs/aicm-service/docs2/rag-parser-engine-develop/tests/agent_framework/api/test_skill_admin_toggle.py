"""Stage B-Core-5 — 스킬 토글 API 통합 테스트.

핵심 흐름:
- GET /list (phone 없음): legacy shape 유지 (enabled/can_enable 없음).
- GET /list?phone=...: account resolve + tenant_skills 조회 → per-skill 토글 메타 부착.
- POST /{id}/enable: business_only 거절, personal/all 만 허용, idempotent.
- POST /{id}/disable: 존재하는 스킬에 한해 registry 호출. 미존재 스킬 404.

외부 의존 mock:
- get_agent_engine: 3 개 stub skill 을 가진 경량 엔진.
- get_skill_registry: AsyncMock 로 list_enabled_skill_ids_for_account/enable_skill/disable_skill 대체.
- get_or_create_account: monkeypatch 로 고정 UUID 반환 (DB 접근 없음).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from src.agent_framework.api import skill_admin as skill_admin_mod
from src.agent_framework.api.dependencies import (
    get_agent_engine,
    get_skill_registry,
)
from src.agent_framework.runtime.schema import (
    Skill,
    SkillAvailability,
    SkillMeta,
    StateDef,
    Trigger,
)
from src.api.main import app


FIXED_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
FIXED_TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


def _make_skill(
    sid: str,
    scope: str,
    visibility: str,
    description: str = "",
) -> Skill:
    """테스트용 최소 Skill 인스턴스."""
    return Skill(
        meta=SkillMeta(
            id=sid,
            version="1",
            domain="test",
            description=description or sid,
        ),
        triggers=[Trigger(intent=f"{sid}_intent")],
        trigger_type="intent",
        initial_state="start",
        states=[StateDef(id="start")],
        availability=SkillAvailability(scope=scope, visibility=visibility),
    )


PERSONAL_AUTO_ID = "personal_auto_skill"
PERSONAL_OPTIN_ID = "personal_optin_skill"
BUSINESS_ID = "business_skill"


def _stub_skills() -> dict[str, Skill]:
    return {
        PERSONAL_AUTO_ID: _make_skill(PERSONAL_AUTO_ID, "personal", "auto"),
        PERSONAL_OPTIN_ID: _make_skill(PERSONAL_OPTIN_ID, "personal", "opt-in"),
        BUSINESS_ID: _make_skill(BUSINESS_ID, "business_only", "opt-in"),
    }


class _StubEngine:
    """skill_admin 엔드포인트가 엑세스하는 필드만 채운 엔진 stub."""

    def __init__(self, skills: dict[str, Skill], registry):
        self.skills = skills
        self.skill_registry = registry


@pytest.fixture
def stub_registry():
    reg = SimpleNamespace(
        list_enabled_skill_ids_for_account=AsyncMock(return_value=[]),
        enable_skill=AsyncMock(return_value=None),
        disable_skill=AsyncMock(return_value=None),
    )
    return reg


@pytest.fixture
def stub_engine(stub_registry):
    return _StubEngine(_stub_skills(), stub_registry)


@pytest.fixture(autouse=True)
def _override_deps(stub_engine, stub_registry, monkeypatch):
    app.dependency_overrides[get_agent_engine] = lambda: stub_engine
    app.dependency_overrides[get_skill_registry] = lambda: stub_registry

    async def _fake_get_or_create_account(phone: str, name: str | None = None):
        # AccountContext 와 동등한 attribute (account_id, personal_tenant_id, phone, name)
        return SimpleNamespace(
            account_id=FIXED_ACCOUNT_ID,
            personal_tenant_id=FIXED_TENANT_ID,
            phone=phone,
            name=name,
        )

    monkeypatch.setattr(
        skill_admin_mod, "get_or_create_account", _fake_get_or_create_account
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)
        app.dependency_overrides.pop(get_skill_registry, None)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_list_skills_without_phone_is_backward_compatible():
    async with await _client() as c:
        resp = await c.get("/agent/skills/list")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 3
        for item in items:
            # legacy shape: enabled / can_enable / visibility 키가 없어야 함
            assert "enabled" not in item
            assert "can_enable" not in item
            assert "visibility" not in item
            # 기본 필드는 그대로
            assert "id" in item and "triggers" in item


@pytest.mark.asyncio
async def test_list_skills_with_phone_returns_enabled_flags(stub_registry):
    stub_registry.list_enabled_skill_ids_for_account.return_value = [
        PERSONAL_AUTO_ID,
    ]
    async with await _client() as c:
        resp = await c.get("/agent/skills/list?phone=01012345678")
        assert resp.status_code == 200
        items = {it["id"]: it for it in resp.json()}

    auto_item = items[PERSONAL_AUTO_ID]
    assert auto_item["enabled"] is True
    assert auto_item["can_enable"] is True
    assert auto_item["visibility"] == "auto"

    optin_item = items[PERSONAL_OPTIN_ID]
    assert optin_item["enabled"] is False
    assert optin_item["can_enable"] is True
    assert optin_item["visibility"] == "opt-in"

    business_item = items[BUSINESS_ID]
    assert business_item["enabled"] is False
    assert business_item["can_enable"] is False  # business_only 은 personal 에서 불가
    assert business_item["visibility"] == "opt-in"

    stub_registry.list_enabled_skill_ids_for_account.assert_awaited_once_with(
        FIXED_ACCOUNT_ID
    )


@pytest.mark.asyncio
async def test_enable_opt_in_personal_skill_succeeds(stub_registry):
    async with await _client() as c:
        resp = await c.post(
            f"/agent/skills/{PERSONAL_OPTIN_ID}/enable",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["skill_id"] == PERSONAL_OPTIN_ID
    assert body["tenant_id"] == str(FIXED_TENANT_ID)

    stub_registry.enable_skill.assert_awaited_once()
    kwargs = stub_registry.enable_skill.await_args.kwargs
    assert kwargs["tenant_id"] == FIXED_TENANT_ID
    assert kwargs["skill_id"] == PERSONAL_OPTIN_ID
    assert kwargs["by_account_id"] == FIXED_ACCOUNT_ID


@pytest.mark.asyncio
async def test_enable_business_only_skill_returns_400(stub_registry):
    async with await _client() as c:
        resp = await c.post(
            f"/agent/skills/{BUSINESS_ID}/enable",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "business_only skill cannot be enabled on personal tenant"
    assert detail["skill_id"] == BUSINESS_ID
    assert "hint" in detail
    stub_registry.enable_skill.assert_not_called()


@pytest.mark.asyncio
async def test_enable_unknown_skill_returns_404(stub_registry):
    async with await _client() as c:
        resp = await c.post(
            "/agent/skills/does_not_exist/enable",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 404
    stub_registry.enable_skill.assert_not_called()


@pytest.mark.asyncio
async def test_disable_skill_calls_registry(stub_registry):
    async with await _client() as c:
        resp = await c.post(
            f"/agent/skills/{PERSONAL_OPTIN_ID}/disable",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["skill_id"] == PERSONAL_OPTIN_ID

    stub_registry.disable_skill.assert_awaited_once()
    kwargs = stub_registry.disable_skill.await_args.kwargs
    assert kwargs["tenant_id"] == FIXED_TENANT_ID
    assert kwargs["skill_id"] == PERSONAL_OPTIN_ID


@pytest.mark.asyncio
async def test_disable_unknown_skill_returns_404(stub_registry):
    async with await _client() as c:
        resp = await c.post(
            "/agent/skills/does_not_exist/disable",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 404
    stub_registry.disable_skill.assert_not_called()
