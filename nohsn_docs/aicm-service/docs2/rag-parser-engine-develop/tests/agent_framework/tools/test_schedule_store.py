"""schedule_store dual-backend tests.

- Redis (기본): 기존 schedule_mock 스펙 보존 — create/list/delete + phone 격리
  + recurrence 필드 보존.
- KMS: ``AGENT_DATA_STORE=kms`` 에서 ``agent_document_store`` 로 위임하는지
  monkeypatch 로 호출 계약만 확인 (실 DB 는 별도 integration test 에서 검증).
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.schedule_store import (
    _reset,
    create,
    delete,
    list_all,
)


# ── Redis path (기존 동작) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crud_redis():
    _reset()
    r = await create(
        {
            "phone": "010-1",
            "title": "회의",
            "when": "2026-04-25T15:00",
            "recurrence": None,
        }
    )
    assert r["id"]
    items = (await list_all({"phone": "010-1"}))["items"]
    assert len(items) == 1
    assert items[0]["title"] == "회의"
    await delete({"phone": "010-1", "id": r["id"]})
    items2 = (await list_all({"phone": "010-1"}))["items"]
    assert len(items2) == 0


@pytest.mark.asyncio
async def test_scoped_by_phone_redis():
    _reset()
    await create(
        {
            "phone": "010-1",
            "title": "회의A",
            "when": "2026-04-25T15:00",
            "recurrence": None,
        }
    )
    await create(
        {
            "phone": "010-2",
            "title": "회의B",
            "when": "2026-04-25T16:00",
            "recurrence": None,
        }
    )
    a = (await list_all({"phone": "010-1"}))["items"]
    b = (await list_all({"phone": "010-2"}))["items"]
    assert len(a) == 1
    assert len(b) == 1
    assert a[0]["title"] == "회의A"


@pytest.mark.asyncio
async def test_recurrence_preserved_redis():
    _reset()
    await create(
        {
            "phone": "010-3",
            "title": "운동",
            "when": "2026-04-28T10:00",
            "recurrence": "FREQ=WEEKLY;BYDAY=MO",
        }
    )
    items = (await list_all({"phone": "010-3"}))["items"]
    assert items[0]["recurrence"] == "FREQ=WEEKLY;BYDAY=MO"


# ── KMS path (monkeypatch delegation) ─────────────────────────────────


@pytest.mark.asyncio
async def test_kms_create_calls_agent_document_store(monkeypatch):
    """KMS 모드: tenant_id 를 받으면 agent_document_store.create_item 에 위임."""
    tenant = uuid4()
    fake_doc_id = uuid4()
    mock_create = AsyncMock(return_value=fake_doc_id)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.schedule_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.schedule_store._get_shared_engine",
        lambda: "fake-engine",
    )

    result = await create(
        {
            "phone": "010-KMS",  # redis 용 — ignored in kms mode
            "tenant_id": str(tenant),
            "title": "KMS 일정",
            "when": "2026-05-01T09:00",
            "recurrence": "FREQ=DAILY",
        }
    )

    # T4: scope_group default='personal' 자동 부여 + 응답에 노출.
    # Phase 1 (알렘빅 072) — owner_agent_id 응답 필드 추가. agent_id 미주입
    # 케이스라 None 으로 노출.
    assert result == {
        "id": str(fake_doc_id),
        "success": True,
        "scope_group": "personal",
        "owner_agent_id": None,
    }
    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[0] == "fake-engine"
    assert call_args[1] == tenant
    assert call_args[2] == "agent_schedule"
    assert call_kwargs["title"] == "KMS 일정"
    # body 에는 who/where/recurrence/when 모두 들어감 (None 포함).
    assert call_kwargs["body"]["when"] == "2026-05-01T09:00"
    assert call_kwargs["body"]["recurrence"] == "FREQ=DAILY"
    assert call_kwargs["scope_group"] == "personal"


@pytest.mark.asyncio
async def test_kms_create_without_tenant_returns_error(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await create({"phone": "010-X", "title": "x", "when": "2026-05-01"})
    assert r["success"] is False
    assert "tenant_id" in (r.get("error") or "")


@pytest.mark.asyncio
async def test_kms_list_calls_agent_document_store(monkeypatch):
    tenant = uuid4()
    mock_list = AsyncMock(
        return_value=[{"id": "d1", "title": "일정1", "when": "2026-05-01"}]
    )
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.schedule_store.agent_document_store.list_items",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.schedule_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await list_all({"phone": "010-X", "tenant_id": str(tenant)})

    assert r["items"] == [{"id": "d1", "title": "일정1", "when": "2026-05-01"}]
    # scope_group 미지정 시 None 으로 전달 (모든 scope) — 기존 동작 유지.
    # Phase 1 (알렘빅 072) — owner_agent_id / include_null_owner 추가 (default
    # None / False — agent 격리 옵트인). agent_id 미주입 케이스라 owner None.
    mock_list.assert_awaited_once_with(
        "fake-engine",
        tenant,
        "agent_schedule",
        scope_group=None,
        owner_agent_id=None,
        include_null_owner=False,
    )


@pytest.mark.asyncio
async def test_kms_delete_calls_agent_document_store(monkeypatch):
    tenant = uuid4()
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.schedule_store.agent_document_store.delete_item",
        mock_delete,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.schedule_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await delete({"phone": "x", "tenant_id": str(tenant), "id": "doc-42"})

    assert r == {"success": True}
    # Phase 1 (알렘빅 072) — owner_agent_id 옵션 추가. agent_id 미주입 케이스라
    # None 으로 전달 — KMS update path 가 owner 필터 없이 tenant 매칭 (legacy 호환).
    mock_delete.assert_awaited_once_with(
        "fake-engine", tenant, "agent_schedule", "doc-42", owner_agent_id=None
    )
