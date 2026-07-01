"""kind → adapter instance lookup."""
from __future__ import annotations
from src.integration.external_agent.base import ChannelAdapter
from src.integration.external_agent.telegram_adapter import TelegramAdapter


_REGISTRY: dict[str, ChannelAdapter] = {
    "telegram": TelegramAdapter(),
}


def get_adapter(kind: str) -> ChannelAdapter | None:
    return _REGISTRY.get(kind)


def supported_kinds() -> list[str]:
    return sorted(_REGISTRY.keys())
