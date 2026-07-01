"""D31d Phase 3 §2 (#212) — RLS violation counter unit tests.

3 hook site 의 inc 동작 검증:
1. bind_agent_scope — non-UUID agent_id 진입 (no-op).
2. bind_system_scope — null tenant + allow_null_tenant=False (write 위험).
3. payload_sync — tenant_slug_not_found.

비파괴 검증: counter inc 만 발생, 기존 동작 (yield, return None 등) 변경 없음.
"""
from __future__ import annotations

import asyncio

import pytest

from src.api.middleware.rls_context import bind_agent_scope, bind_system_scope
from src.common.metrics import KMS_RLS_VIOLATION_TOTAL


def _read_counter(source: str, table: str, operation: str) -> float:
    """KMS_RLS_VIOLATION_TOTAL 의 특정 라벨 조합 sample 값 추출."""
    return KMS_RLS_VIOLATION_TOTAL.labels(
        source=source, table=table, operation=operation
    )._value.get()


@pytest.mark.asyncio
async def test_rls_violation_bind_agent_scope_invalid_id() -> None:
    """bind_agent_scope — non-UUID 진입 시 counter inc."""
    before = _read_counter(
        source="middleware",
        table="any",
        operation="bind_agent_scope_invalid_id",
    )

    # non-UUID agent_id (no-op 분기 진입).
    async with bind_agent_scope("not-a-uuid"):
        pass

    after = _read_counter(
        source="middleware",
        table="any",
        operation="bind_agent_scope_invalid_id",
    )
    assert after == before + 1.0, (
        f"counter 가 inc 되지 않음: before={before}, after={after}"
    )


@pytest.mark.asyncio
async def test_rls_violation_bind_agent_scope_none_id() -> None:
    """bind_agent_scope — None agent_id 진입 시 counter inc."""
    before = _read_counter(
        source="middleware",
        table="any",
        operation="bind_agent_scope_invalid_id",
    )

    async with bind_agent_scope(None):
        pass

    after = _read_counter(
        source="middleware",
        table="any",
        operation="bind_agent_scope_invalid_id",
    )
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_rls_violation_bind_agent_scope_valid_uuid_no_inc() -> None:
    """bind_agent_scope — 정상 UUID 시 counter 변화 0 (false positive 방지)."""
    before = _read_counter(
        source="middleware",
        table="any",
        operation="bind_agent_scope_invalid_id",
    )

    async with bind_agent_scope("11111111-1111-1111-1111-111111111111"):
        pass

    after = _read_counter(
        source="middleware",
        table="any",
        operation="bind_agent_scope_invalid_id",
    )
    assert after == before, (
        f"정상 UUID 인데 counter 가 inc 됨: before={before}, after={after}"
    )


@pytest.mark.asyncio
async def test_rls_violation_bind_system_scope_null_tenant() -> None:
    """bind_system_scope — null tenant + allow_null_tenant=False 시 counter inc."""
    before = _read_counter(
        source="middleware",
        table="any",
        operation="bind_system_scope_null_tenant",
    )

    async with bind_system_scope(None, allow_null_tenant=False):
        pass

    after = _read_counter(
        source="middleware",
        table="any",
        operation="bind_system_scope_null_tenant",
    )
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_rls_violation_bind_system_scope_allow_null_no_inc() -> None:
    """bind_system_scope — allow_null_tenant=True 시 counter 변화 0 (read-only path 면제)."""
    before = _read_counter(
        source="middleware",
        table="any",
        operation="bind_system_scope_null_tenant",
    )

    async with bind_system_scope(None, allow_null_tenant=True):
        pass

    after = _read_counter(
        source="middleware",
        table="any",
        operation="bind_system_scope_null_tenant",
    )
    assert after == before, (
        f"allow_null_tenant=True 인데 counter 가 inc 됨: before={before}, after={after}"
    )


@pytest.mark.asyncio
async def test_rls_violation_bind_system_scope_with_tenant_no_inc() -> None:
    """bind_system_scope — 정상 tenant_id 시 counter 변화 0."""
    before = _read_counter(
        source="middleware",
        table="any",
        operation="bind_system_scope_null_tenant",
    )

    async with bind_system_scope("44444444-4444-4444-4444-444444444444"):
        pass

    after = _read_counter(
        source="middleware",
        table="any",
        operation="bind_system_scope_null_tenant",
    )
    assert after == before


@pytest.mark.asyncio
async def test_rls_violation_payload_sync_slug_not_found() -> None:
    """payload_sync._resolve_tenant_slug — row 없을 때 counter inc."""
    from src.search.payload_sync import _resolve_tenant_slug

    before = _read_counter(
        source="payload_sync",
        table="documents",
        operation="tenant_slug_not_found",
    )

    class _StubResult:
        def fetchone(self) -> None:
            return None

    class _StubSession:
        async def execute(self, *_args, **_kwargs) -> _StubResult:
            return _StubResult()

    slug = await _resolve_tenant_slug("00000000-0000-0000-0000-000000000000", _StubSession())  # type: ignore[arg-type]
    assert slug is None  # 비파괴 — 기존 동작 유지.

    after = _read_counter(
        source="payload_sync",
        table="documents",
        operation="tenant_slug_not_found",
    )
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_rls_violation_payload_sync_slug_found_no_inc() -> None:
    """payload_sync._resolve_tenant_slug — row 있을 때 counter 변화 0."""
    from src.search.payload_sync import _resolve_tenant_slug

    before = _read_counter(
        source="payload_sync",
        table="documents",
        operation="tenant_slug_not_found",
    )

    class _StubResult:
        def fetchone(self):  # type: ignore[no-untyped-def]
            return ("ricky-personal",)

    class _StubSession:
        async def execute(self, *_args, **_kwargs) -> _StubResult:
            return _StubResult()

    slug = await _resolve_tenant_slug("00000000-0000-0000-0000-000000000000", _StubSession())  # type: ignore[arg-type]
    assert slug == "ricky-personal"  # 비파괴.

    after = _read_counter(
        source="payload_sync",
        table="documents",
        operation="tenant_slug_not_found",
    )
    assert after == before


@pytest.mark.asyncio
async def test_rls_violation_payload_sync_db_exception_no_inc() -> None:
    """payload_sync._resolve_tenant_slug — DB exception 시 counter 변화 0
    (GPT-5 verdict §2: transient DB 오류는 RLS 위반 분류 X)."""
    from src.search.payload_sync import _resolve_tenant_slug

    before = _read_counter(
        source="payload_sync",
        table="documents",
        operation="tenant_slug_not_found",
    )

    class _StubSession:
        async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("connection refused")

    slug = await _resolve_tenant_slug("00000000-0000-0000-0000-000000000000", _StubSession())  # type: ignore[arg-type]
    assert slug is None  # 기존 동작 — except 후 None 반환.

    after = _read_counter(
        source="payload_sync",
        table="documents",
        operation="tenant_slug_not_found",
    )
    assert after == before, (
        f"DB exception (transient) 인데 counter 가 inc 됨: before={before}, after={after}"
    )


def test_kms_rls_violation_counter_metric_definition() -> None:
    """metric 정의 검증 — labelnames + 등록 확인.

    prometheus_client 는 Counter 의 _name 에서 '_total' suffix 를 자동 제거 후
    inc 시 다시 추가 → exposition 이름은 'kms_rls_violation_total'.
    """
    assert KMS_RLS_VIOLATION_TOTAL._name == "kms_rls_violation"
    assert set(KMS_RLS_VIOLATION_TOTAL._labelnames) == {"source", "table", "operation"}
