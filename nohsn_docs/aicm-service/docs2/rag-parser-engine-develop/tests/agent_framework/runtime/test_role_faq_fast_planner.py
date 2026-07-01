"""role_faq fast-planner 단위 테스트 (2026-05-07).

진단:
- 5 role agent 중복 처리 진단 → fast-track synthesizer 검증
- intent / utterance / plan_orchestrator LLM 3 회 skip 진입 조건 회귀 0
- include_sop=False 분기 (단일 도구 agent) 호환

Doc: ``Doc/research/2026-05-07-role-agent-redundancy-fast-track.md``
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agent_framework.runtime.fast_planners.role_faq import (
    is_role_fast_trackable,
    synthesize_role_faq_plan,
    ALLOWED_FAST_TRACK_TOOLS,
)


@dataclass
class _StubAgentContext:
    """AgentContext 의 필요한 attribute 만 가진 stub.

    실제 AgentContext 는 frozen + UUID id 가 필요해 fixture 비용이 큼.
    fast-track 진입 검사는 ``is_admin`` / ``kind`` / ``allowed_tools`` 만 본다.
    """
    is_admin: bool = False
    kind: str = "role"
    allowed_tools: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.allowed_tools is None:
            self.allowed_tools = []


# ============================================================
# is_role_fast_trackable 진입 조건
# ============================================================


def test_trackable_with_kms_rag_and_sop():
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    assert is_role_fast_trackable(ctx) is True


def test_trackable_with_kms_rag_only():
    """SOP 없이 kms_rag.search 만 있어도 trackable."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search"])
    assert is_role_fast_trackable(ctx) is True


def test_trackable_with_kms_sop_only():
    """kms_sop.search 만 있어도 trackable (rare 이지만 확장 호환)."""
    ctx = _StubAgentContext(allowed_tools=["kms_sop.search"])
    assert is_role_fast_trackable(ctx) is True


def test_not_trackable_when_admin():
    """admin agent 는 fast-track 부적합 (전방위 도구)."""
    ctx = _StubAgentContext(
        is_admin=True,
        kind="admin",
        allowed_tools=["kms_rag.search", "kms_sop.search"],
    )
    assert is_role_fast_trackable(ctx) is False


def test_not_trackable_when_external_tool_present():
    """mail.send 등이 추가된 복합 role agent 는 LLM plan 필요 — 진입 거부."""
    ctx = _StubAgentContext(
        allowed_tools=["kms_rag.search", "kms_sop.search", "mail.send"]
    )
    assert is_role_fast_trackable(ctx) is False


def test_not_trackable_when_schedule_tool_present():
    ctx = _StubAgentContext(
        allowed_tools=["kms_rag.search", "schedule.create"]
    )
    assert is_role_fast_trackable(ctx) is False


def test_not_trackable_when_empty_allowed_tools():
    """allowed_tools 비어 있으면 fast-track 적용 X — LLM 으로 자유 plan."""
    ctx = _StubAgentContext(allowed_tools=[])
    assert is_role_fast_trackable(ctx) is False


def test_not_trackable_when_kind_not_role():
    """kind 가 'role' 이 아닐 때 (예: 미래 'specialist' 같은 신규 kind) 안전 거부."""
    ctx = _StubAgentContext(
        kind="specialist",
        allowed_tools=["kms_rag.search", "kms_sop.search"],
    )
    assert is_role_fast_trackable(ctx) is False


def test_not_trackable_when_context_none():
    assert is_role_fast_trackable(None) is False


def test_allowed_set_consistency():
    """``ALLOWED_FAST_TRACK_TOOLS`` 가 hard-coded subset 정의."""
    assert "kms_rag.search" in ALLOWED_FAST_TRACK_TOOLS
    assert "kms_sop.search" in ALLOWED_FAST_TRACK_TOOLS
    # 다른 도구는 들어가면 안 됨 (확장 시 본 테스트 명시 변경 필요).
    assert "web.search" not in ALLOWED_FAST_TRACK_TOOLS
    assert "mail.send" not in ALLOWED_FAST_TRACK_TOOLS


# ============================================================
# synthesize_role_faq_plan plan 합성
# ============================================================


