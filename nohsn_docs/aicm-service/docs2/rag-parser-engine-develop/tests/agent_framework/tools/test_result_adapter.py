"""Phase 1.5A D73 — result_adapter contract 테스트.

목적: legacy dict ↔ ToolResult dataclass *왕복 호환* 보장 +
adversarial_checker 가 의존하는 key (confirm_id / op_type / success / ...)
가 to_legacy_dict 출력에 보존.
"""
import pytest

from src.agent_framework.runtime.adversarial_checker import (
    _has_state_change_evidence,
)
from src.agent_framework.tools.outcomes import (
    OutcomeKind,
    ToolOutcome,
    ToolResult,
    ToolResultMeta,
)
from src.agent_framework.tools.result_adapter import (
    ensure_result_shape,
    to_legacy_dict,
    to_tool_result,
)


# ---------------------------------------------------------------------------
# to_tool_result — legacy dict → ToolResult
# ---------------------------------------------------------------------------


def test_to_tool_result_simple_success() -> None:
    """간단한 read 도구 — success=True / items 있음."""
    legacy = {"success": True, "items": [{"id": "x"}], "summary": "OK"}
    res = to_tool_result(legacy)
    assert res.success is True
    assert res.items == [{"id": "x"}]
    assert res.summary == "OK"
    assert res.meta.outcome == ToolOutcome.OK


def test_to_tool_result_empty_total_zero() -> None:
    """total=0 + success=True → outcome=EMPTY (도메인 empty)."""
    legacy = {"success": True, "total": 0, "items": []}
    res = to_tool_result(legacy)
    assert res.success is True
    assert res.meta.outcome == ToolOutcome.EMPTY
    assert res.meta.kind == OutcomeKind.DOMAIN_EMPTY.value


def test_to_tool_result_conflict() -> None:
    """duplicate=True → outcome=DUPLICATE."""
    legacy = {"success": True, "duplicate": True, "summary": "이미 등록"}
    res = to_tool_result(legacy)
    assert res.meta.outcome == ToolOutcome.DUPLICATE
    assert res.meta.kind == OutcomeKind.DOMAIN_CONFLICT.value


def test_to_tool_result_external_failure() -> None:
    """success=False + timeout error → EXTERNAL_API_FAIL + retryable=True."""
    legacy = {"success": False, "error": "request timeout"}
    res = to_tool_result(legacy)
    assert res.success is False
    assert res.meta.outcome == ToolOutcome.TIMEOUT
    assert res.meta.retryable is True


def test_to_tool_result_permission_denied() -> None:
    legacy = {"success": False, "error": "permission denied for tool"}
    res = to_tool_result(legacy)
    assert res.meta.outcome == ToolOutcome.PERMISSION_DENIED
    assert res.meta.kind == OutcomeKind.POLICY.value
    assert res.meta.user_action_required is True


def test_to_tool_result_none_input() -> None:
    """None → success=False / EXTERNAL_API_FAIL."""
    res = to_tool_result(None)
    assert res.success is False
    assert res.meta.outcome == ToolOutcome.EXTERNAL_API_FAIL


def test_to_tool_result_explicit_outcome_preserved() -> None:
    """legacy["meta"]["outcome"] 명시 시 그대로 매핑."""
    legacy = {
        "success": True,
        "meta": {
            "outcome": "saturated",
            "reason": "all_slots_booked",
            "kind": OutcomeKind.DOMAIN_EMPTY.value,
        },
    }
    res = to_tool_result(legacy)
    assert res.meta.outcome == ToolOutcome.SATURATED
    assert res.meta.reason == "all_slots_booked"


# ---------------------------------------------------------------------------
# to_legacy_dict — ToolResult → legacy dict (adversarial_checker 호환)
# ---------------------------------------------------------------------------


def test_to_legacy_dict_preserves_meta_outcome_string() -> None:
    """ToolResult.meta.outcome → legacy["meta"]["outcome"] = str."""
    res = ToolResult(
        success=True,
        summary="ok",
        meta=ToolResultMeta(
            outcome=ToolOutcome.OK,
            reason="",
            kind=OutcomeKind.DOMAIN_EMPTY.value,
        ),
    )
    legacy = to_legacy_dict(res)
    assert legacy["success"] is True
    assert legacy["meta"]["outcome"] == "ok"


def test_roundtrip_dict_to_result_to_dict() -> None:
    """legacy → ToolResult → legacy 왕복 시 success / outcome / summary 보존."""
    original = {
        "success": True,
        "items": [{"id": "a"}, {"id": "b"}],
        "summary": "2건 발견",
    }
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    assert back["success"] == original["success"]
    assert back["items"] == original["items"]
    assert back["summary"] == original["summary"]
    assert back["meta"]["outcome"] == "ok"


# ---------------------------------------------------------------------------
# adversarial_checker 호환성 — confirm_id / op_type / success 의 evidence 인식
# ---------------------------------------------------------------------------


def test_adversarial_checker_recognizes_confirm_id_via_adapter() -> None:
    """ToolResult 가 confirm_id 를 *내포* 한 legacy dict 와 함께 사용 시
    adversarial_checker.is_state_change_evidence 가 동일하게 인식."""
    # 실제 prod 경로에서는 confirm_id 가 tool 별 dict 에 들어감 — adapter 변환 후에도
    # adversarial_checker 가 confirm_id 를 못 보면 false-confirm 차단 회귀.
    legacy_with_confirm = {
        "success": True,
        "confirm_id": "inv_abc123",
        "op_type": "create",
        "summary": "지출 등록 완료",
    }
    tool_results = [{"tool": "expense.create", "result": legacy_with_confirm}]
    assert _has_state_change_evidence(tool_results) is True


