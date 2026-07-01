"""nested-only-inner — outer entry has NO wrap; inner nested def has wrap.

GPT-5 §3 권고 — outer 가 wrap 안 했는데 inner 만 wrap 했으면 FAIL 이어야 함.
"""
from __future__ import annotations


async def handle_event(event):
    """outer entry — wrap 누락 (FAIL 대상)."""

    async def _inner_with_wrap():
        from src.api.middleware.rls_context import bind_system_scope

        async with bind_system_scope(str(event.tenant_id)):
            await _process(event)

    await _inner_with_wrap()


async def _process(event):
    pass
