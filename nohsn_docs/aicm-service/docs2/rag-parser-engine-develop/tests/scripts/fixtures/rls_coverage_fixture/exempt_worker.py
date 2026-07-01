"""exempt — docstring 마커 — guard 가 면제해야 함."""
from __future__ import annotations


async def handle_event(event):
    """rls-coverage: exempt — caller wrap 으로 충분."""
    await _process(event)


async def _process(event):
    pass