def test_adversarial_checker_no_evidence_after_adapter_roundtrip() -> None:
    """read 도구 결과 — confirm_id 없으면 evidence X (false-confirm 차단 가능)."""
    legacy_read = {"success": True, "items": [{"id": "x"}], "total": 1}
    tool_results = [{"tool": "expense.list", "result": legacy_read}]
    assert _has_state_change_evidence(tool_results) is False


# ---------------------------------------------------------------------------
# ensure_result_shape — contract 검증 (테스트 전용 helper)
# ---------------------------------------------------------------------------


def test_ensure_result_shape_valid() -> None:
    valid, errors = ensure_result_shape({"success": True, "items": []})
    assert valid is True
    assert errors == []


def test_ensure_result_shape_missing_success() -> None:
    valid, errors = ensure_result_shape({"items": []})
    assert valid is False
    assert "missing_success" in errors


def test_ensure_result_shape_state_change_without_evidence() -> None:
    """op_type=create + success=True 인데 confirm_id/evidence_id 미존재 → 결함."""
    valid, errors = ensure_result_shape(
        {"success": True, "op_type": "create"}
    )
    assert valid is False
    assert "state_change_without_evidence" in errors


def test_ensure_result_shape_state_change_with_evidence() -> None:
    valid, errors = ensure_result_shape(
        {"success": True, "op_type": "create", "confirm_id": "inv_x"}
    )
    assert valid is True


def test_ensure_result_shape_not_dict() -> None:
    valid, errors = ensure_result_shape(None)  # type: ignore[arg-type]
    assert valid is False


# ---------------------------------------------------------------------------
# GPT-5 사후 권고 — adv-checker 키 왕복 무손실 보존 (HIGH severity)
# ---------------------------------------------------------------------------


def test_roundtrip_preserves_confirm_id_and_op_type() -> None:
    """legacy → ToolResult → legacy 왕복 시 confirm_id / op_type 보존 (adv-checker 의존).

    GPT-5 사후 권고 (2026-05-12) — 초기 구현이 이 키들을 *드롭* 해서
    adversarial_checker 가 evidence 미인식 → false-confirm 차단 우회 가능했음.
    """
    original = {
        "success": True,
        "confirm_id": "inv_abc123",
        "op_type": "create",
        "summary": "지출 등록 완료",
    }
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    assert back["confirm_id"] == "inv_abc123"
    assert back["op_type"] == "create"
    assert back["success"] is True


def test_roundtrip_preserves_evidence_id() -> None:
    original = {"success": True, "evidence_id": "evt_xyz", "op_type": "update"}
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    assert back["evidence_id"] == "evt_xyz"
    assert back["op_type"] == "update"


def test_roundtrip_preserves_rows_affected_and_status() -> None:
    original = {"success": True, "status": "ok", "rows_affected": 3}
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    assert back["status"] == "ok"
    assert back["rows_affected"] == 3


def test_roundtrip_no_ok_auto_mirror_for_read() -> None:
    """legacy 에 ok 없으면 왕복 후에도 ok 부재 (자동 미러 X).

    GPT-5 사후 권고 초기안은 success→ok 자동 미러였으나, adversarial_checker 가
    result.get("ok") is True 단독으로 state-change evidence True 판단 → read 도구가
    false-positive evidence 갖게 됨. ok 미러 제거 (적용 안 됨).
    """
    original = {"success": True}  # read 도구 — ok 없음
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    assert "ok" not in back
    assert back["success"] is True


def test_roundtrip_preserves_ok_when_present() -> None:
    """legacy 에 ok 가 *명시* 됐으면 왕복 후에도 보존 (state-change 도구 evidence)."""
    original = {"success": True, "ok": True, "op_type": "create"}
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    assert back.get("ok") is True
    assert back.get("op_type") == "create"


def test_adversarial_checker_sees_evidence_after_roundtrip() -> None:
    """ToolResult 왕복 후 adversarial_checker 가 *동일하게* evidence 인식."""
    original = {
        "success": True,
        "confirm_id": "inv_evidence_001",
        "op_type": "create",
    }
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    tool_results = [{"tool": "expense.create", "result": back}]
    assert _has_state_change_evidence(tool_results) is True


def test_adversarial_checker_no_false_evidence_for_read_after_roundtrip() -> None:
    """read 도구 (confirm_id 없음) → 왕복 후에도 evidence X."""
    original = {"success": True, "items": [{"id": "x"}], "total": 1}
    res = to_tool_result(original)
    back = to_legacy_dict(res)
    tool_results = [{"tool": "expense.list", "result": back}]
    # adversarial_checker 가 success=True + ok=True 만 보고 evidence True 하면 안 됨.
    # op_type 없으니 read — 단 .list 가 .create/.update/.delete/.send 어간 아님 → False.
    assert _has_state_change_evidence(tool_results) is False


# ---------------------------------------------------------------------------
# GPT-5 사후 권고 — OK kind 매핑 수정 (DOMAIN_EMPTY → success)
# ---------------------------------------------------------------------------


def test_ok_outcome_kind_is_success_not_domain_empty() -> None:
    """OK outcome 의 kind 가 'success' (이전 fallback=DOMAIN_EMPTY 결함 수정)."""
    legacy = {"success": True, "items": [{"id": "x"}], "summary": "OK"}
    res = to_tool_result(legacy)
    assert res.meta.outcome == ToolOutcome.OK
    assert res.meta.kind == "success"
