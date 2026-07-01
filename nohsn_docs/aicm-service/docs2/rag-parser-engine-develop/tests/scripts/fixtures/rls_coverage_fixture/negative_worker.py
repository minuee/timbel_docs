"""negative — wrap 누락 — guard 가 검출해야 함."""
from __future__ import annotations


async def handle_event(event):
    """wrap 누락 handler."""
    await _process(event)


async def _process(event):
    pass
