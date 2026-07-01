"""D25 (#158) — RLS context (contextvars) unit tests.

D25 spec §7 — RLS context 의 set/get/reset 정합 + dataclass 검증.
"""
from __future__ import annotations

import asyncio

import pytest

from src.api.middleware.rls_context import (
    RLSContext,
    get_rls_context,
    reset_rls_context,
    set_rls_context,
)


def test_rls_context_default_none() -> None:
    """초기 상태 — get_rls_context() = None (default-deny)."""
    # 테스트 격리 위해 매번 set/reset 사이클로 검증.
    assert get_rls_context() is None


def test_rls_context_set_get_reset() -> None:
    """set → get → reset 사이클이 격리 보장."""
    ctx = RLSContext(
        agent_id="11111111-1111-1111-1111-111111111111",
        scope="agent",
        tenant_id="22222222-2222-2222-2222-222222222222",
    )
    token = set_rls_context(ctx)
    try:
        got = get_rls_context()
        assert got is not None
        assert got.agent_id == ctx.agent_id
        assert got.scope == "agent"
        assert got.tenant_id == ctx.tenant_id
    finally:
        reset_rls_context(token)
    assert get_rls_context() is None


def test_rls_context_admin_scope() -> None:
    """admin scope — 자기 tenant 안 cross-agent."""
    ctx = RLSContext(
        agent_id=None,
        scope="admin",
        tenant_id="33333333-3333-3333-3333-333333333333",
    )
    token = set_rls_context(ctx)
    try:
        got = get_rls_context()
        assert got is not None
        assert got.scope == "admin"
        assert got.agent_id is None
        assert got.tenant_id == "33333333-3333-3333-3333-333333333333"
    finally:
        reset_rls_context(token)


def test_rls_context_superadmin_scope() -> None:
    """superadmin — cross-tenant (tenant_id 무관)."""
    ctx = RLSContext(agent_id=None, scope="superadmin", tenant_id=None)
    token = set_rls_context(ctx)
    try:
        got = get_rls_context()
        assert got is not None
        assert got.scope == "superadmin"
    finally:
        reset_rls_context(token)


def test_rls_context_system_scope() -> None:
    """system scope — background worker / cron / dispatcher."""
    ctx = RLSContext(agent_id=None, scope="system", tenant_id=None)
    token = set_rls_context(ctx)
    try:
        got = get_rls_context()
        assert got is not None
        assert got.scope == "system"
    finally:
        reset_rls_context(token)


def test_rls_context_immutable_dataclass() -> None:
    """frozen=True — context 변조 차단."""
    ctx = RLSContext(agent_id="a", scope="agent", tenant_id="t")
    with pytest.raises((AttributeError, Exception)):
        ctx.scope = "admin"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_rls_context_isolated_per_task() -> None:
    """contextvars 가 asyncio task 별 격리."""

    async def task_a() -> str | None:
        ctx = RLSContext(agent_id="agent-a", scope="agent", tenant_id="t1")
        token = set_rls_context(ctx)
        try:
            await asyncio.sleep(0.01)
            return get_rls_context().agent_id  # type: ignore[union-attr]
        finally:
            reset_rls_context(token)

    async def task_b() -> str | None:
        ctx = RLSContext(agent_id="agent-b", scope="agent", tenant_id="t2")
        token = set_rls_context(ctx)
        try:
            await asyncio.sleep(0.01)
            return get_rls_context().agent_id  # type: ignore[union-attr]
        finally:
            reset_rls_context(token)

    a_id, b_id = await asyncio.gather(task_a(), task_b())
    assert a_id == "agent-a"
    assert b_id == "agent-b"
    # 두 task 종료 후 main 의 contextvar = None.
    assert get_rls_context() is None
