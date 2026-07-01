"""FAST_INFO_LOOKUP_PLAN flag 분기 검증.

flag off  → fast_planner 호출 없이 기존 LLM 경로.
flag on + info_lookup  → fast_planner 호출, LLM 호출 0.
flag on + 다른 category → 기존 LLM 경로 (fast_planner 미사용).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent_framework.runtime.plan_orchestrator import PlanOrchestrator


def _make_decision(category: str = "info_lookup"):
    d = MagicMock()
    d.category = category
    d.reason = "test"
    d.matched_intent = "info_lookup"
    d.needs_llm_disambiguation = False
    d.verb = "info"
    d.domain = "stock"
    return d


@pytest.mark.asyncio
async def test_flag_off_uses_llm_path(monkeypatch):
    """flag off 일 때 synthesize_info_lookup_plan 호출 X, LLM 경로 사용."""
    monkeypatch.delenv("FEATURE_FAST_INFO_LOOKUP_PLAN", raising=False)

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=(
            '{"plan": [], "needs_clarification": false, '
            '"confidence": 0.9, "ambiguity_reasons": [], "summary": "llm_path"}'
        )
    )
    orch = PlanOrchestrator(llm_client=llm)

    with (
        patch(
            "src.agent_framework.runtime.plan_orchestrator.is_enabled",
            return_value=False,
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("info_lookup"),
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route",
            return_value=_make_decision("info_lookup"),
        ),
        patch(
            "src.agent_framework.runtime.fast_planners.info_lookup.synthesize_info_lookup_plan"
        ) as mock_synth,
    ):
        result = await orch.generate_plan(
            user_message="주식 매도 대금 입금일",
            utterance_verb="info",
            utterance_domain="stock",
        )

    # synthesize_info_lookup_plan 은 호출되지 않아야 함.
    mock_synth.assert_not_called()
    # LLM 은 호출됨.
    llm.complete.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_flag_on_info_lookup_uses_fast_planner(monkeypatch):
    """flag on + intent=info_lookup → fast_planner 사용, LLM 호출 0."""
    monkeypatch.setenv("FEATURE_FAST_INFO_LOOKUP_PLAN", "true")

    llm = MagicMock()
    llm.complete = AsyncMock(return_value="should not be called")
    orch = PlanOrchestrator(llm_client=llm)

    with (
        patch(
            "src.agent_framework.runtime.plan_orchestrator.is_enabled",
            return_value=True,
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("info_lookup"),
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route",
            return_value=_make_decision("info_lookup"),
        ),
    ):
        result = await orch.generate_plan(
            user_message="주식 매도 대금 입금일",
            utterance_verb="info",
            utterance_domain="stock",
            tenant_id="test-tenant",
        )

    # LLM 은 호출되지 않아야 함.
    llm.complete.assert_not_called()
    assert result is not None
    assert result.summary == "fast_info_lookup_planner (LLM bypass)"
    assert result.confidence == 0.95
    assert result.needs_clarification is False
    # 결정론 plan: kms_rag.search / web.search / reasoning
    kinds = [s.kind for s in result.plan]
    assert "tool" in kinds
    assert "reasoning" in kinds
    tool_names = [s.raw.get("tool") for s in result.plan if s.kind == "tool"]
    assert "kms_rag.search" in tool_names


@pytest.mark.asyncio
async def test_flag_on_other_category_uses_llm_path(monkeypatch):
    """flag on + category=schedule → fast_planner 미사용, LLM 경로."""
    monkeypatch.setenv("FEATURE_FAST_INFO_LOOKUP_PLAN", "true")

    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=(
            '{"plan": [], "needs_clarification": false, '
            '"confidence": 0.8, "ambiguity_reasons": [], "summary": "schedule_llm"}'
        )
    )
    orch = PlanOrchestrator(llm_client=llm)

    # is_enabled 은 true 지만 category 가 schedule 이어서 fast_path 우회.
    with (
        patch(
            "src.agent_framework.runtime.plan_orchestrator.is_enabled",
            return_value=True,
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("schedule"),
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route",
            return_value=_make_decision("schedule"),
        ),
    ):
        result = await orch.generate_plan(
            user_message="오늘 일정 알려줘",
            utterance_verb="info",
            utterance_domain="schedule",
            tenant_id="test-tenant",
        )

    # LLM 은 호출됨 (schedule 은 fast_path 대상 아님).
    llm.complete.assert_called_once()
    assert result is not None
    assert result.summary != "fast_info_lookup_planner (LLM bypass)"
