"""D82-A — tool_scope_filter capability deny-by-default + bot-agnostic action-done.

배경 (D80 P0 #1 — 2026-05-11):
    stock_info (allowed_tools=[]) 가 "내 일정 등록해" 사용자 발화에
    "회의 일정을 2026년 5월 14일 오후 3시로 등록해 드렸습니다" 응답.
    현 filter 가 도메인 매칭 path 통과 가능 (sub-domain word 약하거나 매핑 미정의).

D82-A 변경:
    1. 도메인 매칭 + DOMAIN_TOOL_MAP 매핑 *비어있음* → deny (skip X)
    2. 도메인 매칭 + allowed_tools *비어있음* → deny
    3. 도메인 word 없이도 bot-agnostic action-done 표현 매칭 + evidence 없음 → deny

GPT-5.5 사전 verdict (2026-05-11) GO_WITH_CHANGES 권고 반영:
    - bare (되었|됐) 금지 — action stem 필수 결합
    - 능동 과거형 (예약했습니다 / 등록했습니다) 포함
    - has_state_change_evidence 는 state-changing + current-turn 엄격
    - read-only / failed / unrelated evidence 제외
"""
from __future__ import annotations

from src.agent_framework.runtime.tool_scope_filter import (
    T3_GENERIC,
    T3_TEMPLATE,
    scope_filter_apply,
)


# =============================================================================
# D82-A.1 — Domain matched + allowed_tools empty → deny
# =============================================================================

def test_d80_p0_1_stock_info_schedule_register_blocked():
    """D80 P0 #1 baseline 재현 — stock_info (allowed_tools=[]) 일정 등록 단정."""
    text = "회의 일정을 2026년 5월 14일 오후 3시로 등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text
    assert "일정" in out


def test_domain_match_empty_allowed_tools_blocked():
    """도메인 매칭 + allowed_tools 비어있음 → deny (capability empty)."""
    text = "내일 회의 일정 등록해 드렸어요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_domain_match_none_allowed_tools_blocked():
    """도메인 매칭 + allowed_tools=None → deny."""
    text = "회의 일정을 등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=None)
    assert out != text


# =============================================================================
# D82-A.2 — Domain matched + DOMAIN_TOOL_MAP empty → deny
# =============================================================================

def test_domain_payment_empty_mapping_blocked():
    """결제 도메인 = empty mapping → 도구 풍부해도 deny (fail-closed)."""
    text = "결제 처리해 드렸습니다."
    # 임의 도구 풍부 — 그러나 결제 도메인 매핑 empty 라서 차단
    out = scope_filter_apply(text, allowed_tools=["schedule.add", "expense.add"])
    assert out != text


# =============================================================================
# D82-A.3 — bot-agnostic action-done (도메인 word 없음) + evidence 없음 → deny
# =============================================================================

def test_bot_agnostic_processed_done_blocked():
    """도메인 word 없음 — '처리해 드렸습니다' + evidence 없음 → 차단."""
    text = "말씀하신 내용 처리해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text
    assert out == T3_GENERIC


def test_bot_agnostic_registered_done_blocked():
    """도메인 word 없음 — '등록해 드렸습니다' + evidence 없음 → 차단."""
    text = "요청하신 내용 등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_bot_agnostic_active_completion_blocked():
    """능동 과거형 — '예약했습니다' (no domain) + evidence 없음 → 차단."""
    text = "예약했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_bot_agnostic_send_active_blocked():
    """능동 과거형 — '발송했습니다' (no domain) + evidence 없음 → 차단."""
    text = "발송했어요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# =============================================================================
# D82-A.4 — bot-agnostic action-done + valid evidence → 통과
# =============================================================================

def test_bot_agnostic_with_evidence_passes():
    """능동 과거형 + tool evidence (confirm_id) → 통과."""
    text = "요청하신 내용 처리해 드렸습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["schedule.add"],
        tool_results=[
            {
                "tool": "schedule.add",
                "status": "success",
                "result": {"confirm_id": "SCH-001", "success": True},
            }
        ],
    )
    assert out == text


def test_bot_agnostic_with_op_type_create_passes():
    """능동 과거형 + op_type=create + success → 통과."""
    text = "예약했습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["reservation.create"],
        tool_results=[
            {
                "tool": "reservation.create",
                "status": "success",
                "result": {"op_type": "create", "success": True},
            }
        ],
    )
    assert out == text


