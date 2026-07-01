"""reservation_store unit tests — Phase 1.5C P0.

KMS-only tool — agent_document_store 호출 계약을 monkeypatch 로 검증.
실 DB 통합 검증은 별도 integration test (이번 PR 범위 X).

검증 범위:
- create: 필수 슬롯 검증 + tenant 격리 + ISO 파싱 + 시작/종료 순서.
- cancel: id-only enforcement + status 전환 + 미존재 처리.
- check_availability: overlap 검사 + raw 정보 비노출.
- reschedule: 기존 row body update + new_start/new_end 검증.
- 공통: redis 모드에서 호출 차단 + tenant_id 미주입 시 거부.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools.reservation_store import (
    cancel,
    check_availability,
    create,
    reschedule,
)


# ── create ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_persists_row(monkeypatch):
    tenant = uuid4()
    fake_doc_id = uuid4()
    mock_create = AsyncMock(return_value=fake_doc_id)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.create_item",
        mock_create,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await create(
        {
            "tenant_id": str(tenant),
            "title": "홍길동님 단체 4명",
            "start_at": "2026-05-08T19:00:00",
            "end_at": "2026-05-08T20:30:00",
            "attendee_count": 4,
            "location": "1번 테이블",
            "contact": "010-1234-5678",
        }
    )

    assert r["success"] is True
    assert r["id"] == str(fake_doc_id)
    assert r["status"] == "confirmed"
    assert "예약 등록 완료" in r["summary"]

    mock_create.assert_awaited_once()
    call_args = mock_create.await_args.args
    call_kwargs = mock_create.await_args.kwargs
    assert call_args[0] == "fake-engine"
    assert call_args[1] == tenant
    assert call_args[2] == "reservation"
    assert call_kwargs["title"] == "홍길동님 단체 4명"
    body = call_kwargs["body"]
    assert body["start_at"] == "2026-05-08T19:00:00"
    assert body["end_at"] == "2026-05-08T20:30:00"
    assert body["attendee_count"] == 4
    assert body["location"] == "1번 테이블"
    assert body["contact"] == "010-1234-5678"
    assert body["status"] == "confirmed"
    assert body["kind"] == "reservation"


@pytest.mark.asyncio
async def test_create_rejects_redis_mode(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "redis")
    r = await create(
        {
            "tenant_id": str(uuid4()),
            "title": "테스트",
            "start_at": "2026-05-08T19:00",
            "end_at": "2026-05-08T20:00",
        }
    )
    assert r["success"] is False
    assert "kms" in r["error"]


@pytest.mark.asyncio
async def test_create_requires_tenant_id(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await create(
        {
            "title": "테스트",
            "start_at": "2026-05-08T19:00",
            "end_at": "2026-05-08T20:00",
        }
    )
    assert r["success"] is False
    assert "tenant_id" in r["error"]


@pytest.mark.asyncio
async def test_create_rejects_invalid_time_range(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await create(
        {
            "tenant_id": str(uuid4()),
            "title": "잘못된 시간",
            "start_at": "2026-05-08T20:00",
            "end_at": "2026-05-08T19:00",  # end < start
        }
    )
    assert r["success"] is False
    assert "end_at" in r["error"]


@pytest.mark.asyncio
async def test_create_rejects_empty_title(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await create(
        {
            "tenant_id": str(uuid4()),
            "title": "   ",
            "start_at": "2026-05-08T19:00",
            "end_at": "2026-05-08T20:00",
        }
    )
    assert r["success"] is False
    assert "title" in r["error"]


@pytest.mark.asyncio
async def test_create_rejects_invalid_iso(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await create(
        {
            "tenant_id": str(uuid4()),
            "title": "테스트",
            "start_at": "내일 7시",  # not ISO
            "end_at": "2026-05-08T20:00",
        }
    )
    assert r["success"] is False
    assert "start_at" in r["error"]


# ── cancel ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_marks_status(monkeypatch):
    tenant = uuid4()
    mock_update = AsyncMock(return_value=True)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.update_item",
        mock_update,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await cancel(
        {
            "tenant_id": str(tenant),
            "id": "doc-42",
            "reason": "고객 변심",
        }
    )

    assert r["success"] is True
    assert r["status"] == "cancelled"

    mock_update.assert_awaited_once()
    call_kwargs = mock_update.await_args.kwargs
    body_patch = call_kwargs["body_patch"]
    assert body_patch["status"] == "cancelled"
    assert body_patch["cancel_reason"] == "고객 변심"
    assert "cancelled_at" in body_patch


@pytest.mark.asyncio
async def test_cancel_requires_id(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await cancel({"tenant_id": str(uuid4())})
    assert r["success"] is False
    assert "id" in r["error"]


@pytest.mark.asyncio
async def test_cancel_handles_not_found(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    mock_update = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.update_item",
        mock_update,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await cancel({"tenant_id": str(uuid4()), "id": "nope"})
    assert r["success"] is False
    assert "not found" in r["error"]


# ── check_availability ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_availability_empty(monkeypatch):
    """기존 예약 0건 — 항상 가능."""
    tenant = uuid4()
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.list_items",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await check_availability(
        {
            "tenant_id": str(tenant),
            "start_at": "2026-05-08T19:00",
            "end_at": "2026-05-08T20:00",
        }
    )
    assert r["success"] is True
    assert r["available"] is True


@pytest.mark.asyncio
async def test_check_availability_overlap_detected(monkeypatch):
    tenant = uuid4()
    existing = [
        {
            "id": "r1",
            "title": "기존 예약",
            "start_at": "2026-05-08T19:30:00",
            "end_at": "2026-05-08T20:30:00",
            "status": "confirmed",
        }
    ]
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.list_items",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await check_availability(
        {
            "tenant_id": str(tenant),
            "start_at": "2026-05-08T19:00",
            "end_at": "2026-05-08T20:00",  # overlaps with 19:30-20:30
        }
    )
    assert r["success"] is True
    assert r["available"] is False
    # raw 예약 정보 노출 X — 결과 dict 에 기존 title/contact 등 포함되지 않음.
    assert "기존 예약" not in str(r)


@pytest.mark.asyncio
async def test_check_availability_ignores_cancelled(monkeypatch):
    tenant = uuid4()
    existing = [
        {
            "id": "r1",
            "start_at": "2026-05-08T19:30:00",
            "end_at": "2026-05-08T20:30:00",
            "status": "cancelled",  # 취소된 예약은 무시.
        }
    ]
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.list_items",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await check_availability(
        {
            "tenant_id": str(tenant),
            "start_at": "2026-05-08T19:00",
            "end_at": "2026-05-08T20:00",
        }
    )
    assert r["available"] is True


# ── reschedule ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reschedule_updates_times(monkeypatch):
    tenant = uuid4()
    mock_update = AsyncMock(return_value=True)
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.update_item",
        mock_update,
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )

    r = await reschedule(
        {
            "tenant_id": str(tenant),
            "id": "doc-7",
            "new_start_at": "2026-05-09T20:00",
            "new_end_at": "2026-05-09T21:00",
        }
    )
    assert r["success"] is True
    assert r["new_start_at"] == "2026-05-09T20:00:00"
    assert r["new_end_at"] == "2026-05-09T21:00:00"

    mock_update.assert_awaited_once()
    body_patch = mock_update.await_args.kwargs["body_patch"]
    assert body_patch["status"] == "rescheduled"
    assert "rescheduled_at" in body_patch


@pytest.mark.asyncio
async def test_reschedule_rejects_inverted_range(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    r = await reschedule(
        {
            "tenant_id": str(uuid4()),
            "id": "doc-7",
            "new_start_at": "2026-05-09T21:00",
            "new_end_at": "2026-05-09T20:00",  # invalid
        }
    )
    assert r["success"] is False
    assert "new_end_at" in r["error"]


@pytest.mark.asyncio
async def test_reschedule_handles_not_found(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_STORE", "kms")
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store.agent_document_store.update_item",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "src.agent_framework.tools.reservation_store._get_shared_engine",
        lambda: "fake-engine",
    )
    r = await reschedule(
        {
            "tenant_id": str(uuid4()),
            "id": "nope",
            "new_start_at": "2026-05-09T20:00",
            "new_end_at": "2026-05-09T21:00",
        }
    )
    assert r["success"] is False
    assert "not found" in r["error"]
