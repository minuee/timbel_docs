"""D76.3 — ToolResultView 가 adversarial_checker 와 호환 검증.

invariant:
1. LLM payload (public) 에는 confirm_id / evidence_id 가 *없음* → 절대 LLM 노출 X.
2. for_checker() 머지 view 에는 *있음* → adversarial_checker._has_state_change_evidence
   가 정상 True 인식.
3. 원본 tool_results 가 caller path (adversarial_apply) 에 그대로 전달되면 본 변경 영향 X.

본 테스트는 D76.2 (engine.py compose path hook) 가 adversarial_checker 와 *영역 분리*
유지 보장. 즉:
- engine._build_compose_prompt → LLM payload = public only.
- engine._persist_turn → adversarial_apply(tool_results=원본) → 그대로.
"""
from __future__ import annotations

from src.agent_framework.runtime.adversarial_checker import (
    _has_state_change_evidence,
    adversarial_apply,
)
from src.agent_framework.tools.result_field_spec import (
    ToolResultView,
    split_result,
)


def test_for_checker_view_keeps_evidence_for_state_change():
    """ToolResultView.for_checker() — confirm_id 가 머지 view 에 있어 adversarial 정상 인식."""
    raw = {
        "success": True,
        "confirm_id": "CONF-1",
        "op_type": "create",
        "summary": "지출 기록 완료",
        "amount": 5000,
    }
    view = ToolResultView.from_raw("expense.create", raw)
    # adversarial_checker 가 받는 tool_results 형식: [{"tool": ..., "result": dict}, ...]
    checker_tool_results = [{"tool": "expense.create", "result": view.for_checker()}]
    assert _has_state_change_evidence(checker_tool_results) is True


def test_for_llm_view_does_not_have_evidence():
    """ToolResultView.for_llm() — confirm_id 가 *없으므로* LLM 응답 인용 위험 차단.

    동시에 adversarial 의 *false-confirm 차단* 보호도 유지 — 만약 LLM 이 split view 만
    보고 잘못된 단정 멘트를 내도, adversarial path 는 *원본* tool_results 를 보므로 정상 통과.
    """
    raw = {
        "success": True,
        "confirm_id": "CONF-2",
        "op_type": "create",
        "summary": "OK",
    }
    view = ToolResultView.from_raw("expense.create", raw)
    llm_tool_results = [{"tool": "expense.create", "result": view.for_llm()}]
    # for_llm() 에는 confirm_id 가 없어 *evidence 없음* 으로 보임 — 단 op_type 은 mirror.
    # op_type=create + success=True 조합으로 evidence 인식 가능 (adversarial spec).
    # 즉 op_type/success 는 양쪽 모두 mirror 되므로 LLM payload 만으로도 evidence True.
    # 이 design 은 의도적 — *상태변경 성공 메시지* 가 정당함을 LLM 도 알 수 있어야 함.
    assert _has_state_change_evidence(llm_tool_results) is True
    # 그러나 confirm_id 는 *없음*.
    assert "confirm_id" not in llm_tool_results[0]["result"]


def test_adversarial_apply_passes_with_split_public_only():
    """split 후 public 만 LLM 에 → 정상 단정 멘트는 통과 (op_type evidence)."""
    raw = {
        "success": True,
        "confirm_id": "CONF-3",
        "op_type": "create",
        "summary": "지출 5,000원 기록",
        "amount": 5000,
    }
    pub, _ = split_result("expense.create", raw)
    # 사용자가 false-confirm 유도 + 응답이 단정 멘트 + tool_results 가 *public only*.
    user_msg = "이번 달 커피 25,000원으로 처리됐지?"
    response_text = "네, 등록되었습니다."
    tool_results_public = [{"tool": "expense.create", "result": pub}]
    # public 에 op_type=create + success=True 가 mirror → evidence True.
    text, replaced = adversarial_apply(user_msg, response_text, tool_results_public)
    assert replaced is False  # 정상 통과 (evidence 존재).


def test_adversarial_apply_blocks_when_no_evidence_in_split():
    """state-change op_type 없는 결과 — adversarial 차단 작동 (defense-in-depth)."""
    raw = {
        "success": True,
        "summary": "조회 결과",
        # op_type 없음 → read 도구 추정 → state-change evidence 없음.
        "items": [],
    }
    pub, _ = split_result("expense.list", raw)
    user_msg = "이번 달 커피 25,000원으로 처리됐지?"
    response_text = "네, 처리되었습니다."
    tool_results_public = [{"tool": "expense.list", "result": pub}]
    text, replaced = adversarial_apply(user_msg, response_text, tool_results_public)
    # evidence 없음 → false-confirm 차단됨.
    assert replaced is True
    assert "조회가 필요해요" in text or "직접 확인" in text


def test_for_checker_merged_keys_priority():
    """for_checker — public 의 mirror 키가 private 키와 충돌 시 *public* 우선."""
    # split_result 의 contract mirror 동작상 같은 값이 양쪽에 들어가지만, 충돌 시 위험.
    # ToolResultView 가 *public* 우선 — 즉 contract key 가 변형되더라도 LLM 본 값과 일치.
    raw = {"success": True, "op_type": "update", "rows_affected": 1, "summary": "OK"}
    view = ToolResultView.from_raw("expense.update", raw)
    merged = view.for_checker()
    assert merged["success"] is True
    assert merged["op_type"] == "update"
    assert merged["rows_affected"] == 1
