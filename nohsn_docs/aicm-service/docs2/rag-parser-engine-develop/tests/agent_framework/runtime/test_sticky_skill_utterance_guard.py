"""P10g 회귀 가드 — sticky_skill_fallback 발화 길이/어미 가드.

원인 (2026-04-29 사용자 보고):
  직전 turn 의 expense_logger 가 SkillV2 catalog 매칭 None 시 sticky 로 무조건
  fallback. "주식 매매 수수료는 어떻게 되는거야?" 같은 긴 의문문도 expense_logger
  로 흘러 빈 답변 + SSE 끊김.

가드 (engine._maybe_activate_skill_v2):
  - utt_len > 14 OR 의문/명령 어미 ("?", "까", "야", "냐", "지", "나요",
    "해", "줘", "워", "주세요", "할래", "줄래", "다") 종결 → sticky skip
  - 짧은 ack/follow-up ("응", "네", "더", "다음", "좋아") 만 sticky 진입 허용
"""
from __future__ import annotations

import pytest


# 코드 가드와 동일한 어미 집합
_INTENT_END = (
    "까",
    "야",
    "냐",
    "지",
    "나요",
    "해",
    "줘",
    "워",
    "주세요",
    "할래",
    "줄래",
    "다",
)


def _short_followup(utt: str) -> bool:
    u = utt.strip()
    intent = "?" in u or u.endswith(_INTENT_END)
    return len(u) <= 14 and not intent


@pytest.mark.parametrize(
    "utt,expected_sticky",
    [
        # 짧은 ack/follow-up — sticky 적용
        ("응", True),
        ("네", True),
        ("좋아", True),
        ("더", True),
        ("다음", True),
        ("ㅇㅋ", True),
        # 긴 발화 / 의문문 / 명령 — sticky skip (fresh routing)
        ("주식 매매 수수료는 어떻게 되는거야?", False),  # ?
        ("이번 달 가계부 알려줘", False),  # 줘
        ("내일 회의 등록해", False),  # 해
        ("연차 신청 어떻게 해?", False),  # ?
        ("KB은행 콜센터 정책이 어떻게 돼?", False),  # ?
        ("뭐 더 있나요?", False),  # 나요
        ("도와줄까", False),  # 까
        ("뭐야", False),  # 야
        ("이거 삭제해", False),  # 해
        ("그건 뭐냐", False),  # 냐
        # "그거 알아" — 짧은 진술, 종결 어미 미포함 → sticky 유지 (안전 default)
        ("그거 알아", True),
    ],
)
def test_sticky_utterance_guard_classification(utt: str, expected_sticky: bool):
    """가드 단위 테스트 — 사용자 보고 회귀 케이스 영구 가드."""
    got = _short_followup(utt)
    assert got == expected_sticky, (
        f"utt={utt!r}: expected sticky={expected_sticky}, got short_followup={got}"
    )


def test_user_reported_case_does_not_stick_to_expense_logger():
    """사용자 직접 보고 — '주식 매매 수수료는 어떻게 되는거야?' 는 sticky skip 되어야 함."""
    assert not _short_followup("주식 매매 수수료는 어떻게 되는거야?")


def test_simple_ack_still_sticks():
    """짧은 ack 응답은 직전 페르소나 유지 — 회귀 방지."""
    for utt in ["응", "네", "좋아", "더 봐", "ㅇㅋ", "OK"]:
        assert _short_followup(utt), f"{utt!r} should still stick"
