"""inventory_store unit tests — Phase 1.5C P0 read-only.

documents.kind='inventory_item' 검색 + status 분류 검증.
실 PIM/POS 연동 X — 본 PR 은 read-only check 만.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.inventory_store import check


def _seed_items() -> list[dict]:
    """list_items 가 반환하는 평탄화된 row 셋."""
    return [
        {
            "id": "item-1",
            "title": "겨울 패딩 (블랙, M)",
            "item_name": "겨울 패딩 (블랙, M)",
            "sku": "PAD-BK-M",
            "current_qty": 12,
            "low_threshold": 5,
            "last_updated": "2026-05-06T10:00:00",
        },
        {
            "id": "item-2",
            "title": "겨울 패딩 (블랙, L)",
            "item_name": "겨울 패딩 (블랙, L)",
            "sku": "PAD-BK-L",
            "current_qty": 3,  # low
            "low_threshold": 5,
            "last_updated": "2026-05-06T10:00:00",
        },
        {
            "id": "item-3",
            "title": "겨울 패딩 (블랙, XL)",
            "item_name": "겨울 패딩 (블랙, XL)",
            "sku": "PAD-BK-XL",
            "current_qty": 0,  # out_of_stock
            "low_threshold": 5,
            "last_updated": "2026-05-06T10:00:00",
            "restock_eta": "2026-05-15",
        },
    ]


@pytest.mark.asyncio
async def test_check_by_sku_in_stock(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed_items()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await check({"tenant_id": str(tenant), "sku": "PAD-BK-M"})
    assert r["success"] is True
    assert r["matched"] == 1
    assert r["status"] == "in_stock"
    assert r["current_qty"] == 12
    assert r["item"]["sku"] == "PAD-BK-M"
    assert "재고 있음" in r["summary"]


@pytest.mark.asyncio
async def test_check_low_stock(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed_items()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await check({"tenant_id": str(tenant), "sku": "PAD-BK-L"})
    assert r["status"] == "low"
    assert r["current_qty"] == 3
    assert "재고 적음" in r["summary"]


@pytest.mark.asyncio
async def test_check_out_of_stock_with_restock_eta(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed_items()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await check({"tenant_id": str(tenant), "sku": "PAD-BK-XL"})
    assert r["status"] == "out_of_stock"
    assert r["current_qty"] == 0
    assert r["restock_eta"] == "2026-05-15"
    assert "품절" in r["summary"]


@pytest.mark.asyncio
async def test_check_disambiguates_multiple_matches(monkeypatch):
    """item_name substring 으로 여러 건 매칭되면 candidates 반환."""
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed_items()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await check({"tenant_id": str(tenant), "item_name": "겨울 패딩"})
    assert r["success"] is True
    assert r["matched"] == 3
    assert "candidates" in r
    assert len(r["candidates"]) == 3
    assert "정확한 상품명" in r["summary"]


@pytest.mark.asyncio
async def test_check_no_match(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed_items()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await check({"tenant_id": str(tenant), "sku": "NONEXIST"})
    assert r["success"] is False
    assert r["matched"] == 0
    assert "찾지 못했습니다" in r["summary"]


@pytest.mark.asyncio
async def test_check_requires_at_least_one_key(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await check({"tenant_id": str(uuid4())})
    assert r["success"] is False
    assert "최소 하나" in r["error"]


@pytest.mark.asyncio
async def test_check_requires_tenant(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await check({"sku": "PAD-BK-M"})
    assert r["success"] is False
    assert "tenant_id" in r["error"]


@pytest.mark.asyncio
async def test_check_rejects_redis_mode(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "redis")
    r = await check({"tenant_id": str(uuid4()), "sku": "X"})
    assert r["success"] is False
    assert "kms" in r["error"]


@pytest.mark.asyncio
async def test_check_by_item_id(monkeypatch):
    """item_id 가 주어지면 동일 sku/item_name 다수여도 정확 매칭."""
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed_items()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.inventory_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await check({"tenant_id": str(tenant), "item_id": "item-2"})
    assert r["success"] is True
    assert r["matched"] == 1
    assert r["item"]["id"] == "item-2"
    assert r["status"] == "low"
