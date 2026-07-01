"""D33 §3 — bind_agent_scope() 컨텍스트 전파 단위 검증.

사전 GPT-5 §3 GO_WITH_CHANGES 권고:
1. agent scope 바인딩 후 RLSContext 가 정상 노출 + finally 후 원복.
2. asyncio.create_task 로 spawn 한 child task 가 동일 RLSContext 를 보는지
   (`contextvars.copy_context` 자동 전파 — Python asyncio default).

본 test 는 라우트 레벨이 아닌 *helper 자체* 의 의미 보장 검증. 실 라우트는
chat_v1 / agents_v1 / external_agent_v1 의 _scoped_engine_turn() wrapper 가
이 helper 를 사용 — wrapper 가 contextvar 전파를 그대로 위임.
"""
from __future__ import annotations

import asyncio
import contextvars
from uuid import uuid4

import pytest

from src.api.middleware.rls_context import (
    RLSContext,
    bind_agent_scope,
    get_rls_context,
    reset_rls_context,
    set_rls_context,
)


@pytest.mark.asyncio
async def test_bind_agent_scope_basic_overlay() -> None:
    """admin scope 위에 agent scope wrap → 안에선 agent, 밖에선 admin 으로 복원."""
    tid = str(uuid4())
    aid = str(uuid4())

    # 사전 admin scope 등록 (middleware 가 set 한 상황).
    admin_ctx = RLSContext(scope="admin", agent_id=None, tenant_id=tid)
    token = set_rls_context(admin_ctx)
    try:
        assert get_rls_context() == admin_ctx

        async with bind_agent_scope(aid, tid):
            inside = get_rls_context()
            assert inside is not None
            assert inside.scope == "agent"
            assert inside.agent_id == aid
            assert inside.tenant_id == tid

        # 종료 후 원복.
        after = get_rls_context()
        assert after == admin_ctx
    finally:
        reset_rls_context(token)


@pytest.mark.asyncio
async def test_bind_agent_scope_propagates_to_child_task() -> None:
    """asyncio.create_task 로 spawn 한 child 가 부모 RLSContext 를 본다.

    Python asyncio 의 default 동작 — create_task 는 contextvars.copy_context()
    로 부모 context snapshot 을 child 에 자동 전파.
    """
    tid = str(uuid4())
    aid = str(uuid4())

    captured: list[RLSContext | None] = []

    async def _child() -> None:
        # await 순간 caller (부모) 의 contextvars 가 도착.
        await asyncio.sleep(0.001)
        captured.append(get_rls_context())

    async with bind_agent_scope(aid, tid):
        # 부모 task 의 RLSContext 는 agent.
        assert get_rls_context() is not None
        assert get_rls_context().scope == "agent"  # type: ignore[union-attr]

        # child task spawn — copy_context 로 agent scope 전파.
        task = asyncio.create_task(_child())
        await task

    # child 가 capture 한 context 도 agent scope 였는지.
    assert len(captured) == 1
    child_ctx = captured[0]
    assert child_ctx is not None
    assert child_ctx.scope == "agent"
    assert child_ctx.agent_id == aid


@pytest.mark.asyncio
async def test_bind_agent_scope_noop_when_invalid_uuid() -> None:
    """agent_id 가 None / 비-UUID 면 RLSContext 변경 없음 (no-op)."""
    admin_ctx = RLSContext(scope="admin", agent_id=None, tenant_id=str(uuid4()))
    token = set_rls_context(admin_ctx)
    try:
        # None.
        async with bind_agent_scope(None, admin_ctx.tenant_id):
            assert get_rls_context() == admin_ctx

        # 비-UUID.
        async with bind_agent_scope("not-a-uuid", admin_ctx.tenant_id):
            assert get_rls_context() == admin_ctx

        # 빈 문자열.
        async with bind_agent_scope("", admin_ctx.tenant_id):
            assert get_rls_context() == admin_ctx
    finally:
        reset_rls_context(token)


@pytest.mark.asyncio
async def test_bind_agent_scope_async_generator_propagation() -> None:
    """async generator 안에서 bind_agent_scope wrap → 매 yield 사이 contextvar 유지.

    실 라우트의 _scoped_engine_turn() wrapper 패턴 검증.
    """
    tid = str(uuid4())
    aid = str(uuid4())

    captured_per_step: list[str] = []

    async def _engine_turn_stub():
        # 첫 yield 전 sleep — caller 의 contextvar 가 set 된 후 진입.
        await asyncio.sleep(0.001)
        ctx1 = get_rls_context()
        captured_per_step.append(ctx1.scope if ctx1 else "(none)")
        yield {"event": "token", "data": {"text": "a"}}

        await asyncio.sleep(0.001)
        ctx2 = get_rls_context()
        captured_per_step.append(ctx2.scope if ctx2 else "(none)")
        yield {"event": "done", "data": {}}

    async def _scoped_iter():
        async with bind_agent_scope(aid, tid):
            async for it in _engine_turn_stub():
                yield it

    items = []
    async for item in _scoped_iter():
        items.append(item)

    assert len(items) == 2
    assert captured_per_step == ["agent", "agent"]
