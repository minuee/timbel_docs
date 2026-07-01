import pytest
from src.agent_framework.tools.outcomes import (
    ToolOutcome, ToolResult, ToolResultMeta,
)


def test_outcome_enum_values():
    """필수 outcome 28+ 값 모두 정의."""
    expected = {
        "ok", "empty", "partial", "duplicate", "conflict",
        "not_found", "too_many_matches", "ambiguous_target",
        "invalid_input", "missing_required_slot",
        "past_time", "too_far_future",
        "permission_denied", "auth_required", "not_owner",
        "quota_exceeded", "rate_limited", "cooldown",
        "timeout", "external_api_fail", "backend_unavailable",
        "low_confidence", "policy_blocked", "unsafe_needs_confirm",
        "saturated", "outside_working_hours", "unknown_resource",
        "sop_missing", "sop_stale", "unsupported",
    }
    actual = {e.value for e in ToolOutcome}
    missing = expected - actual
    assert not missing, f"missing outcomes: {missing}"


def test_tool_result_success_with_empty_outcome():
    """empty 는 실행 성공 + 도메인 결과 — success=True."""
    result = ToolResult(
        success=True,
        items=[],
        summary="결과 없음",
        meta=ToolResultMeta(
            outcome=ToolOutcome.EMPTY,
            reason="no_records",
            kind="domain_empty",
            retryable=False,
            user_action_required=True,
        ),
    )
    assert result.success is True
    assert result.meta.outcome == ToolOutcome.EMPTY
    assert result.meta.kind == "domain_empty"


def test_tool_result_failure_with_external_api():
    """외부 API 실패 — success=False."""
    result = ToolResult(
        success=False,
        error="smtp connection refused",
        error_ref="log-abc123",
        meta=ToolResultMeta(
            outcome=ToolOutcome.EXTERNAL_API_FAIL,
            reason="smtp_fail",
            kind="external_dependency",
            retryable=True,
        ),
    )
    assert result.success is False
    assert result.meta.retryable is True


def test_tool_result_alternatives_for_conflict():
    """conflict 시 alternatives 에 대안 포함."""
    result = ToolResult(
        success=True,
        meta=ToolResultMeta(
            outcome=ToolOutcome.CONFLICT,
            reason="schedule_overlap",
            kind="domain_conflict",
            alternatives=[{"start": "14:00", "end": "15:00"}, {"start": "16:00", "end": "17:00"}],
        ),
    )
    assert len(result.meta.alternatives) == 2


def test_tool_result_to_dict_serializable():
    """SSE / JSON 송출 가능."""
    import json
    result = ToolResult(
        success=True,
        summary="ok",
        meta=ToolResultMeta(outcome=ToolOutcome.OK, reason="", kind="domain_empty"),
    )
    serialized = result.to_dict()
    json.dumps(serialized)  # raise X 면 OK


def test_outcome_classification_kinds():
    """kind 분류 5개 enum 또는 literal."""
    from src.agent_framework.tools.outcomes import OutcomeKind
    expected_kinds = {"domain_empty", "domain_conflict", "policy", "external_dependency", "validation"}
    assert {k.value if hasattr(k, 'value') else k for k in OutcomeKind} == expected_kinds
