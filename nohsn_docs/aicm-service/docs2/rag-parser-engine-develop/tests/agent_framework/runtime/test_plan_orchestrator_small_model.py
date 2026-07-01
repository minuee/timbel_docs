"""Option β Stage 5 — PLAN_MODEL_SMALL flag 검증.

flag off  → LLM 호출 model=None (기존 31B 그대로, byte-equal).
flag on   → LLM 호출 model=PLAN_SMALL_MODEL env (기본 gemma-4-12b).
flag on + JSON parse 실패 → 31B fallback (model=None) 재시도.
flag on + PLAN_SMALL_MODEL env 오버라이드 → 지정 모델 사용.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent_framework.runtime.plan_orchestrator import PlanOrchestrator


_VALID_JSON = json.dumps(
    {
        "plan": [],
        "needs_clarification": False,
        "confidence": 0.9,
        "ambiguity_reasons": [],
        "summary": "test",
    }
)

_INVALID_JSON = "this is not json {"


def _make_decision(category: str = "schedule"):
    d = MagicMock()
    d.category = category
    d.reason = "test"
    d.matched_intent = "schedule"
    d.needs_llm_disambiguation = False
    d.verb = "schedule"
    d.domain = "calendar"
    return d


def _make_orch(llm_complete_side_effect=None, llm_complete_return_value=_VALID_JSON):
    llm = MagicMock()
    if llm_complete_side_effect is not None:
        llm.complete = AsyncMock(side_effect=llm_complete_side_effect)
    else:
        llm.complete = AsyncMock(return_value=llm_complete_return_value)
    return PlanOrchestrator(llm_client=llm), llm


@pytest.mark.asyncio
async def test_flag_off_default_model(monkeypatch):
    """flag off 시 LLM 호출에 model=None (기존 31B 경로)."""
    monkeypatch.delenv("FEATURE_PLAN_MODEL_SMALL", raising=False)

    orch, llm = _make_orch()

    with patch(
        "src.agent_framework.runtime.plan_orchestrator.is_enabled",
        return_value=False,
    ):
        with patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("schedule"),
        ):
            with patch(
                "src.agent_framework.runtime.plan_router.route",
                return_value=_make_decision("schedule"),
            ):
                result = await orch.generate_plan(
                    user_message="다음 주 회의 일정 잡아줘",
                    utterance_verb="schedule",
                    utterance_domain="calendar",
                    tenant_id="test-tenant",
                )

    assert result is not None
    llm.complete.assert_called_once()
    _args, _kwargs = llm.complete.call_args
    # model 키워드가 없거나 None 이어야 함.
    assert _kwargs.get("model") is None


@pytest.mark.asyncio
async def test_flag_on_uses_small_model(monkeypatch):
    """flag on 시 LLM 호출 model='gemma-4-12b' (기본 small model)."""
    monkeypatch.setenv("FEATURE_PLAN_MODEL_SMALL", "true")
    monkeypatch.delenv("PLAN_SMALL_MODEL", raising=False)

    orch, llm = _make_orch()

    with patch(
        "src.agent_framework.runtime.plan_orchestrator.is_enabled",
        return_value=True,
    ):
        with patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("schedule"),
        ):
            with patch(
                "src.agent_framework.runtime.plan_router.route",
                return_value=_make_decision("schedule"),
            ):
                result = await orch.generate_plan(
                    user_message="다음 주 회의 일정 잡아줘",
                    utterance_verb="schedule",
                    utterance_domain="calendar",
                    tenant_id="test-tenant",
                )

    assert result is not None
    llm.complete.assert_called_once()
    _args, _kwargs = llm.complete.call_args
    assert _kwargs.get("model") == "gemma-4-12b"


@pytest.mark.asyncio
async def test_flag_on_json_parse_failure_fallback(monkeypatch):
    """small model JSON parse 실패 시 31B fallback (model=None) 호출."""
    monkeypatch.setenv("FEATURE_PLAN_MODEL_SMALL", "true")
    monkeypatch.delenv("PLAN_SMALL_MODEL", raising=False)

    # 첫 번째 호출 → invalid JSON (small model 응답), 두 번째 → valid JSON (31B fallback).
    orch, llm = _make_orch(
        llm_complete_side_effect=[_INVALID_JSON, _VALID_JSON]
    )

    with patch(
        "src.agent_framework.runtime.plan_orchestrator.is_enabled",
        return_value=True,
    ):
        with patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("schedule"),
        ):
            with patch(
                "src.agent_framework.runtime.plan_router.route",
                return_value=_make_decision("schedule"),
            ):
                result = await orch.generate_plan(
                    user_message="다음 주 회의 일정 잡아줘",
                    utterance_verb="schedule",
                    utterance_domain="calendar",
                    tenant_id="test-tenant",
                )

    assert result is not None
    assert llm.complete.call_count == 2

    first_call_kwargs = llm.complete.call_args_list[0][1]
    second_call_kwargs = llm.complete.call_args_list[1][1]

    # 첫 호출 — small model.
    assert first_call_kwargs.get("model") == "gemma-4-12b"
    # 두 번째 호출 — 31B fallback (model=None).
    assert second_call_kwargs.get("model") is None


@pytest.mark.asyncio
async def test_flag_on_env_override(monkeypatch):
    """PLAN_SMALL_MODEL env 로 모델 명 오버라이드."""
    monkeypatch.setenv("FEATURE_PLAN_MODEL_SMALL", "true")
    monkeypatch.setenv("PLAN_SMALL_MODEL", "gemma-4-9b")

    orch, llm = _make_orch()

    with patch(
        "src.agent_framework.runtime.plan_orchestrator.is_enabled",
        return_value=True,
    ):
        with patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("schedule"),
        ):
            with patch(
                "src.agent_framework.runtime.plan_router.route",
                return_value=_make_decision("schedule"),
            ):
                result = await orch.generate_plan(
                    user_message="다음 주 회의 일정 잡아줘",
                    utterance_verb="schedule",
                    utterance_domain="calendar",
                    tenant_id="test-tenant",
                )

    assert result is not None
    llm.complete.assert_called_once()
    _args, _kwargs = llm.complete.call_args
    assert _kwargs.get("model") == "gemma-4-9b"
