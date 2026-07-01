"""Phase 8 (KMS-Plus) — get_agent_engine 가 guard/inv_store 를 주입하는지 검증.

_build_guard_and_inv_store() 는 DB 연결 실패 시 (None, None) 반환하도록
설계됨. 따라서 단위 테스트는 두 갈래로:
1. 정상 환경 — engine.execution_guard / engine.tool_invocation_store 가 None 이 아님.
2. fallback — _build_guard_and_inv_store 가 (None, None) 반환할 때도 engine 빌드는 성공.

vLLM/Redis 외부 의존을 피하려고 _build_engine 의 무거운 부품을 mock.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _clear_singleton_cache():
    # _build_engine 은 lru_cache — 격리 위해 재호출 시 캐시 클리어.
    from src.agent_framework.api.dependencies import _build_engine
    _build_engine.cache_clear()


def test_build_guard_and_inv_store_returns_tuple():
    """팩토리 함수는 (guard, store) tuple — 정상 시 둘 다 instance.

    DB가 살아있는 환경 (CI 컨테이너) 에선 instance, 그렇지 않은 env 에선
    (None, None). 어느 쪽이든 tuple 반환은 보장되어야 한다.
    """
    from src.agent_framework.api.dependencies import _build_guard_and_inv_store

    result = _build_guard_and_inv_store()
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_engine_singleton_has_guard_and_inv_store_attrs():
    """엔진 빌드 후 execution_guard / tool_invocation_store 속성 존재 검증.

    실제 인스턴스 여부는 환경에 따라 달라질 수 있어 — 속성 자체가
    AgentEngine 에 노출되어 있고, 빌드 시 주입 시도가 일어났는지를 확인.
    """
    _clear_singleton_cache()
    try:
        # Heavy 의존성 mock — 실제 vLLM/Redis 연결 회피.
        with patch(
            "src.agent_framework.api.dependencies._build_guard_and_inv_store"
        ) as mock_build:
            sentinel_guard = object()
            sentinel_store = object()
            mock_build.return_value = (sentinel_guard, sentinel_store)

            with patch(
                "src.agent_framework.api.dependencies.aioredis.from_url"
            ), patch(
                "src.agent_framework.api.dependencies.VLLMAdapter"
            ), patch(
                "src.agent_framework.api.dependencies."
                "_load_skills_from_configured_source",
                return_value={},
            ), patch(
                "src.agent_framework.api.dependencies._get_or_create_db_engine"
            ), patch(
                "src.agent_framework.api.dependencies.SkillRegistry"
            ), patch(
                "src.agent_framework.api.dependencies.MultiLabelIntentClassifier"
            ), patch(
                "src.agent_framework.api.dependencies.DraftComposer"
            ), patch(
                "src.agent_framework.api.dependencies.ToolCallingLoop"
            ):
                from src.agent_framework.api.dependencies import _build_engine

                engine = _build_engine()
                assert engine.execution_guard is sentinel_guard
                assert engine.tool_invocation_store is sentinel_store
                assert mock_build.called
    finally:
        _clear_singleton_cache()


def test_engine_attrs_default_to_none_when_factory_returns_none():
    """팩토리가 (None, None) 반환해도 engine 빌드는 성공 + 속성은 None."""
    _clear_singleton_cache()
    try:
        with patch(
            "src.agent_framework.api.dependencies._build_guard_and_inv_store",
            return_value=(None, None),
        ), patch(
            "src.agent_framework.api.dependencies.aioredis.from_url"
        ), patch(
            "src.agent_framework.api.dependencies.VLLMAdapter"
        ), patch(
            "src.agent_framework.api.dependencies."
            "_load_skills_from_configured_source",
            return_value={},
        ), patch(
            "src.agent_framework.api.dependencies._get_or_create_db_engine"
        ), patch(
            "src.agent_framework.api.dependencies.SkillRegistry"
        ), patch(
            "src.agent_framework.api.dependencies.MultiLabelIntentClassifier"
        ), patch(
            "src.agent_framework.api.dependencies.DraftComposer"
        ), patch(
            "src.agent_framework.api.dependencies.ToolCallingLoop"
        ):
            from src.agent_framework.api.dependencies import _build_engine

            engine = _build_engine()
            assert engine.execution_guard is None
            assert engine.tool_invocation_store is None
    finally:
        _clear_singleton_cache()
