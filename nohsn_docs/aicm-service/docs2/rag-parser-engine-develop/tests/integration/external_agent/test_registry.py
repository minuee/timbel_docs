from src.integration.external_agent.registry import (
    get_adapter, supported_kinds,
)
from src.integration.external_agent.telegram_adapter import TelegramAdapter


def test_supported_kinds_includes_telegram():
    assert "telegram" in supported_kinds()


def test_get_adapter_telegram():
    a = get_adapter("telegram")
    assert isinstance(a, TelegramAdapter)


def test_get_adapter_unknown():
    assert get_adapter("nonexistent") is None
