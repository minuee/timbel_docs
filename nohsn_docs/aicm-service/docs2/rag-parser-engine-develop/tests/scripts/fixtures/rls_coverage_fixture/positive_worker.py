"""positive — bind_system_scope wrap 정상 적용된 worker."""
from __future__ import annotations


async def handle_event(event):
    """test fixture handler — wrap 적용."""
    from src.api.middleware.rls_context import bind_system_scope

    async with bind_system_scope(str(event.tenant_id), allow_null_tenant=False):
        await _process(event)


async def _process(event):
    pass
