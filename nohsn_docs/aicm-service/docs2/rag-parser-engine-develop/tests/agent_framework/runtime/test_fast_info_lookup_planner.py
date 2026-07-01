import pytest
from src.agent_framework.runtime.fast_planners.info_lookup import (
    synthesize_info_lookup_plan,
    IntentResult,
)


CASES = [
    ("주식 매도 대금 입금일", "info_lookup", "stock"),
    ("회사 휴가 규정 알려줘", "info_lookup", "policy"),
    ("출장비 정산 방법", "info_lookup", "expense"),
    ("프린터 사용법", "info_lookup", "general"),
    ("계약서 작성 가이드", "info_lookup", "policy"),
]


@pytest.mark.parametrize("user_msg,intent,domain", CASES)
def test_synth_plan_kms_first(user_msg, intent, domain):
    cls = IntentResult(intent=intent, domain=domain, confidence=0.9)
    plan = synthesize_info_lookup_plan(user_msg, cls)

    # KMS-first 정책: step 1 은 kms_rag.search
    assert plan[0].kind == "tool"
    assert plan[0].tool == "kms_rag.search"
    # 마지막 step 은 reasoning (최종 합성)
    assert plan[-1].kind == "reasoning"
    # plan 길이는 ≤ 3 (kms / web / reasoning)
    assert 2 <= len(plan) <= 3


def test_no_duplicate_signatures():
    cls = IntentResult(intent="info_lookup", domain="stock", confidence=0.9)
    plan = synthesize_info_lookup_plan("주식 매도 대금 입금일", cls)
    sigs = [(s.tool, str(s.args)) for s in plan if s.kind == "tool"]
    assert len(sigs) == len(set(sigs))


def test_schema_fields_present():
    cls = IntentResult(intent="info_lookup", domain="stock", confidence=0.9)
    plan = synthesize_info_lookup_plan("주식 매도", cls)
    for step in plan:
        assert step.kind in ("tool", "reasoning", "ask_user_clarify")
        if step.kind == "tool":
            assert step.tool is not None
            assert isinstance(step.args, dict)


def test_include_web_false():
    """include_web=False 이면 web.search step 제외."""
    cls = IntentResult(intent="info_lookup", domain="stock", confidence=0.9)
    plan = synthesize_info_lookup_plan("주식 매도", cls, include_web=False)
    tools = [s.tool for s in plan if s.kind == "tool"]
    assert "kms_rag.search" in tools
    assert "web.search" not in tools
    assert len(plan) == 2  # kms + reasoning


def test_user_message_passes_through_as_query():
    """별도 query rewrite 없이 user_message 가 그대로 query 로."""
    cls = IntentResult(intent="info_lookup", domain="stock", confidence=0.9)
    plan = synthesize_info_lookup_plan("주식 매도 대금 입금일", cls)
    assert plan[0].args["query"] == "주식 매도 대금 입금일"