def test_synthesize_with_sop_emits_3_steps():
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    plan = synthesize_role_faq_plan("배달 지연 환불 정책 알려줘", ctx)
    assert len(plan) == 3
    assert plan[0].kind == "tool"
    assert plan[0].tool == "kms_rag.search"
    assert plan[1].kind == "tool"
    assert plan[1].tool == "kms_sop.search"
    assert plan[2].kind == "reasoning"
    assert plan[2].tool is None


def test_synthesize_without_sop_emits_2_steps():
    """allowed_tools 에 kms_sop.search 가 없으면 step 2 자동 omit."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search"])
    plan = synthesize_role_faq_plan("환불 정책", ctx)
    assert len(plan) == 2
    assert plan[0].tool == "kms_rag.search"
    assert plan[1].kind == "reasoning"


def test_synthesize_explicit_include_sop_true():
    """include_sop=True 명시 — agent_context 무관하게 step 2 포함."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search"])  # SOP 미보유
    plan = synthesize_role_faq_plan("환불 정책", ctx, include_sop=True)
    assert len(plan) == 3
    assert plan[1].tool == "kms_sop.search"


def test_synthesize_explicit_include_sop_false():
    """include_sop=False — agent_context 가 SOP 도구 보유해도 omit."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    plan = synthesize_role_faq_plan("환불 정책", ctx, include_sop=False)
    assert len(plan) == 2
    assert plan[0].tool == "kms_rag.search"
    assert plan[1].kind == "reasoning"


def test_synthesize_query_passes_through_user_message():
    """query rewrite 안 함 — user_message 가 그대로 args.query 로."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    msg = "교환은 어떻게 신청하나요?"
    plan = synthesize_role_faq_plan(msg, ctx)
    assert plan[0].args["query"] == msg
    assert plan[1].args["query"] == msg


def test_synthesize_reasoning_expr_present_with_sop():
    """SOP 포함 시 reasoning expr 에 SOP 우선 instruction 있음."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    plan = synthesize_role_faq_plan("환불", ctx)
    expr = plan[2].expr or ""
    assert "SOP" in expr
    assert "[N]" in expr  # citation marker 룰


def test_synthesize_reasoning_expr_present_without_sop():
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search"])
    plan = synthesize_role_faq_plan("환불", ctx)
    expr = plan[1].expr or ""
    assert "[N]" in expr


def test_synthesize_args_dict_for_reasoning_step_is_empty():
    """reasoning step 은 args 가 빈 dict — engine 의 _evaluate_reasoning 호환."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    plan = synthesize_role_faq_plan("환불", ctx)
    assert plan[2].args == {}


# ============================================================
# 회귀 — 동일 입력 동일 출력 (deterministic)
# ============================================================


def test_synthesize_deterministic():
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    p1 = synthesize_role_faq_plan("배달 지연", ctx)
    p2 = synthesize_role_faq_plan("배달 지연", ctx)
    assert [(s.kind, s.tool) for s in p1] == [(s.kind, s.tool) for s in p2]
    assert [s.args for s in p1] == [s.args for s in p2]


# ============================================================
# Edge — 빈 user_message
# ============================================================


def test_synthesize_with_empty_user_message():
    """empty 입력도 schema 유지. caller (engine) 가 진입 전 strip 검사."""
    ctx = _StubAgentContext(allowed_tools=["kms_rag.search", "kms_sop.search"])
    plan = synthesize_role_faq_plan("", ctx)
    assert len(plan) == 3
    assert plan[0].args["query"] == ""


# ============================================================
# Parametrized — 5 봇 발화 샘플 (실제 production 시나리오)
# ============================================================


@pytest.mark.parametrize("user_msg", [
    "배달 지연 환불 정책",         # baemin
    "이 옷 사이즈 어떻게 돼?",     # homeshop / musinsa
    "적금 한도 알려줘",            # kbsoldier
    "산업 통계 정보",              # samchully
    "교환 신청 방법",              # 공통
])
def test_synthesize_real_role_agent_utterances(user_msg):
    """5 role agent production 발화 패턴에서 동형 plan 합성 확인."""
    ctx = _StubAgentContext(
        allowed_tools=["kms_rag.search", "kms_sop.search"],
    )
    plan = synthesize_role_faq_plan(user_msg, ctx)
    tools = [s.tool for s in plan if s.kind == "tool"]
    assert tools == ["kms_rag.search", "kms_sop.search"]
    assert plan[-1].kind == "reasoning"
