"""#76 (2026-05-19) — `_is_sop_rag_enabled` default on 전환 검증.

사용자 발견 (2026-05-18): SOP repo 등록해도 system_prompt 에 inject 안 됨 →
root cause = ``FEATURE_SOP_RAG`` default off + tenant DB 미설정.

본 라운드 fix: default on + env kill-switch (``FEATURE_SOP_RAG=false``) 유지.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


def _make_engine_stub():
    """``_is_sop_rag_enabled`` 만 검증 — engine 의 다른 의존성 mock."""
    from src.agent_framework.runtime.engine import AgentEngine

    # __init__ 우회 — 메서드만 unbound 호출.
    return AgentEngine


def _call_is_sop_rag_enabled(env_value: str | None) -> bool:
    """env 값 set 후 ``_is_sop_rag_enabled`` 호출."""
    if env_value is None:
        os.environ.pop("FEATURE_SOP_RAG", None)
    else:
        os.environ["FEATURE_SOP_RAG"] = env_value
    AgentEngine = _make_engine_stub()
    # method 는 self 만 받음 — agent_context 는 안 봐도 됨 (env 만 분기).
    instance = MagicMock()
    # 실제 method 를 bound 호출.
    return AgentEngine._is_sop_rag_enabled(instance)


@pytest.fixture(autouse=True)
def _restore_env():
    """env FEATURE_SOP_RAG 원복."""
    original = os.environ.get("FEATURE_SOP_RAG")
    yield
    if original is None:
        os.environ.pop("FEATURE_SOP_RAG", None)
    else:
        os.environ["FEATURE_SOP_RAG"] = original


def test_default_unset_returns_true():
    """env 미설정 시 default on (#76 fix)."""
    assert _call_is_sop_rag_enabled(None) is True


def test_env_false_kill_switch():
    """env false 명시 시 off (운영 incident 대응 kill-switch)."""
    assert _call_is_sop_rag_enabled("false") is False


def test_env_true_explicit():
    """env true 명시 시 on (legacy default-off 환경 호환)."""
    assert _call_is_sop_rag_enabled("true") is True


def test_env_no_value():
    """env 'no' 도 off 로 해석."""
    assert _call_is_sop_rag_enabled("no") is False


def test_env_off_value():
    """env 'off' 도 off 로 해석."""
    assert _call_is_sop_rag_enabled("off") is False


def test_env_invalid_value_default_on():
    """invalid env (예: 'maybe') 시 default on (env_explicit 가 None 반환 → fallthrough)."""
    assert _call_is_sop_rag_enabled("maybe") is True


def test_env_1_value():
    """env '1' on 으로 해석."""
    assert _call_is_sop_rag_enabled("1") is True


def test_env_0_value():
    """env '0' off 로 해석."""
    assert _call_is_sop_rag_enabled("0") is False
