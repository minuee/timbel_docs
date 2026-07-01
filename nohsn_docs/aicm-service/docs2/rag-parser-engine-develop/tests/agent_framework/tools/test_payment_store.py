"""payment_store unit tests — Phase 1.5C P0 추상 layer.

실 PG (Toss / 카카오페이) 호출 X — documents.kind='refund_request' 로 기록만.
계약: agent_document_store.create_item 호출 인자 검증 + status='pending'.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.payment_store import refund


@pytest.mark.asyncio
async def test_refund_creates_pending_request(monkeypatch):
    tenant = uuid4()
    fake_doc_id = uuid4()
    mock_create = AsyncMock(return_value=fake_doc_id)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.payment_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.payment_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await refund(
        {
            "tenant_id": str(tenant),
            "order_id": "ORD-2026-001",
            "amount": 15000,
            "reason": "고객 변심",
        }
    )

    assert r["success"] is True
    assert r["id"] == str(fake_doc_id)
    assert r["status"] == "pending"
    assert r["order_id"] == "ORD-2026-001"
    assert r["amount"] == 15000
    assert "환불 요청 접수" in r["summary"]

    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[1] == tenant
    assert call_args[2] == "refund_request"
    body = call_kwargs["body"]
    assert body["kind"] == "refund_request"
    assert body["order_id"] == "ORD-2026-001"
    assert body["amount"] == 15000
    assert body["reason"] == "고객 변심"
    assert body["status"] == "pending"
    assert "requested_at" in body


@pytest.mark.asyncio
async def test_refund_amount_string_and_float(monkeypatch):
    tenant = uuid4()
    mock_create = AsyncMock(return_value=uuid4())
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.payment_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.payment_store._get_shared_engine",
        lambda: "fake-engine",
    )

    # string
    r1 = await refund(
        {
            "tenant_id": str(tenant),
            "order_id": "ORD-1",
            "amount": "12500",
        }
    )
    assert r1["amount"] == 12500
    # float (반올림)
    r2 = await refund(
        {
            "tenant_id": str(tenant),
            "order_id": "ORD-2",
            "amount": 9999.6,
        }
    )
    assert r2["amount"] == 10000


@pytest.mark.asyncio
async def test_refund_rejects_zero_or_negative_amount(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r1 = await refund(
        {
            "tenant_id": str(uuid4()),
            "order_id": "ORD-1",
            "amount": 0,
        }
    )
    assert r1["success"] is False
    assert "amount" in r1["error"]

    r2 = await refund(
        {
            "tenant_id": str(uuid4()),
            "order_id": "ORD-1",
            "amount": -100,
        }
    )
    assert r2["success"] is False


@pytest.mark.asyncio
async def test_refund_requires_order_id(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await refund(
        {
            "tenant_id": str(uuid4()),
            "order_id": "   ",
            "amount": 1000,
        }
    )
    assert r["success"] is False
    assert "order_id" in r["error"]


@pytest.mark.asyncio
async def test_refund_requires_tenant(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await refund({"order_id": "ORD-1", "amount": 1000})
    assert r["success"] is False
    assert "tenant_id" in r["error"]


@pytest.mark.asyncio
async def test_refund_rejects_redis_mode(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "redis")
    r = await refund(
        {
            "tenant_id": str(uuid4()),
            "order_id": "ORD-1",
            "amount": 1000,
        }
    )
    assert r["success"] is False
    assert "kms" in r["error"]


@pytest.mark.asyncio
async def test_refund_summary_formats_amount(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.payment_store.agent_document_store.create_item",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.payment_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await refund(
        {
            "tenant_id": str(tenant),
            "order_id": "ORD-99",
            "amount": 1234567,
        }
    )
    assert "1,234,567원" in r["summary"]