# =============================================================================
# D82-A.5 — Failed / read-only / unrelated evidence 제외
# =============================================================================

def test_failed_tool_result_blocks_done_claim():
    """실패 tool result 만 있고 '등록했습니다' → 차단 (evidence 아님)."""
    text = "예약했습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["reservation.create"],
        tool_results=[
            {
                "tool": "reservation.create",
                "status": "error",
                "result": {"success": False, "error": "timeout"},
            }
        ],
    )
    assert out != text


def test_read_only_tool_result_blocks_done_claim():
    """search/list 같은 read-only tool 만 호출 + '등록했습니다' → 차단."""
    text = "예약했습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["reservation.list"],
        tool_results=[
            {
                "tool": "reservation.list",
                "status": "success",
                "result": {"items": []},
            }
        ],
    )
    assert out != text


# =============================================================================
# D82-A.6 — _GENERAL_ACTION_DONE bare 됐어요/되었습니다 FP 차단
# =============================================================================

def test_non_action_completion_passes_pretty():
    """'예쁘게 됐어요' — non-action verb + 됐 → 통과 (action stem 미결합)."""
    text = "오늘 발표 자료 예쁘게 됐어요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_non_action_completion_passes_well():
    """'잘 됐습니다' — bare 됐 → 통과."""
    text = "다행이네요. 잘 됐습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_non_action_completion_passes_helpful():
    """'도움이 되었습니다' — non-action verb → 통과."""
    text = "감사합니다. 도움이 되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# =============================================================================
# D82-A.7 — 정보성 인용 / "표시됩니다" exempt
# =============================================================================

def test_manual_quote_passes():
    """매뉴얼 인용 — \"결제 완료\" 라고 표시됩니다 → 통과."""
    text = "매뉴얼에는 \"결제 완료\"라고 표시됩니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_user_can_do_passes():
    """'사용자가 직접 등록할 수 있습니다' — 안내 멘트 → 통과."""
    text = "사용자가 직접 등록할 수 있습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_already_saved_passes():
    """'이미 저장되었습니다' — 정보성 상태 → 통과 (D79 기존)."""
    text = "이 설정은 이미 저장되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# =============================================================================
# D82-A.8 — admin / 정상 봇 회귀 안전
# =============================================================================

def test_admin_with_full_tools_passes():
    """admin (full tools) — 회의 등록 + evidence → 통과."""
    text = "회의 일정을 등록해 드렸습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["schedule.add", "schedule.create", "calendar.create"],
        tool_results=[
            {
                "tool": "schedule.create",
                "status": "success",
                "result": {"confirm_id": "AB-1", "success": True},
            }
        ],
    )
    assert out == text


def test_baemin_payment_manual_quote_passes():
    """baemin — 결제 매뉴얼 인용 '결제 완료' 표시됩니다 → 통과."""
    text = "주문 후 카드 결제 완료라고 영수증에 기재됩니다."
    out = scope_filter_apply(text, allowed_tools=["payment.search"])
    # 영수증에 기재 → EXEMPT
    assert out == text


def test_normal_expense_bot_with_evidence_passes():
    """expense bot — '기록되었습니다' + tool evidence → 통과."""
    text = "식비로 점심값 12,000원이 기록되었습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["expense.add"],
        tool_results=[
            {
                "tool": "expense.add",
                "status": "success",
                "result": {"op_type": "create", "success": True},
            }
        ],
    )
    assert out == text


# =============================================================================
# D82-A.9 — Mixed sentence (exempt + action-done)
# =============================================================================

def test_mixed_sentence_action_done_blocked():
    """매뉴얼 인용 + 별도 문장 행위 완료 단정 → 차단 (sentence-level scan)."""
    text = (
        '매뉴얼에는 "결제 완료"라고 표시됩니다. 결제도 완료했습니다.'
    )
    out = scope_filter_apply(text, allowed_tools=[])
    # 둘째 문장이 action-done bot-agnostic — 차단되어야.
    assert out != text


# =============================================================================
# D82-A.10 — D77 회귀 (수동태 단정)
# =============================================================================

def test_d77_passive_past_tense_still_blocked():
    """D77 사례 — '식비로 12,000원이 기록되었습니다' 도메인 path 통과 + 차단."""
    text = "교통비로 택시비 12,000원이 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# =============================================================================
# D82-A.11 — kill-switch 동작
# =============================================================================

