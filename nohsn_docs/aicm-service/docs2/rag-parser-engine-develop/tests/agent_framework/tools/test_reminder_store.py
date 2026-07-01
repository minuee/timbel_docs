"""reminder_store dual-backend tests.

- Redis (기본): 기존 reminder_mock 동작 보존.
- KMS: ``AGENT_DATA_STORE=kms`` 에서 agent_document_store 로 위임하는지
  monkeypatch 로 호출 계약만 확인.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.reminder_store import list_recent, schedule


# ── Redis path (기존 동작) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reminder_schedule_records_entry_redis():
    r = await schedule(
        {
            "at": "2026-04-25T09:00",
            "channel": "sms",
            "phone": "010-1234",
            "template": "reminder_derm",
        }
    )
    assert r["success"] is True
    assert r["at"] == "2026-04-25T09:00"
    recent = await list_recent()
    assert len(recent) >= 1
    match = [e for e in recent if e.get("at") == "2026-04-25T09:00"]
    assert match and match[0]["channel"] == "sms"


# ── KMS path (monkeypatch delegation) ─────────────────────────────────


@pytest.mark.asyncio
async def test_kms_schedule_creates_reminder_doc(monkeypatch):
    tenant = uuid4()
    mock_create = AsyncMock(return_value=uuid4())
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reminder_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reminder_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await schedule(
        {
            "at": "2026-05-01T09:00",
            "channel": "sms",
            "phone": "010-9999",
            "template": "reminder_derm",
            "tenant_id": str(tenant),
        }
    )

    assert r == {"success": True, "at": "2026-05-01T09:00"}
    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[0] == "fake-engine"
    assert call_args[1] == tenant
    assert call_args[2] == "agent_reminder"
    assert call_kwargs["title"] == "2026-05-01T09:00 리마인더"
    assert call_kwargs["body"] == {
        "at": "2026-05-01T09:00",
        "channel": "sms",
        "phone": "010-9999",
        "template": "reminder_derm",
    }


@pytest.mark.asyncio
async def test_kms_schedule_without_tenant_errors(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await schedule({"at": "2026-05-01", "channel": "sms", "phone": "010"})
    assert r["success"] is False
    assert "tenant_id" in (r.get("error") or "")


@pytest.mark.asyncio
async def test_kms_list_recent_uses_global_doctype(monkeypatch):
    sample = [
        {"id": "r1", "title": "2026-05-01 리마인더", "at": "2026-05-01", "tenant_id": str(uuid4())}
    ]
    mock_list = AsyncMock(return_value=sample)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reminder_store.agent_document_store.list_items_global_doctype",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reminder_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await list_recent()

    assert r == sample
    mock_list.assert_awaited_once()
    call_args = mock_list.await_args.args
    assert call_args[0] == "fake-engine"
    assert call_args[1] == "agent_reminder"
