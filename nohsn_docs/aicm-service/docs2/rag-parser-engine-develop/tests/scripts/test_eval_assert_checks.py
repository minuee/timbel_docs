import pytest
from scripts.eval.latency.assert_checks import (
    check_schema,
    check_duplicate_signatures,
    check_intent_skill_conflict,
    check_slot_completeness,
)


VALID_TRACE = {
    "id": "schedule__simple",
    "user_message": "내일 6시 약속",
    "expected_intent": "schedule_personal",
    "phases": [
        {"name": "intent_classifier", "wall_ms": 1960, "meta": {}},
        {"name": "plan_generator", "wall_ms": 6540,
         "meta": {"prompt_tokens": 8000, "cached_tokens": 0}},
    ],
    "plan": [
        {"step": 1, "kind": "tool", "tool": "schedule.create",
         "args": {"title": "약속", "when": "2026-05-07T18:00"}},
    ],
    "executed_tools": ["schedule.create"],
    "user_expected_tool": "schedule.create",
}


def test_schema_valid():
    errs = check_schema(VALID_TRACE)
    assert errs == []


def test_schema_missing_phases():
    bad = dict(VALID_TRACE)
    del bad["phases"]
    errs = check_schema(bad)
    assert any("phases" in e for e in errs)


def test_dupe_count_zero_for_unique_signatures():
    n = check_duplicate_signatures(VALID_TRACE["plan"])
    assert n == 0


def test_dupe_count_for_repeated_kms_search():
    plan = [
        {"step": 1, "kind": "tool", "tool": "kms_rag.search",
         "args": {"query": "주식 매도 대금"}},
        {"step": 2, "kind": "tool", "tool": "kms_rag.search",
         "args": {"query": "주식 매도 대금"}},
    ]
    assert check_duplicate_signatures(plan) == 1


def test_intent_skill_conflict_detected():
    """Trace C 의 핵심 검증."""
    trace_c = {
        "id": "internal-mismatch__memo-vs-schedule",
        "expected_intent": "memo_capture",
        "actual_skill_v2_at_capture": "schedule_personal",
        "executed_tool_at_capture": "schedule.create",
        "user_expected_tool": "memo.save",
    }
    conflict = check_intent_skill_conflict(trace_c)
    assert conflict is True


def test_no_conflict_when_aligned():
    aligned = {
        "id": "schedule__simple",
        "expected_intent": "schedule_personal",
        "actual_skill_v2_at_capture": "schedule_personal",
        "executed_tool_at_capture": "schedule.create",
        "user_expected_tool": "schedule.create",
    }
    assert check_intent_skill_conflict(aligned) is False


def test_slot_completeness_no_expected():
    """expected_clarify 미설정 — 항상 True."""
    assert check_slot_completeness({"id": "x"}, [
        {"kind": "tool", "tool": "kms_rag.search", "args": {}},
    ]) is True


def test_slot_completeness_clarify_present():
    """expected_clarify 있고 plan 에 ask_user_clarify 있음 — True."""
    trace = {"id": "x", "expected_clarify": ["환자명"]}
    plan = [
        {"kind": "ask_user_clarify", "tool": None, "args": {}},
        {"kind": "tool", "tool": "schedule.create", "args": {}},
    ]
    assert check_slot_completeness(trace, plan) is True


def test_slot_completeness_clarify_missing():
    """expected_clarify 있는데 plan 에 ask_user_clarify 없음 — False."""
    trace = {"id": "x", "expected_clarify": ["환자명"]}
    plan = [{"kind": "tool", "tool": "schedule.create", "args": {}}]
    assert check_slot_completeness(trace, plan) is False