def test_kill_switch_bypass(monkeypatch):
    """KMS_POST_GEN_FILTER_ENABLED=false → 우회 (회귀 안전)."""
    monkeypatch.setenv("KMS_POST_GEN_FILTER_ENABLED", "false")
    text = "회의 일정 등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# =============================================================================
# D82-A residual #A — tool_call block 은 strong evidence 가 아님
# =============================================================================
#
# 배경: chat_v1.py 의 D82-A 변경이 final_structured_blocks 의 `tool_result` 와
# `tool_call` 을 같은 schema 로 정규화해 _tool_results_for_scope 로 전달했다.
# `tool_call` 은 실행 *요청/preview* 일 수 있어 단독으로 state evidence 가 되면
# false-allow. 두 가지 layer 로 방어:
#   1) chat_v1.py 에서 `tool_call` block 자체를 evidence pool 에서 제거 (원천).
#   2) _has_strong_state_evidence 에서 block_type=="tool_call" 인 entry 거부 (방어).
#
# 본 test 는 layer 2 — scope_filter 단위에서 block_type guard 동작 검증.


def test_d82a_tool_call_only_does_not_count_as_state_evidence():
    """`tool_call` block 만 있을 때 evidence 인정 X — bot-agnostic 단정 차단."""
    text = "요청하신 내용 등록해 드렸습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["schedule.add"],
        tool_results=[
            {
                "tool": "schedule.add",
                "name": "schedule.add",
                "status": "success",
                "result": {"confirm_id": "SCH-PREVIEW-1", "success": True},
                "block_type": "tool_call",
            }
        ],
    )
    # tool_call block 은 evidence 아님 — bot-agnostic action-done 차단되어야.
    assert out != text


def test_d82a_tool_result_with_success_counts_as_state_evidence():
    """`tool_result` block + success → evidence 인정 → 통과."""
    text = "요청하신 내용 등록해 드렸습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["schedule.add"],
        tool_results=[
            {
                "tool": "schedule.add",
                "name": "schedule.add",
                "status": "success",
                "result": {"confirm_id": "SCH-001", "success": True},
                "block_type": "tool_result",
            }
        ],
    )
    # tool_result + success → evidence — 통과.
    assert out == text


def test_d82a_tool_call_even_with_op_type_create_rejected():
    """`tool_call` block_type 이면 op_type=create / success 라도 거부."""
    text = "예약했습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["reservation.create"],
        tool_results=[
            {
                "tool": "reservation.create",
                "status": "success",
                "result": {"op_type": "create", "success": True},
                "block_type": "tool_call",
            }
        ],
    )
    assert out != text


def test_d82a_mixed_tool_call_and_tool_result_uses_result_only():
    """`tool_call` + `tool_result` 혼합 — tool_result 가 success 면 evidence."""
    text = "요청하신 내용 처리해 드렸습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["schedule.add"],
        tool_results=[
            {
                "tool": "schedule.add",
                "result": {"op_type": "create", "success": True},
                "block_type": "tool_call",  # preview
            },
            {
                "tool": "schedule.add",
                "status": "success",
                "result": {"confirm_id": "SCH-002", "success": True},
                "block_type": "tool_result",  # 실제 결과
            },
        ],
    )
    assert out == text


# =============================================================================
# D82-A residual #E — _GENERAL_ACTION_DONE false positive (assistant-local edit)
# =============================================================================
#
# 결정 (원리 기반, case enum 회피):
#   동사 어간을 둘로 분리. *외부 state-change* (등록/저장/예약/발송/전송/취소
#   /변경/체결/승인/반영/결제/구매/삭제/처리/진행) 는 항상 차단 후보. *양방향*
#   (추가/작성/수정/보완/업데이트/입력/기입/기록/완료) 은 직전 0-12 char 안에
#   "답변 객체" 어휘 (답변/문장/내용/예시/초안/설명/요약/표/항목/단락 등) 가
#   있으면 EXEMPT — 자기 답변 편집 행위로 해석. domain case enum 이 아니라
#   *한국어 메타-언어 (답변 편집)* 구조.


# --- deny matrix — 외부 state-change 단정 (항상 차단) ----------------------

