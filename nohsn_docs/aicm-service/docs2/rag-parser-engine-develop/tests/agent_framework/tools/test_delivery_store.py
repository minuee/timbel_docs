"""delivery_store unit tests — Phase 1.5C P0 추상 layer.

내부 documents 캐시만 조회. 실 carrier API 호출 X.
검증: tracking_number 정규화 + status 매핑 + 미존재 처리 + carrier hint 필터.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.delivery_store import track


def _seed() -> list[dict]:
    return [
        {
            "id": "d-1",
            "title": "송장 1234567890",
            "tracking_number": "1234567890",
            "carrier": "cj",
            "status": "in_transit",
            "last_updated": "2026-05-06T10:00:00",
            "eta": "2026-05-08",
            "last_event": "옥천허브 출발",
        },
        {
            "id": "d-2",
            "title": "송장 9999999999",
            "tracking_number": "9999999999",
            "carrier": "hanjin",
            "status": "delivered",
            "last_updated": "2026-05-05T18:30:00",
            "last_event": "수령 완료",
        },
        {
            "id": "d-3",
            "title": "송장 1234567890 (한진 동일번호)",
            "tracking_number": "1234567890",
            "carrier": "hanjin",
            "status": "out_for_delivery",
            "last_updated": "2026-05-06T09:00:00",
        },
    ]


@pytest.mark.asyncio
async def test_track_in_transit(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await track(
        {"tenant_id": str(tenant), "tracking_number": "1234567890", "carrier": "cj"}
    )
    assert r["success"] is True
    assert r["status"] == "in_transit"
    assert r["carrier"] == "cj"
    assert r["eta"] == "2026-05-08"
    assert r["last_event"] == "옥천허브 출발"
    assert "운송 중" in r["summary"]


@pytest.mark.asyncio
async def test_track_normalizes_tracking_number(monkeypatch):
    """공백·하이픈 들어와도 매칭."""
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await track(
        {
            "tenant_id": str(tenant),
            "tracking_number": "1234-5678-90",
            "carrier": "cj",
        }
    )
    assert r["success"] is True
    assert r["tracking_number"] == "1234567890"
    assert r["status"] == "in_transit"


@pytest.mark.asyncio
async def test_track_delivered(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await track({"tenant_id": str(tenant), "tracking_number": "9999999999"})
    assert r["status"] == "delivered"
    assert "배송 완료" in r["summary"]


@pytest.mark.asyncio
async def test_track_carrier_hint_filters(monkeypatch):
    """동일 송장번호 다른 carrier 두 건 — hint 로 정확 매칭."""
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store._get_shared_engine",
        lambda: "fake-engine",
    )
    # carrier=hanjin 으로 hint → out_for_delivery row 매칭.
    r = await track(
        {"tenant_id": str(tenant), "tracking_number": "1234567890", "carrier": "hanjin"}
    )
    assert r["status"] == "out_for_delivery"
    assert r["carrier"] == "hanjin"


@pytest.mark.asyncio
async def test_track_unknown_returns_hint(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await track({"tenant_id": str(tenant), "tracking_number": "0000000000"})
    assert r["success"] is False
    assert r["status"] == "unknown"
    # carrier webhook 활성화 안내가 summary 에 포함.
    assert "carrier" in r["summary"] or "후속" in r["summary"]


@pytest.mark.asyncio
async def test_track_requires_tenant(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await track({"tracking_number": "1234"})
    assert r["success"] is False
    assert "tenant_id" in r["error"]


@pytest.mark.asyncio
async def test_track_requires_tracking_number(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await track({"tenant_id": str(uuid4()), "tracking_number": ""})
    assert r["success"] is False
    assert "tracking_number" in r["error"]


@pytest.mark.asyncio
async def test_track_rejects_redis_mode(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "redis")
    r = await track({"tenant_id": str(uuid4()), "tracking_number": "1234"})
    assert r["success"] is False
    assert "kms" in r["error"]


@pytest.mark.asyncio
async def test_track_picks_most_recent_when_carrier_omitted(monkeypatch):
    """송장 1234567890 매칭 2건 (cj / hanjin) — last_updated 가장 최근(cj 10:00) 우선."""
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store.agent_document_store.list_items",
        AsyncMock(return_value=_seed()),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.delivery_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await track({"tenant_id": str(tenant), "tracking_number": "1234567890"})
    assert r["status"] == "in_transit"
    assert r["carrier"] == "cj"
