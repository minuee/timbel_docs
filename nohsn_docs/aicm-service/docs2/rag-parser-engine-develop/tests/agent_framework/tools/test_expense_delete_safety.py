"""Phase 1.5A Task 8e — expense.delete id-only enforcement.

GPT-5.5 deep dive 발견 결함: amount/category/spent_at 만으로 broad delete 가능
(예: ``expense.delete(amount=5000)`` → 같은 금액의 모든 항목 일괄 삭제).

본 테스트는 id (UUID) 가 유일한 selector 임을 강제한다.

- id 있으면 OK (extras 동봉되어도 무시).
- id 없으면 INVALID_INPUT — meta.outcome 확인.
- LLM 은 *list/sum_by_category 로 id 확보 후 delete 호출* 강제 (preview-confirm
  패턴) 의 1차 가드 레이어.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.tools import expense_store


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def patched_redis_delete(monkeypatch):
    """redis 백엔드 mock — 실제 Redis 미접속 환경에서 delete 경로 검증.

    AGENT_DATA_STORE 가 redis (default) 인 경우 expense_store.delete 가
    rs.remove_by_id 를 호출하므로 그 부분만 가로챈다.
    """
    monkeypatch.setenv("AGENT_DATA_STORE", "redis")
    rs_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(expense_store.rs, "remove_by_id", rs_mock)
    return rs_mock


# ── Positive case — id 명시 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_with_id_ok(patched_redis_delete):
    """id (UUID) 만 있으면 정상 삭제."""
    target_id = str(uuid4())
    res = await expense_store.delete({"id": target_id, "phone": "010-1"})
    assert res.get("success") is True
    assert res.get("deleted_count") == 1
    patched_redis_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_with_id_plus_extra_filters_ok(patched_redis_delete):
    """id 가 있으면 extras (amount/category/spent_at) 가 와도 OK — id 가 sufficient."""
    target_id = str(uuid4())
    res = await expense_store.delete(
        {"id": target_id, "amount": 5000, "category": "식비", "spent_at": "2026-05-06", "phone": "010-1"}
    )
    assert res.get("success") is True
    assert res.get("deleted_count") == 1


# ── Negative cases — id 없음 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_with_amount_only_invalid(patched_redis_delete):
    """amount 만으로 broad delete 차단 — INVALID_INPUT."""
    res = await expense_store.delete({"amount": 5000, "phone": "010-1"})
    assert res.get("success") is True  # tool 실행은 성공 (도메인 결과)
    meta = res.get("meta") or {}
    assert meta.get("outcome") == "invalid_input"
    assert meta.get("reason") == "id_required"
    assert meta.get("user_action_required") is True
    # 실제 삭제 호출은 안 일어나야 함
    patched_redis_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_with_category_only_invalid(patched_redis_delete):
    """category 만으로 broad delete 차단."""
    res = await expense_store.delete({"category": "식비", "phone": "010-1"})
    assert res.get("success") is True
    meta = res.get("meta") or {}
    assert meta.get("outcome") == "invalid_input"
    patched_redis_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_with_date_only_invalid(patched_redis_delete):
    """spent_at 만으로 broad delete 차단."""
    res = await expense_store.delete({"spent_at": "2026-05-06", "phone": "010-1"})
    assert res.get("success") is True
    meta = res.get("meta") or {}
    assert meta.get("outcome") == "invalid_input"
    patched_redis_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_no_args_invalid(patched_redis_delete):
    """args 비어 있으면 reject."""
    res = await expense_store.delete({"phone": "010-1"})
    assert res.get("success") is True
    meta = res.get("meta") or {}
    assert meta.get("outcome") == "invalid_input"
    patched_redis_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_with_description_only_invalid(patched_redis_delete):
    """description substring 만으로 broad delete 차단 — 가장 위험한 경로."""
    res = await expense_store.delete({"description": "스타벅스", "phone": "010-1"})
    assert res.get("success") is True
    meta = res.get("meta") or {}
    assert meta.get("outcome") == "invalid_input"
    patched_redis_delete.assert_not_awaited()


# ── Invalid id format ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_with_non_uuid_id_invalid(patched_redis_delete):
    """id 가 UUID 형식이 아니면 reject — LLM 이 임의 문자열 (예: '첫번째')

    넘겨도 broad mutation 차단."""
    res = await expense_store.delete({"id": "first-item", "phone": "010-1"})
    assert res.get("success") is True
    meta = res.get("meta") or {}
    assert meta.get("outcome") == "invalid_input"
    assert meta.get("reason") == "id_required"
    patched_redis_delete.assert_not_awaited()