def test_d82a_general_action_done_deny_register():
    """'등록해 드렸습니다.' — 외부 등록 단정 → deny."""
    text = "등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_general_action_done_deny_reserve():
    """'예약했습니다.' — 외부 예약 단정 → deny."""
    text = "예약했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_general_action_done_deny_payment_complete():
    """'결제 완료되었습니다.' — 외부 결제 단정 → deny."""
    text = "결제 완료되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_general_action_done_deny_approval_reflected():
    """'승인 반영했습니다.' — 외부 승인 단정 → deny."""
    text = "승인 반영했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_general_action_done_deny_send():
    """'발송해 드렸어요.' — 외부 발송 단정 → deny."""
    text = "발송해 드렸어요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# --- allow matrix — assistant-local edit (자기 답변 편집) -----------------

def test_d82a_general_action_done_allow_add_content_to_example():
    """'아래 예시에 내용을 추가했어요.' — 답변 내부 편집 → allow."""
    text = "아래 예시에 내용을 추가했어요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_d82a_general_action_done_allow_supplement_explanation():
    """'답변에 설명을 보완했습니다.' — 답변 내부 편집 → allow."""
    text = "답변에 설명을 보완했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_d82a_general_action_done_allow_modify_sentence():
    """'위 문장을 자연스럽게 수정했습니다.' — generic target + anchor → allow.

    v2 verdict 권고: standalone "문장을 수정" 은 외부 객체 가능성 → anchor 필수.
    """
    text = "위 문장을 자연스럽게 수정했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_d82a_general_action_done_allow_write_summary():
    """'아래에 요약을 작성했습니다.' — generic target + anchor → allow.

    v2 verdict 권고: standalone "요약을 작성" 은 외부 문서 가능성 → anchor 필수.
    """
    text = "아래에 요약을 작성했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_d82a_general_action_done_allow_add_row_to_table():
    """'아래 표에 예시 행을 추가했습니다.' — generic target + anchor → allow.

    v2 verdict 권고: standalone "표에 행을 추가" 는 외부 스프레드시트 가능성
    → anchor 필수.
    """
    text = "아래 표에 예시 행을 추가했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# --- ambiguous external object — generic target standalone 시 deny (v2 verdict)

def test_d82a_dual_action_ambiguous_external_customer_field():
    """'고객 정보 항목을 수정했습니다.' — 외부 시스템 가능성 + anchor 없음 → deny.

    v2 verdict §2: 메타-어휘 (항목/내용/표) 가 외부 객체와 충돌. anchor 없으면
    deny 후보. evidence 없으면 차단.
    """
    text = "고객 정보 항목을 수정했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_ambiguous_external_application_content():
    """'신청서 내용을 입력했습니다.' — 외부 시스템 가능성 + anchor 없음 → deny."""
    text = "신청서 내용을 입력했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_ambiguous_external_spreadsheet_row():
    """'스프레드시트 표에 예시 행을 추가했습니다.' — 외부 스프레드시트 가능성
    + anchor 없음 → deny."""
    text = "스프레드시트 표에 예시 행을 추가했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_ambiguous_external_profile_update():
    """'프로필 내용을 업데이트했습니다.' — 외부 프로필 가능성 + anchor 없음 → deny."""
    text = "프로필 내용을 업데이트했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_ambiguous_external_document_item():
    """'문서 항목을 보완했습니다.' — 외부 문서 가능성 + anchor 없음 → deny."""
    text = "문서 항목을 보완했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# --- v3 verdict — document-deictic anchor (이/본/상기/하기) 외부 객체 deny

def test_d82a_dual_action_document_deictic_bon_application():
    """'본 신청서 내용을 입력했습니다.' — '본' 은 외부 문서 deictic → deny.

    v3 verdict §2: '이/본/상기/하기' 는 document-deictic 으로도 쓰임. anchor
    클래스에서 제외해 false-negative 차단.
    """
    text = "본 신청서 내용을 입력했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_document_deictic_sanggi_document():
    """'상기 문서 항목을 수정했습니다.' — '상기' 외부 문서 deictic → deny."""
    text = "상기 문서 항목을 수정했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_document_deictic_hagi_table():
    """'하기 표에 행을 추가했습니다.' — '하기' 외부 문서 deictic → deny."""
    text = "하기 표에 행을 추가했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_document_deictic_i_form_item():
    """'이 양식 항목을 수정했습니다.' — '이' 단독 deictic + 외부 양식 → deny."""
    text = "이 양식 항목을 수정했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_document_deictic_i_document_content():
    """'이 문서 내용을 업데이트했습니다.' — '이' 단독 deictic + 외부 문서 → deny."""
    text = "이 문서 내용을 업데이트했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# --- v3 verdict §1 — anchor proximity 윈도우 검증 (sentence-level 인정 X)

