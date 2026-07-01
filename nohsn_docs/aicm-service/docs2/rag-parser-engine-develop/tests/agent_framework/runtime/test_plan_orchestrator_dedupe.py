"""PLAN_DEDUPE flag 분기 검증 — plan_orchestrator Stage 3.

flag off  → dedupe_plan 호출 없음, plan 길이 변화 없음.
flag on + 중복 plan → dedupe 적용, 중복 step 제거.
flag on + 중복 없는 plan → result 그대로 (재할당 X).
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent_framework.runtime.plan_orchestrator import GeneratedPlan, PlanOrchestrator


def _make_decision(category: str = "info_lookup"):
    d = MagicMock()
    d.category = category
    d.reason = "test"
    d.matched_intent = "info_lookup"
    d.needs_llm_disambiguation = False
    d.verb = "info"
    d.domain = "general"
    return d


def _llm_response(steps: list[dict]) -> str:
    return json.dumps(
        {
            "plan": steps,
            "needs_clarification": False,
            "confidence": 0.9,
            "ambiguity_reasons": [],
            "summary": "test_plan",
        },
        ensure_ascii=False,
    )


# 6-step plan: kms x2 + web x2 + reasoning x2 (Trace A 형태)
_REDUNDANT_STEPS = [
    {"step": 1, "kind": "tool", "tool": "kms_rag.search", "args": {"query": "주식 매도 대금"}},
    {"step": 2, "kind": "tool", "tool": "web.search", "args": {"query": "주식 매도 대금"}},
    {"step": 3, "kind": "reasoning", "expr": "step1 결과 정리"},
    {"step": 4, "kind": "tool", "tool": "kms_rag.search", "args": {"query": "주식 매도 대금"}},  # dup of 1
    {"step": 5, "kind": "tool", "tool": "web.search", "args": {"query": "주식 매도 대금"}},    # dup of 2
    {"step": 6, "kind": "reasoning", "expr": "step1 결과 정리"},                               # reasoning — kept
]

# 3-step plan: 모두 unique
_UNIQUE_STEPS = [
    {"step": 1, "kind": "tool", "tool": "kms_rag.search", "args": {"query": "주식"}},
    {"step": 2, "kind": "tool", "tool": "web.search", "args": {"query": "배당"}},
    {"step": 3, "kind": "reasoning", "expr": "종합"},
]


def _make_orch_with_llm(steps: list[dict]) -> tuple[PlanOrchestrator, MagicMock]:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=_llm_response(steps))
    orch = PlanOrchestrator(llm_client=llm)
    return orch, llm


def _common_patches(is_enabled_returns):
    """공통 patch context — router + is_enabled."""
    return [
        patch(
            "src.agent_framework.runtime.plan_orchestrator.is_enabled",
            side_effect=is_enabled_returns,
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route_by_verb_domain",
            return_value=_make_decision("info_lookup"),
        ),
        patch(
            "src.agent_framework.runtime.plan_router.route",
            return_value=_make_decision("info_lookup"),
        ),
    ]


# ---------------------------------------------------------------------------
# Test 1 — flag off: plan 길이 변화 없음, dedupe_plan 미호출
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_off_no_dedupe(monkeypatch):
    """flag off 시 dedupe_plan 호출 없음, 원본 plan 길이(6) 그대로."""
    monkeypatch.delenv("FEATURE_PLAN_DEDUPE", raising=False)

    orch, llm = _make_orch_with_llm(_REDUNDANT_STEPS)

    # is_enabled 은 항상 False (flag off)
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
            "src.agent_framework.runtime.plan_postprocess.plan_dedupe.dedupe_plan"
        ) as mock_dedupe,
    ):
        result = await orch.generate_plan(
            user_message="주식 매도 대금 입금일",
            utterance_verb="info",
            utterance_domain="general",
        )

    assert result is not None
    # dedupe_plan 은 호출되어서는 안 됨.
    mock_dedupe.assert_not_called()
    # plan 길이는 LLM 반환 그대로 (6 step — invalid tool filter 통과한 것들).
    assert len(result.plan) == 6


# ---------------------------------------------------------------------------
# Test 2 — flag on + redundant plan: dedupe 적용, plan 짧아짐
# ---------------------------------------------------------------------------

def _is_enabled_dedupe_only(flag, *, tenant_id=None):
    """PLAN_DEDUPE=True, FAST_INFO_LOOKUP_PLAN=False — fast path 우회."""
    from src.common.feature_flags import FeatureFlag
    return flag == FeatureFlag.PLAN_DEDUPE


@pytest.mark.asyncio
async def test_flag_on_dedupes_redundant_steps(monkeypatch):
    """flag on + 중복 tool step → dedupe 후 plan 길이 감소."""
    monkeypatch.setenv("FEATURE_PLAN_DEDUPE", "true")

    orch, llm = _make_orch_with_llm(_REDUNDANT_STEPS)

    # PLAN_DEDUPE=True, FAST_INFO_LOOKUP_PLAN=False (fast path 우회하여 LLM 경로 사용).
    with (
        patch(
            "src.agent_framework.runtime.plan_orchestrator.is_enabled",
            side_effect=_is_enabled_dedupe_only,
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
            utterance_domain="general",
            tenant_id="test-tenant",
        )

    assert result is not None
    # 6 step 에서 tool dup 2개 제거 → 4 step (kms x1, web x1, reasoning x2).
    # reasoning 은 unique: signature 이므로 보존.
    assert len(result.plan) < 6, f"expected dedupe, got {len(result.plan)} steps"
    # 남은 tool step 의 tool 명 중복 없어야 함.
    tool_names = [s.raw.get("tool") for s in result.plan if s.kind == "tool"]
    assert len(tool_names) == len(set(tool_names)), f"duplicate tools remain: {tool_names}"
    # reasoning 은 2개 모두 보존 (unique: prefix — dedupe 대상 아님).
    reasoning_count = sum(1 for s in result.plan if s.kind == "reasoning")
    assert reasoning_count == 2


# ---------------------------------------------------------------------------
# Test 3 — flag on + unique plan: result 그대로
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_no_change_when_unique(monkeypatch):
    """flag on + 중복 없는 3-step plan → plan 길이 변화 없음."""
    monkeypatch.setenv("FEATURE_PLAN_DEDUPE", "true")

    orch, llm = _make_orch_with_llm(_UNIQUE_STEPS)

    with (
        patch(
            "src.agent_framework.runtime.plan_orchestrator.is_enabled",
            side_effect=_is_enabled_dedupe_only,
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
            user_message="주식 배당금 정보",
            utterance_verb="info",
            utterance_domain="general",
            tenant_id="test-tenant",
        )

    assert result is not None
    # unique plan → 길이 그대로.
    assert len(result.plan) == 3
    # 각 step 의 kind 순서 보존.
    kinds = [s.kind for s in result.plan]
    assert kinds == ["tool", "tool", "reasoning"]
