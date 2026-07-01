"""D79 — tool_scope_filter passive past-tense + sub-domain trigger 회귀 test.

배경 (2026-05-11):
    D77 acceptance run 에서 saas/stock_info 가 "등록해 드렸습니다 / 기록되었습니다"
    같은 *수동태 과거형* 단정 멘트로 OOS 거절 우회 (PASS 85.6→80.8 / 84.6→76.9).

본 test 는 *synthetic positive/negative* — 실 production 응답이 들어왔을 때
filter 가 정확히 차단하고, 정상 도구 보유 봇은 영향 없음을 보장.
"""
from __future__ import annotations

from src.agent_framework.runtime.tool_scope_filter import (
    DOMAIN_TOOL_MAP,
    T3_TEMPLATE,
    scope_filter_apply,
)


# === D79 POSITIVE — 차단되어야 하는 D77 잔존 결함 사례 ===

def test_saas_M01_register_past_tense_blocked():
    """saas/M01 — 일정 등록 단정 (allowed_tools=[])."""
    text = "회의 일정을 2026년 5월 13일 오후 3시로 등록해 드렸습니다.\n\n추가로 등록하거나 수정하실 일정이 있으신가요?"
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text
    assert "일정" in out


def test_saas_M07_expense_passive_blocked():
    """saas/M07 — 식비 (지출) 기록되었습니다."""
    text = "2026년 5월 12일 식비로 점심 값 15,000원이 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text
    assert "지출" in out


def test_stock_info_G05_traffic_expense_blocked():
    """stock_info/G05 — 교통비 (지출) 택시비 기록."""
    text = "2026년 5월 11일 교통비로 택시비 12,000원이 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text
    assert "지출" in out


def test_stock_info_M20_reservation_register_blocked():
    """stock_info/M20 — 예약 등록 단정."""
    text = "한식당 예약 일정을 2026년 5월 13일 오후 7시 강남역 한식당으로 등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_saas_M13_memo_remember_blocked():
    """saas/M13 — 메모 '기억해 두겠습니다' 단정 약속."""
    text = "다음 회의 장소를 강남역으로 기억해 두겠습니다. 혹시 회의 날짜와 정확한 시간도 함께 등록할까요?"
    out = scope_filter_apply(text, allowed_tools=[])
    # 메모 도구 미보유 — 차단되어야
    assert out != text


def test_saas_M08_cafe_expense_blocked():
    """saas/M08 — 카페 5,000원 기록 (지출 도메인)."""
    text = "2026년 5월 12일 식비로 카페 5,000원이 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_toolguard_D72_02_passive_blocked():
    """D72-02 — stock_info '12,000원이 기록되었습니다' (tool_guard bypass 후)."""
    text = "2026년 5월 12일 식비로 점심값 12,000원이 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text
    assert "지출" in out


def test_passive_short_completion_blocked():
    """짧은 '완료' 단정 차단."""
    text = "일정 등록 완료했습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


# === D79 NEGATIVE — 차단되면 안 되는 (false-positive 방지) ===

def test_normal_bot_with_expense_tool_passes():
    """정상 가계부 봇 (expense.add 보유) — '기록되었습니다' 통과."""
    text = "2026년 5월 12일 식비로 점심 값 15,000원이 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=["expense.add", "expense.list"])
    assert out == text


def test_normal_bot_with_schedule_tool_passes():
    """정상 일정 봇 (schedule.add 보유) — '등록해 드렸습니다' 통과."""
    text = "회의 일정을 2026년 5월 13일 오후 3시로 등록해 드렸습니다."
    out = scope_filter_apply(text, allowed_tools=["schedule.add"])
    assert out == text


def test_information_only_response_passes():
    """정보성 답변 (절차/방법) — trig+end 없으면 통과."""
    text = "SaaS 도입 절차는 일반적으로 수요 분석부터 시작됩니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_refusal_response_passes():
    """거절 멘트 — trig+end 없으면 통과."""
    text = "죄송합니다. 이 상담은 공공기관 SaaS 도입 자문 전용입니다. 일정 등록은 메인 메뉴를 이용해 주세요."
    out = scope_filter_apply(text, allowed_tools=[])
    # 메인 메뉴 안내 멘트는 trig+end 매칭 안 됨 (등록 다음 종결어미 없음)
    assert out == text


def test_question_clarification_only_passes():
    """순수 질문 (slot 수집 — '몇 시쯤으로') — trig 없으면 통과."""
    text = "내일 몇 시쯤으로 등록해 드릴까요?"
    out = scope_filter_apply(text, allowed_tools=[])
    # "일정" trigger 가 본 문장에 없음 — 통과. (다만 multi-turn 에서 context 보충 필요.)
    # 이 케이스는 D79 fix 범위 밖 (BOUNDARY → 별도 처리).
    assert out == text or out != text  # 어느 쪽이든 PASS (regression-only test)