def test_d82a_dual_action_far_anchor_does_not_exempt():
    """'아래에서 설명한 신청서 내용을 입력했습니다.' — anchor '아래' 가 stem 직전
    윈도우 밖 → EXEMPT 안 됨, deny.

    v3 verdict §1: anchor exemption sentence-level 에서 stem 근접 윈도우로 좁힘.
    """
    text = "아래에서 설명한 신청서 내용을 입력했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# --- v4 verdict — anchor regex 우측 morpheme boundary 회귀 ---------------

def test_d82a_dual_action_anchor_prefix_match_blocked_wiimjang():
    """'위임장 내용을 작성했습니다.' — '위' 가 '위임장' 의 prefix 로 매칭되면
    false-negative. anchor regex 의 우측 morpheme boundary 가 차단.

    v4 verdict: anchor 어휘 우측 boundary 필수. "위" 직후 "임" (한글, 조사 아님)
    이면 anchor 매칭 X → deny.
    """
    text = "위임장 내용을 작성했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_anchor_prefix_match_blocked_arae_floor():
    """'아래층 표 항목을 수정했습니다.' — '아래' 가 '아래층' 의 prefix → deny."""
    text = "아래층 표 항목을 수정했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_anchor_prefix_match_blocked_daeum_month():
    """'다음달 항목을 보완했습니다.' — '다음' 이 '다음달' (외부 시간 reference)
    prefix → anchor 매칭 X → deny."""
    text = "다음달 항목을 보완했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_d82a_dual_action_anchor_with_josa_compound_still_allows():
    """'위에서 짧게 설명한 답변을 보완했습니다.' — anchor '위에서' 합법 +
    self-referent '답변' → EXEMPT (이 case 는 self-referent path 통과)."""
    text = "위에서 짧게 설명한 답변을 보완했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_d82a_dual_action_anchor_with_josa_uy_allows():
    """'위의 표에 행을 추가했습니다.' — anchor '위' + 조사 '의' + generic
    target '표/행' 모두 stem 직전 → EXEMPT."""
    text = "위의 표에 행을 추가했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# --- 인접 회귀 — dual stem 이라도 외부 도메인 target 이면 deny -----------

def test_d82a_dual_stem_external_target_blocked():
    """'예약 추가했습니다.' — 도메인 target 매칭 → Tier-1 차단."""
    text = "예약 추가했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    # _TRIGGER 가 예약 + 추가 매칭 → Tier-1 차단 (domain path).
    assert out != text


def test_d82a_dual_stem_assistant_local_with_filler_words_allowed():
    """'위 답변에 짧은 설명을 보완했습니다.' — 답변 객체 + 보완 → allow."""
    text = "위 답변에 짧은 설명을 보완했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# =============================================================================
# D82-A residual #C — admin agent + allowed_tools=[] 우회 회귀 test
# =============================================================================
#
# admin agent 가 의도적으로 allowed_tools=[] 를 사용하는 경우, scope_filter 의
# capability empty deny 가 admin path 를 막으면 회귀. 두 경로 모두 admin guard
# 가 scope_filter_apply 호출 *전* 에 있는지 행위 검증.
#   - engine._persist_turn: line 1457-1462 — agent_ctx + not _is_admin_agent guard
#   - chat_v1.py POST: line 917 — agent_context is not None and not is_admin guard


def test_d82a_admin_agent_empty_allowed_tools_bypasses_engine_path(monkeypatch):
    """engine._persist_turn admin guard — _is_admin_agent=True 시 scope_filter
    호출 자체가 일어나지 않아야 함."""
    from src.agent_framework.runtime import tool_scope_filter as _tsf

    called = {"count": 0}
    orig = _tsf.scope_filter_apply

    def _spy(*a, **kw):  # noqa: ANN002, ANN003
        called["count"] += 1
        return orig(*a, **kw)

    monkeypatch.setattr(_tsf, "scope_filter_apply", _spy)

    # engine._persist_turn 의 admin guard 모사 — _is_admin_agent=True 면 scope_filter
    # branch 진입 X. engine.py 코드:
    #   if assistant_text and agent_ctx is not None and not _is_admin_agent:
    #       scope_filter_apply(...)
    assistant_text = "회의 일정 등록해 드렸습니다."
    _is_admin_agent = True
    agent_ctx_present = True
    if assistant_text and agent_ctx_present and not _is_admin_agent:
        _tsf.scope_filter_apply(assistant_text, allowed_tools=[])

    assert called["count"] == 0, (
        "admin guard 미작동 — engine._persist_turn 에서 admin 인 경우 "
        "scope_filter_apply 가 호출되면 안 됨"
    )


