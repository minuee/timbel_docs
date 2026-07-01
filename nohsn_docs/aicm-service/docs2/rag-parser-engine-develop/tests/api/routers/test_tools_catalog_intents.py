"""Intent visibility 필드 — _CATALOG 단위 테스트."""
import pytest
from src.api.routers.tools_v1 import _CATALOG


def test_all_tools_have_intents():
    for tool in _CATALOG:
        if tool.is_implemented:
            assert isinstance(tool.triggered_by_intents, list), (
                f"{tool.name} missing triggered_by_intents"
            )


def test_all_tools_have_example_utterances():
    for tool in _CATALOG:
        if tool.is_implemented:
            assert isinstance(tool.example_utterances, list)
            # 구현된 도구는 예시 발화 1개 이상
            assert len(tool.example_utterances) >= 1, (
                f"{tool.name} no example utterances"
            )


def test_intents_are_lowercase_snake():
    for tool in _CATALOG:
        for intent in tool.triggered_by_intents:
            assert intent == intent.lower(), (
                f"{tool.name}: intent '{intent}' not lowercase"
            )
            assert " " not in intent, (
                f"{tool.name}: intent '{intent}' contains space"
            )


def test_unimplemented_tools_allowed_empty_intents():
    """미구현 도구는 intents 빈 리스트도 허용 (단, 리스트 타입이어야 함)."""
    for tool in _CATALOG:
        if not tool.is_implemented:
            assert isinstance(tool.triggered_by_intents, list), (
                f"{tool.name} triggered_by_intents must be a list"
            )
