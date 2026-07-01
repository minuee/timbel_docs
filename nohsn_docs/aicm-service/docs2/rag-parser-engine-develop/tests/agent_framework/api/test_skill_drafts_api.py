"""/agent/skill_drafts — Task 36 Phase A integration tests.

agent_document_store / skill_draft_store / get_or_create_account 를 monkeypatch
로 교체해 DB 접근 없이 라우터 동작 검증.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.agent_framework.api import skill_drafts as skill_drafts_mod
from src.agent_framework.api.dependencies import (
    get_agent_engine,
    get_skill_registry,
)
from src.api.main import app


FIXED_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
FIXED_TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")
VALID_YAML = (
    "skill:\n"
    "  id: user_defined_check\n"
    '  version: "1.1"\n'
    "  domain: personal\n"
    '  description: "x"\n'
    "triggers:\n  - intent: do_check\n"
    "slots: []\n"
    "initial_state: s0\n"
    "states:\n  - id: s0\n"
)


@pytest.fixture
def stub_registry():
    return SimpleNamespace(enable_skill=AsyncMock(return_value=None))


@pytest.fixture
def stub_engine(stub_registry):
    return SimpleNamespace(skill_registry=stub_registry, skills={})


@pytest.fixture(autouse=True)
def _override_deps(stub_engine, stub_registry, monkeypatch):
    app.dependency_overrides[get_agent_engine] = lambda: stub_engine
    app.dependency_overrides[get_skill_registry] = lambda: stub_registry

    async def _fake_get_or_create_account(phone, name=None):
        return SimpleNamespace(
            account_id=FIXED_ACCOUNT_ID,
            personal_tenant_id=FIXED_TENANT_ID,
            phone=phone,
            name=name,
        )

    monkeypatch.setattr(
        skill_drafts_mod,
        "get_or_create_account",
        _fake_get_or_create_account,
    )
    # db engine dependency — don't actually touch DB
    monkeypatch.setattr(
        skill_drafts_mod,
        "_get_or_create_db_engine",
        lambda: object(),
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)
        app.dependency_overrides.pop(get_skill_registry, None)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_list_drafts_filters_by_status(monkeypatch):
    """GET /agent/skill_drafts?phone=...&status=pending — store.list_by_account 호출."""
    called_with = {}

    async def fake_list(engine, account_id, *, status=None):
        called_with["account_id"] = account_id
        called_with["status"] = status
        return [{"id": "abc", "status": status or "pending"}]

    monkeypatch.setattr(
        skill_drafts_mod.skill_draft_store, "list_by_account", fake_list
    )

    async with await _client() as c:
        resp = await c.get(
            "/agent/skill_drafts?phone=01012345678&status=pending"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"id": "abc", "status": "pending"}]
    assert called_with["account_id"] == FIXED_ACCOUNT_ID
    assert called_with["status"] == "pending"


@pytest.mark.asyncio
async def test_get_draft_returns_404_when_missing(monkeypatch):
    async def fake_get(engine, draft_id):
        return None

    monkeypatch.setattr(skill_drafts_mod.skill_draft_store, "get", fake_get)
    async with await _client() as c:
        resp = await c.get(f"/agent/skill_drafts/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_promotes_draft_and_enables_skill(
    monkeypatch, stub_registry
):
    draft_id = uuid4()
    created_doc_id = uuid4()

    async def fake_get(engine, did):
        assert did == draft_id
        return {
            "id": str(draft_id),
            "tenant_id": str(FIXED_TENANT_ID),
            "draft_yaml": VALID_YAML,
            "status": "pending",
        }

    create_item_called = {}

    async def fake_create_item(engine, tenant_id, dtype, title, body):
        create_item_called["title"] = title
        create_item_called["dtype"] = dtype
        create_item_called["body_yaml"] = body.get("yaml")
        create_item_called["tenant_id"] = tenant_id
        return created_doc_id

    async def fake_update(engine, did, status, *, reviewer_account_id=None):
        assert did == draft_id
        assert status == "approved"
        assert reviewer_account_id == FIXED_ACCOUNT_ID
        return True

    monkeypatch.setattr(skill_drafts_mod.skill_draft_store, "get", fake_get)
    monkeypatch.setattr(
        skill_drafts_mod.skill_draft_store,
        "update_status",
        fake_update,
    )
    monkeypatch.setattr(
        skill_drafts_mod.agent_document_store,
        "create_item",
        fake_create_item,
    )

    async with await _client() as c:
        resp = await c.post(
            f"/agent/skill_drafts/{draft_id}/approve",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"
    assert body["skill_id"] == "user_defined_check"
    assert body["document_id"] == str(created_doc_id)
    assert body["active"] is True
    assert "재시작" in body["note"]

    # skill_registry.enable_skill 호출됐는지
    stub_registry.enable_skill.assert_awaited_once()
    kwargs = stub_registry.enable_skill.await_args.kwargs
    assert kwargs["skill_id"] == "user_defined_check"
    assert kwargs["tenant_id"] == FIXED_TENANT_ID
    assert kwargs["by_account_id"] == FIXED_ACCOUNT_ID

    assert create_item_called["title"] == "user_defined_check"
    assert create_item_called["dtype"] == "agent_skill"
    assert "user_defined_check" in create_item_called["body_yaml"]


@pytest.mark.asyncio
async def test_reject_sets_status_rejected(monkeypatch):
    draft_id = uuid4()

    async def fake_get(engine, did):
        return {
            "id": str(draft_id),
            "tenant_id": str(FIXED_TENANT_ID),
            "draft_yaml": VALID_YAML,
            "status": "pending",
        }

    update_call = {}

    async def fake_update(engine, did, status, *, reviewer_account_id=None):
        update_call["did"] = did
        update_call["status"] = status
        update_call["reviewer"] = reviewer_account_id
        return True

    monkeypatch.setattr(skill_drafts_mod.skill_draft_store, "get", fake_get)
    monkeypatch.setattr(
        skill_drafts_mod.skill_draft_store,
        "update_status",
        fake_update,
    )

    async with await _client() as c:
        resp = await c.post(
            f"/agent/skill_drafts/{draft_id}/reject",
            json={"phone": "01099998888"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert update_call["did"] == draft_id
    assert update_call["status"] == "rejected"
    assert update_call["reviewer"] == FIXED_ACCOUNT_ID


@pytest.mark.asyncio
async def test_delete_returns_404_when_not_found(monkeypatch):
    draft_id = uuid4()

    async def fake_delete(engine, did):
        return False

    monkeypatch.setattr(
        skill_drafts_mod.skill_draft_store, "delete", fake_delete
    )
    async with await _client() as c:
        resp = await c.delete(f"/agent/skill_drafts/{draft_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_rejects_non_pending_draft(monkeypatch):
    draft_id = uuid4()

    async def fake_get(engine, did):
        return {
            "id": str(draft_id),
            "tenant_id": str(FIXED_TENANT_ID),
            "draft_yaml": VALID_YAML,
            "status": "approved",  # already approved
        }

    monkeypatch.setattr(skill_drafts_mod.skill_draft_store, "get", fake_get)
    async with await _client() as c:
        resp = await c.post(
            f"/agent/skill_drafts/{draft_id}/approve",
            json={"phone": "01012345678"},
        )
    assert resp.status_code == 409