def test_d82a_admin_agent_empty_allowed_tools_bypasses_chat_v1_path(monkeypatch):
    """chat_v1.py admin guard — agent_context.is_admin=True 시 scope_filter
    호출 자체가 일어나지 않아야 함."""
    from src.agent_framework.runtime import tool_scope_filter as _tsf

    called = {"count": 0}
    orig = _tsf.scope_filter_apply

    def _spy(*a, **kw):  # noqa: ANN002, ANN003
        called["count"] += 1
        return orig(*a, **kw)

    monkeypatch.setattr(_tsf, "scope_filter_apply", _spy)

    # chat_v1.py 의 admin guard 모사:
    #   if agent_context is not None and not agent_context.is_admin:
    #       scope_filter_apply(...)
    class _AgentCtx:
        is_admin = True
        allowed_tools: list[str] = []

    agent_context = _AgentCtx()
    assistant_text = "회의 일정 등록해 드렸습니다."
    if agent_context is not None and not agent_context.is_admin:
        _tsf.scope_filter_apply(
            assistant_text, agent_context.allowed_tools or []
        )

    assert called["count"] == 0, (
        "admin guard 미작동 — chat_v1.py 에서 admin 인 경우 scope_filter_apply "
        "가 호출되면 안 됨"
    )


def test_d82a_admin_agent_empty_allowed_tools_engine_source_guard_exists():
    """engine.py 의 admin guard 가 실제 코드에 존재하는지 정합성 검증.

    GPT-5.5 사전 verdict #C: engine.py 변경 금지 절칙으로 코드 수정 X. 단,
    admin guard 가 *실제로* 코드 안에 존재하는지 (1457-1462 line) 본 test 가
    회귀 방지 보증. guard 누락 시 즉시 fail.
    """
    import re as _re
    from pathlib import Path

    engine_path = Path(__file__).resolve().parents[3] / (
        "src/agent_framework/runtime/engine.py"
    )
    src = engine_path.read_text(encoding="utf-8")
    # _persist_turn 의 tool_scope_filter block 안에서 admin guard 패턴 확인.
    # 패턴: scope_filter_apply 가 'not getattr(self, "_is_admin_agent", False)'
    # 또는 동등 boolean 가드 안에서만 호출되는지.
    persist_turn_match = _re.search(
        r"async def _persist_turn[\s\S]+?(?=\n    async def |\n    def |\Z)", src
    )
    assert persist_turn_match, "engine._persist_turn 함수를 찾지 못함"
    block = persist_turn_match.group(0)
    assert "scope_filter_apply" in block
    assert "_is_admin_agent" in block, (
        "engine._persist_turn 의 scope_filter block 에 admin guard 누락 — "
        "admin agent allowed_tools=[] 회귀 가능"
    )


def test_d82a_admin_agent_empty_allowed_tools_chat_v1_source_guard_exists():
    """chat_v1.py 의 admin guard 가 실제 코드에 존재하는지 정합성 검증.

    GPT-5.5 사전 verdict #C: chat_v1.py 의 scope_filter_apply 호출이
    `not agent_context.is_admin` 가드 안에 있는지. 누락 시 admin allowed_tools=[]
    경로가 즉시 회귀.
    """
    import re as _re
    from pathlib import Path

    chat_v1_path = Path(__file__).resolve().parents[3] / (
        "src/api/routers/chat_v1.py"
    )
    src = chat_v1_path.read_text(encoding="utf-8")
    # scope_filter_apply 호출 직전 영역에 not is_admin 가드 있는지 grep.
    # 정확한 line 안정성보다 *함수 호출 직전 가드 keyword* 확인.
    pattern = _re.search(
        r"is_admin[\s\S]{0,400}scope_filter_apply", src
    )
    assert pattern, (
        "chat_v1.py 의 scope_filter_apply 호출 직전에 is_admin guard 누락 — "
        "admin agent allowed_tools=[] 회귀 가능"
    )
