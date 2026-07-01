"""diary_store dual-backend tests.

- Redis (기본): 기존 diary_mock 스펙 보존 — save/search + phone 격리 + emotion 필터.
- KMS: ``AGENT_DATA_STORE=kms`` 에서 ``agent_document_store`` 로 위임하는지
  monkeypatch 로 호출 계약만 확인 (실 DB 는 별도 integration test 에서 검증).
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.diary_store import (
    _reset,
    delete,
    save,
    search,
)


# ── Redis path (기존 동작) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_search():
    _reset()
    r = await save({
        "phone": "010-1",
        "entry_text": "오늘 기분이 좋았다",
        "emotion": "기쁨",
        "date": "2026-04-22",
    })
    assert r["id"]
    assert r["success"] is True
    hits = await search({"phone": "010-1", "query": "기분", "top_k": 5})
    assert len(hits["hits"]) == 1
    assert hits["hits"][0]["text"] == "오늘 기분이 좋았다"


@pytest.mark.asyncio
async def test_search_scoped_by_phone():
    _reset()
    await save({"phone": "010-1", "entry_text": "A 의 일기", "emotion": "평온", "date": "2026-04-22"})
    await save({"phone": "010-2", "entry_text": "B 의 일기", "emotion": "불안", "date": "2026-04-22"})
    a = await search({"phone": "010-1", "query": "", "top_k": 10})
    b = await search({"phone": "010-2", "query": "", "top_k": 10})
    assert len(a["hits"]) == 1
    assert a["hits"][0]["text"] == "A 의 일기"
    assert len(b["hits"]) == 1


@pytest.mark.asyncio
async def test_search_filter_by_emotion():
    _reset()
    await save({"phone": "010-3", "entry_text": "좋은 날", "emotion": "기쁨", "date": "2026-04-22"})
    await save({"phone": "010-3", "entry_text": "우울한 날", "emotion": "슬픔", "date": "2026-04-23"})
    r = await search({"phone": "010-3", "query": "", "emotion": "슬픔", "top_k": 10})
    assert len(r["hits"]) == 1
    assert r["hits"][0]["emotion"] == "슬픔"


@pytest.mark.asyncio
async def test_search_empty_no_matches():
    _reset()
    r = await search({"phone": "010-no-entries", "query": "anything", "top_k": 5})
    assert r["hits"] == []


# ── KMS path (monkeypatch delegation) ─────────────────────────────────


@pytest.mark.asyncio
async def test_kms_save_calls_agent_document_store(monkeypatch):
    """KMS 모드: tenant_id 가 있으면 agent_document_store.create_item 위임."""
    tenant = uuid4()
    fake_doc_id = uuid4()
    mock_create = AsyncMock(return_value=fake_doc_id)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store._get_shared_engine",
        lambda: "fake-engine",
    )

    result = await save(
        {
            "phone": "010-KMS",  # redis 용 — ignored in kms mode
            "tenant_id": str(tenant),
            "entry_text": "오늘은 뿌듯했다",
            "emotion": "기쁨",
            "date": "2026-05-01",
        }
    )

    # T4: scope_group default='personal' 자동 부여 + 응답에 노출.
    assert result == {
        "id": str(fake_doc_id),
        "success": True,
        "scope_group": "personal",
    }
    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[0] == "fake-engine"
    assert call_args[1] == tenant
    assert call_args[2] == "agent_diary"
    # title 은 날짜 기반 "2026-05-01 일기"
    assert call_kwargs["title"] == "2026-05-01 일기"
    assert call_kwargs["body"] == {
        "text": "오늘은 뿌듯했다",
        "emotion": "기쁨",
        "date": "2026-05-01",
    }
    assert call_kwargs["scope_group"] == "personal"


@pytest.mark.asyncio
async def test_kms_save_without_tenant_returns_error(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await save({"phone": "010-X", "entry_text": "x"})
    assert r["success"] is False
    assert "tenant_id" in (r.get("error") or "")


@pytest.mark.asyncio
async def test_kms_search_delegates_with_filters(monkeypatch):
    """KMS search: query → body_text_contains, emotion → body_equals, 최신순."""
    tenant = uuid4()
    mock_list = AsyncMock(
        return_value=[
            {"id": "d1", "title": "2026-05-02 일기", "text": "힘들었다", "emotion": "슬픔", "date": "2026-05-02"}
        ]
    )
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store.agent_document_store.list_items_filtered",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await search(
        {
            "phone": "010-X",
            "tenant_id": str(tenant),
            "query": "힘들",
            "emotion": "슬픔",
            "top_k": 7,
        }
    )

    assert r["hits"] == [
        {
            "id": "d1",
            "title": "2026-05-02 일기",
            "text": "힘들었다",
            "emotion": "슬픔",
            "date": "2026-05-02",
        }
    ]
    mock_list.assert_awaited_once()
    call_args = mock_list.await_args.args
    call_kwargs = mock_list.await_args.kwargs
    assert call_args[0] == "fake-engine"
    assert call_args[1] == tenant
    assert call_args[2] == "agent_diary"
    assert call_kwargs["body_equals"] == {"emotion": "슬픔"}
    assert call_kwargs["body_text_contains"] == ("text", "힘들")
    assert call_kwargs["order_desc"] is True
    assert call_kwargs["limit"] == 7


@pytest.mark.asyncio
async def test_kms_search_without_filters_passes_none(monkeypatch):
    """query/emotion 없이 호출하면 body_equals/body_text_contains 는 None."""
    tenant = uuid4()
    mock_list = AsyncMock(return_value=[])
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store.agent_document_store.list_items_filtered",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store._get_shared_engine",
        lambda: "fake-engine",
    )

    await search({"tenant_id": str(tenant), "phone": "x"})

    call_kwargs = mock_list.await_args.kwargs
    assert call_kwargs["body_equals"] is None
    assert call_kwargs["body_text_contains"] is None
    assert call_kwargs["order_desc"] is True
    assert call_kwargs["limit"] == 10  # default top_k


@pytest.mark.asyncio
async def test_kms_delete_calls_agent_document_store(monkeypatch):
    tenant = uuid4()
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store.agent_document_store.delete_item",
        mock_delete,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.diary_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await delete({"phone": "x", "tenant_id": str(tenant), "id": "doc-42"})

    assert r == {"success": True}
    mock_delete.assert_awaited_once_with(
        "fake-engine", tenant, "agent_diary", "doc-42"
    )