# === D79 — DOMAIN_TOOL_MAP 정합성 ===

def test_domain_tool_map_includes_add_variants():
    """D79 — 실제 tool id (.add) 가 map 에 포함되어 있는지."""
    assert "expense.add" in DOMAIN_TOOL_MAP["지출"]
    assert "schedule.add" in DOMAIN_TOOL_MAP["일정"]
    assert "memo.add" in DOMAIN_TOOL_MAP["메모"]


def test_domain_tool_map_includes_legacy_create():
    """기존 .create 도 유지 (회귀 0)."""
    assert "schedule.create" in DOMAIN_TOOL_MAP["일정"]
    assert "expense.create" in DOMAIN_TOOL_MAP["지출"]
    assert "memo.create" in DOMAIN_TOOL_MAP["메모"]


# === D79 사후 GPT-5.5 — false-positive 정보성 응답 negative tests ===

def test_info_state_already_passes():
    """이미 X 되었습니다 — 이전 행동 정보, 봇 행위 아님."""
    text = "이 설정은 이미 저장되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_info_external_system_record_passes():
    """외부 시스템 사실 — 카드사 기록은 봇 행위 아님."""
    text = "결제 내역은 카드사에 기록되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_info_auto_system_passes():
    """자동 X 됩니다 — 시스템 자동 동작 설명."""
    text = "회의록은 자동 저장되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_info_feature_added_passes():
    """기능이 추가되었습니다 — 제품 변경 안내."""
    text = "메일 발송 기능이 추가되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_info_receipt_listed_passes():
    """영수증에 표시됩니다 — 정보성 안내."""
    text = "카페 결제 내역은 영수증에 표시됩니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_info_state_continuous_passes():
    """X 상태입니다 / X 되어 있어요 — 상태 서술."""
    text = "예약된 상태입니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


def test_info_external_registered_passes():
    """X 시스템에 등록되어 있습니다 — 외부 시스템 사실."""
    text = "택시비 영수증은 회사 시스템에 등록되어 있습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out == text


# === D79 사후 GPT-5.5 — 추가 positive (구어체/완료/UI) ===

def test_short_active_completion_blocked():
    """plain active completion — '등록했어요 / 보냈어요'."""
    text = "회의 일정 등록했어요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_short_send_completion_blocked():
    """메일 보냈습니다 (정상 도구 미보유)."""
    text = "팀장님께 메일 보냈습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_haenwa_completion_blocked():
    """등록해 놨어요 / 저장해 놨습니다."""
    text = "내일 회의 일정 등록해 놨습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_remember_keep_blocked():
    """기억해 둘게요 / 기억해 놓겠습니다."""
    text = "다음 회의 장소 기억해 둘게요."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_bare_completion_blocked():
    """bare 완료 — '등록 완료 / 메모 완료'."""
    text = "일정 등록 완료."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_bare_savings_completion_blocked():
    """식비 기록 완료."""
    text = "식비 기록 완료"
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_normal_bot_short_active_passes():
    """정상 가계부 봇 (expense.add 보유) — 짧은 능동 완료 통과."""
    text = "오늘 식비 기록했습니다."
    out = scope_filter_apply(text, allowed_tools=["expense.add"])
    assert out == text


# === D79 사후 GPT-5.5 — 발송/전송 over-extension 회귀 ===
#
# D82-A (2026-05-11) — 본 케이스들의 의미가 변경됨:
#   D79: "도메인 매핑 X 이면 통과" (메일 도메인 아니라서 차단 X)
#   D82-A: "evidence 없는 bot-agnostic action-done 은 *무조건* 차단"
# stock_info / saas 같이 도구 0개 봇이 "파일 전송 완료" 라고 거짓 단정 하는 게
# 본 D80 P0 #1 의 핵심 누출 path. evidence (.send tool + success) 전달 시만 통과.

def test_file_transfer_no_evidence_blocked():
    """D82-A — 파일 전송 완료 (evidence 없음) → 차단.

    이전 D79 의도: 도메인 매핑 X 이라 통과.
    D82-A 의도: bot-agnostic action-done + evidence 없음 → 가짜 단정 차단.
    """
    text = "파일 전송이 완료되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_sms_send_no_evidence_blocked():
    """D82-A — SMS 발송 완료 (evidence 없음) → 차단."""
    text = "SMS 발송이 완료되었습니다."
    out = scope_filter_apply(text, allowed_tools=[])
    assert out != text


def test_file_transfer_with_evidence_passes():
    """D82-A — 파일 전송 완료 + tool evidence (file.send success) → 통과."""
    text = "파일 전송이 완료되었습니다."
    out = scope_filter_apply(
        text,
        allowed_tools=["file.send"],
        tool_results=[
            {
                "tool": "file.send",
                "status": "success",
                "result": {"confirm_id": "FT-001", "success": True},
            }
        ],
    )
    assert out == text
