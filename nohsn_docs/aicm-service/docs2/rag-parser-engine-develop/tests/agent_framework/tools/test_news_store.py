"""news_store dual-backend tests.

- Redis (기본): 기존 news_mock 스펙 보존 — subscribe/unsubscribe/list/fetch/reports
  + phone 격리.
- KMS: ``AGENT_DATA_STORE=kms`` 에서 ``agent_document_store`` 로 위임하는지
  monkeypatch 로 호출 계약만 확인 (실 DB 는 integration test).
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.news_store import (
    _reset,
    add_subscription,
    fetch_and_summarize,
    list_recent_reports,
    list_subscribers,
    list_subscriptions,
    remove_subscription,
)


# ── Redis path (기존 동작) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_and_fetch_redis():
    _reset()
    await add_subscription({"phone": "010-1", "topic": "AI 스타트업"})
    got = await fetch_and_summarize({"phone": "010-1", "today": "2026-04-23"})
    assert "AI 스타트업" in got["topics"]
    assert "AI 스타트업" in got["summary"]


@pytest.mark.asyncio
async def test_multiple_topics_ordered_redis():
    _reset()
    await add_subscription({"phone": "010-2", "topic": "반도체"})
    await add_subscription({"phone": "010-2", "topic": "AI 스타트업"})
    got = await list_subscriptions({"phone": "010-2"})
    assert got["subscription"]["topics"] == ["반도체", "AI 스타트업"]


@pytest.mark.asyncio
async def test_remove_subscription_redis():
    _reset()
    await add_subscription({"phone": "010-3", "topic": "X"})
    await add_subscription({"phone": "010-3", "topic": "Y"})
    await remove_subscription({"phone": "010-3", "topic": "X"})
    got = await list_subscriptions({"phone": "010-3"})
    assert got["subscription"]["topics"] == ["Y"]


@pytest.mark.asyncio
async def test_recent_reports_accumulate_redis():
    _reset()
    await add_subscription({"phone": "010-4", "topic": "X"})
    await fetch_and_summarize({"phone": "010-4", "today": "2026-04-22"})
    await fetch_and_summarize({"phone": "010-4", "today": "2026-04-23"})
    reports = await list_recent_reports({"phone": "010-4"})
    assert len(reports["reports"]) == 2


@pytest.mark.asyncio
async def test_fetch_no_subscription_message_redis():
    _reset()
    got = await fetch_and_summarize({"phone": "010-none", "today": "2026-04-23"})
    assert "구독 주제가 설정되지 않았" in got["summary"]


# ── KMS path (monkeypatch delegation) ─────────────────────────────────


@pytest.mark.asyncio
async def test_kms_add_subscription_creates_doc_when_new(monkeypatch):
    """KMS 모드: 새 topic 은 create_item 호출 + 최종 topics 목록 반환."""
    tenant = uuid4()
    doc_id = uuid4()

    # existing check: 빈 결과 → 신규 생성 경로
    mock_filtered = AsyncMock(return_value=[])
    mock_create = AsyncMock(return_value=doc_id)
    mock_list = AsyncMock(
        return_value=[{"id": str(doc_id), "title": "구독: AI", "topic": "AI", "channel": "web"}]
    )
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items_filtered",
        mock_filtered,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await add_subscription({"phone": "010-x", "tenant_id": str(tenant), "topic": "AI"})

    assert r["success"] is True
    assert r["topics"] == ["AI"]
    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[0] == "fake-engine"
    assert call_args[1] == tenant
    assert call_args[2] == "agent_news_sub"
    assert call_kwargs["title"] == "구독: AI"
    assert call_kwargs["body"]["topic"] == "AI"
    assert call_kwargs["body"]["channel"] == "web"


@pytest.mark.asyncio
async def test_kms_add_subscription_skips_when_existing(monkeypatch):
    """KMS 모드: 이미 같은 topic 이 있으면 create_item 호출 안 함."""
    tenant = uuid4()
    mock_filtered = AsyncMock(
        return_value=[{"id": "d-existing", "title": "구독: AI", "topic": "AI"}]
    )
    mock_create = AsyncMock()
    mock_list = AsyncMock(
        return_value=[{"id": "d-existing", "title": "구독: AI", "topic": "AI", "channel": "web"}]
    )
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items_filtered",
        mock_filtered,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await add_subscription({"phone": "010-x", "tenant_id": str(tenant), "topic": "AI"})

    assert r["success"] is True
    assert r["topics"] == ["AI"]
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_kms_add_subscription_without_tenant_errors(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await add_subscription({"phone": "010", "topic": "AI"})
    assert r["success"] is False
    assert "tenant_id" in (r.get("error") or "")


@pytest.mark.asyncio
async def test_kms_remove_subscription_soft_deletes_match(monkeypatch):
    tenant = uuid4()
    mock_filtered = AsyncMock(
        return_value=[{"id": "doc-1", "title": "구독: AI", "topic": "AI"}]
    )
    mock_delete = AsyncMock(return_value=True)
    mock_list = AsyncMock(return_value=[])
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items_filtered",
        mock_filtered,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.delete_item",
        mock_delete,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await remove_subscription({"phone": "x", "tenant_id": str(tenant), "topic": "AI"})

    assert r == {"success": True, "topics": []}
    mock_delete.assert_awaited_once_with("fake-engine", tenant, "agent_news_sub", "doc-1")


@pytest.mark.asyncio
async def test_kms_list_subscriptions_returns_shape(monkeypatch):
    tenant = uuid4()
    mock_list = AsyncMock(
        return_value=[
            {"id": "d1", "title": "구독: AI", "topic": "AI", "channel": "web"},
            {"id": "d2", "title": "구독: 반도체", "topic": "반도체", "channel": "web"},
        ]
    )
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await list_subscriptions({"phone": "x", "tenant_id": str(tenant)})

    assert r["subscription"]["topics"] == ["AI", "반도체"]
    assert r["subscription"]["channel"] == "web"


@pytest.mark.asyncio
async def test_kms_fetch_and_summarize_writes_report_doc(monkeypatch):
    tenant = uuid4()
    mock_list = AsyncMock(
        return_value=[{"id": "d1", "title": "구독: AI", "topic": "AI", "channel": "web"}]
    )
    mock_create = AsyncMock(return_value=uuid4())
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items",
        mock_list,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await fetch_and_summarize(
        {"phone": "x", "tenant_id": str(tenant), "today": "2026-05-01"}
    )

    assert "AI" in r["summary"]
    assert r["topics"] == ["AI"]
    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[2] == "agent_news_report"
    assert "2026-05-01" in call_kwargs["title"]
    assert call_kwargs["body"]["date"] == "2026-05-01"
    assert call_kwargs["body"]["topics"] == ["AI"]


@pytest.mark.asyncio
async def test_kms_list_recent_reports_uses_filtered_desc(monkeypatch):
    tenant = uuid4()
    sample = [
        {"id": "r2", "title": "2026-05-02 AI 요약", "date": "2026-05-02"},
        {"id": "r1", "title": "2026-05-01 AI 요약", "date": "2026-05-01"},
    ]
    mock_filtered = AsyncMock(return_value=sample)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_items_filtered",
        mock_filtered,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await list_recent_reports({"phone": "x", "tenant_id": str(tenant)})

    assert r["reports"] == sample
    call_kwargs = mock_filtered.await_args.kwargs
    assert call_kwargs["order_desc"] is True
    assert call_kwargs["limit"] == 10


@pytest.mark.asyncio
async def test_kms_list_subscribers_returns_tenant_ids(monkeypatch):
    """KMS 모드의 list_subscribers 는 list_tenants_with_doctype 로 위임."""
    ta = uuid4()
    tb = uuid4()
    mock_tenants = AsyncMock(return_value=[ta, tb])
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store.agent_document_store.list_tenants_with_doctype",
        mock_tenants,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.news_store._get_shared_engine",
        lambda: "fake-engine",
    )

    subs = await list_subscribers()

    assert set(subs) == {str(ta), str(tb)}
    mock_tenants.assert_awaited_once_with("fake-engine", "agent_news_sub")
