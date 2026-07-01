"""Tool scope post-generation filter — D65 / D79 / D82-A.

응답 본문에 *없는 도구 영역의 행위 제안* 패턴 탐지 시 T3 셀프가이드 멘트로 치환.

배경 (2026-05-12 사용자 보고):
    SaaS 자문 봇 (allowed_tools = kms_rag/kms_sop/web.search/web.fetch) 이
    "내일 약속 있어" → "등록해 드릴까요?" 멘트 송출. system prompt 의
    TOOL_SCOPE_GUARD 가 *first line of defense* 지만, LLM 이 long context 에서
    가끔 잊는다. 본 모듈은 *post-generation* 차원의 *second line of defense* —
    완성된 응답 본문을 정규식으로 스캔, 없는 도구 영역 행위 제안 패턴 매칭 시
    T3 셀프가이드 멘트로 치환.

D82-A (2026-05-11) — capability deny-by-default + bot-agnostic action-done:
    D80 P0 #1: stock_info (allowed_tools=[]) 가 "회의 일정 ... 등록해 드렸습니다"
    같은 단정 응답 노출. 도메인 word 가 약하거나 매핑 누락 시 SKIP 되어 누출.
    fix 방향:
      1. 도메인 *있음* + DOMAIN_TOOL_MAP 매핑 *비어있음* → deny (skip X)
      2. 도메인 *있음* + allowed_tools *비어있음* → deny
      3. bot-agnostic 행위 완료 표현 (도메인 word 없이 "처리해 드렸어요" /
         "예약했습니다" 등) 매칭 시 tool evidence 검증 — 없으면 차단
    GPT-5.5 사전 verdict (2026-05-11 GO_WITH_CHANGES) 권고 반영:
      - bare (되었|됐) 금지 — 반드시 action stem 과 결합
      - 정상 능동 완료 (예약했습니다 / 등록했습니다 등) 포함
      - has_state_change_evidence 는 current-turn / state-changing / allowed tool
        기준으로 엄격. read-only / failed / unrelated 제외
      - _EXEMPT 는 sentence-level 적용 (기존 동작 유지)

설계 원칙 (GPT-5 보강):
    - 정보성 설명 ("도입 절차는?" / "신청 방법?") 은 *예외* — 통과.
    - 트리거 + 종결어미 *동시* 매칭만 차단. 단일어 매칭 X (false-positive 회피).
    - allowed_tools 에 해당 도메인 도구가 *있으면* 통과 (정상 슬롯 수집 허용).
    - 하드코딩 키워드 리스트는 *최소* — 도메인 일반화. 변형 표현은 LLM
      TOOL_SCOPE_GUARD 가 1차 차단, 본 필터는 핵심 패턴만.
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterable


def _is_enabled() -> bool:
    """D78 kill-switch — 신규 키 우선, 미설정 시 구형 키 fallback.

    - ``KMS_POST_GEN_FILTER_ENABLED`` (신규) — 설정 시 이 값만 사용.
    - ``KMS_POST_GEN_FILTER`` (구형 alias) — 신규 키 미설정 시 fallback.
    - default = true (회귀 0). 사전 GPT-5 GO_WITH_CHANGES 권고 반영.

    false/0/no/off 시 bypass (scope_filter_apply 가 원본 그대로 반환).
    """
    raw = os.getenv("KMS_POST_GEN_FILTER_ENABLED")
    if raw is None:
        raw = os.getenv("KMS_POST_GEN_FILTER", "true")
    return (raw or "").strip().lower() not in ("0", "false", "no", "off")


# 도메인 → 해당 도구 prefix 매핑. allowed_tools 에 *어떤* 도구가 있으면 통과.
# (set 비교 — exact match 가 아닌 prefix-based 도 가능하나 일단 정확한 도구 id.)
#
# D79 (2026-05-11) — *실제* 도구 id (.add/.delete/.list/.update/.send) 반영.
# 이전 .create/.log 만 기재 → DOMAIN_TOOL_MAP 우회 가능성 차단. tool registry
# 와 정합. (예: schedule.add, expense.add, memo.add 가 실제 tool id.)
DOMAIN_TOOL_MAP: dict[str, set[str]] = {
    "일정": {
        "schedule.add", "schedule.create", "schedule.update", "schedule.delete",
        "schedule.list", "calendar.create", "calendar.add",
    },
    "지출": {
        "expense.add", "expense.create", "expense.update", "expense.delete",
        "expense.list", "expense.log",
    },
    "메모": {
        "memo.add", "memo.create", "memo.update", "memo.delete", "memo.list",
        "diary.add",  # diary 도 메모 도메인 자매 도구
    },
    "예약": {
        "reservation.create", "reservation.add", "reservation.reschedule",
        "reservation.cancel", "reservation.list",
    },
    "메일": {
        "mail.send", "mail.compose", "mail.list", "mail.search", "email.send",
    },
    "이메일": {
        "mail.send", "mail.compose", "mail.list", "mail.search", "email.send",
    },
    "알림": {
        "reminder.schedule", "reminder.create", "reminder.add", "reminder.cancel",
    },
    "리마인더": {
        "reminder.schedule", "reminder.create", "reminder.add", "reminder.cancel",
    },
    "주문": {
        "reservation.create", "order.create", "order.add",
    },
    "결제": set(),  # 결제 도구 미지원 — 항상 차단
}

# 트리거: 도메인 명사 ± 0-8 char ± 행위 동사. GPT-5 보강 동의어 포함.
#
# D79 (2026-05-11) — sub-domain 명사 추가. 봇 응답이 *상위 도메인* 이 아닌 *세부
# 분류* (식비/교통비/회식비/카페/택시비) 로 표현해도 매칭. D77 잔존 결함:
#   "식비로 점심 값 15,000원이 기록되었습니다." (saas/M07)
#   "교통비로 택시비 12,000원이 기록되었습니다." (stock_info/G05)
# 위 사례 모두 *지출* 도메인 — 식비/교통비/회식비 등 카테고리 명사가 trigger.
_TRIGGER = re.compile(
    r"("
    # 일정 도메인 + 동의어
    r"일정|미팅|회의|약속"
    # 지출 도메인 + 세부 카테고리 (D79)
    r"|지출|식비|교통비|회식비|카페|택시비|영수증|가계부"
    # 메모/예약/메일/알림/주문/결제
    r"|메모|예약|메일|이메일|알림|리마인더|주문|결제"
    # D79 사후 GPT-5.5 — 발송/전송 trigger 제거. action verb (파일/SMS/푸시
    # 전송 가능) — 도메인 신호 아님. _END 에는 유지 (수동태 변형 차단).
    r")"
    # D79 — 거리 0-40 char (한국어 답변에서 trig→verb 사이 datetime/금액/주체 등
    # natural slot 이 들어감. 0-12 는 너무 좁아 D77 잔존 결함 누출).
    # 같은 문장 안 검사 (_SENTENCE_SPLIT 으로 분리됨) 이므로 over-match 위험 낮음.
    r".{0,40}"
    # D79 사후 — 동사 어간 변형 보강: 보내/보냈/보냄, 등록/등록했, 완료/끝났.
    r"(등록|저장|추가|보내|보냈|보냄|발송|전송|신청|구매|예약|기록|입력|기입|작성|생성|만들|완료|기억|끝났)",
)

# 종결어미 (질문형 / 의지형 / 행위 약속 + 과거형 단정). 답변에 *반드시* 함께
# 매칭돼야 차단. *trig + end + (도메인 도구 미보유)* 3 조건 충족 시만 차단.
#
# D79 (2026-05-11) 보강 — D77 saas/stock_info 회귀 사례 dump 기반:
# - "등록해 드렸습니다" / "기록되었습니다" / "등록되었습니다" 같은 passive past-tense
#   단정 변형 추가. 이전 _END 가 *미래/의지형* 만 매칭 → 잔존 결함 누출.
# - "기억해 두겠습니다" 같은 메모 단정 약속 추가.
# - "완료 / 완료했습니다 / 완료되었습니다" 같은 short completion 패턴 추가.
# - 정상 봇 (해당 도메인 도구 보유) 은 DOMAIN_TOOL_MAP 통과 → 영향 0.
_END = re.compile(
    # === 미래/의지/약속/질문형 (기존 D65/D68 유지) ===
    r"(해[ ]?드릴까요"
    r"|해[ ]?드릴게요"
    r"|해[ ]?드리겠습니다"
    r"|도와드릴까요"
    r"|진행할까요"
    r"|등록하겠습니다"
    r"|저장하겠습니다"
    r"|추가해[ ]?드릴게요"
    r"|보낼까요"
    r"|보내[ ]?드릴까요"
    r"|보내[ ]?드릴게요"
    r"|보내[ ]?드리겠습니다"
    r"|처리해[ ]?드릴게요"
    r"|만들어[ ]?드릴까요"
    r"|만들어[ ]?드릴게요"
    r"|드리겠습니다"
    # 사용자 권유형 — "메모 저장하시겠어요?" / "등록하시겠습니까?" 같은 LLM
    # 이 사용자에게 행위 의향을 묻는 패턴. 본 봇은 도구 없으므로 차단.
    r"|하시겠어요"
    r"|하시겠습니까"
    # === D79 — 과거형/수동태 단정 (acceptance 누출 차단) ===
    # 능동 완료 — "등록해 드렸습니다 / 보내 드렸어요"
    r"|등록해[ ]?드렸어요"
    r"|등록해[ ]?드렸습니다"
    r"|저장해[ ]?드렸어요"
    r"|저장해[ ]?드렸습니다"
    r"|기록해[ ]?드렸어요"
    r"|기록해[ ]?드렸습니다"
    r"|보내[ ]?드렸어요"
    r"|보내[ ]?드렸습니다"
    r"|처리해[ ]?드렸어요"
    r"|처리해[ ]?드렸습니다"
    r"|발송해[ ]?드렸어요"
    r"|발송해[ ]?드렸습니다"
    r"|추가해[ ]?드렸어요"
    r"|추가해[ ]?드렸습니다"
    # 수동태 완료 — "기록되었습니다 / 등록되었어요 / 저장됐습니다"
    r"|등록되었어요"
    r"|등록되었습니다"
    r"|등록됐어요"
    r"|등록됐습니다"
    r"|등록됐네요"
    r"|기록되었어요"
    r"|기록되었습니다"
    r"|기록됐어요"
    r"|기록됐습니다"
    r"|저장되었어요"
    r"|저장되었습니다"
    r"|저장됐어요"
    r"|저장됐습니다"
    r"|처리되었어요"
    r"|처리되었습니다"
    r"|처리됐어요"
    r"|처리됐습니다"
    r"|예약되었어요"
    r"|예약되었습니다"
    r"|예약됐어요"
    r"|예약됐습니다"
    r"|발송되었어요"
    r"|발송되었습니다"
    r"|발송됐어요"
    r"|발송됐습니다"
    r"|전송되었어요"
    r"|전송되었습니다"
    r"|전송됐어요"
    r"|전송됐습니다"
    r"|추가되었어요"
    r"|추가되었습니다"
    r"|추가됐어요"
    r"|추가됐습니다"
    # short completion — "완료 / 완료했습니다 / 완료되었습니다"
    r"|완료했어요"
    r"|완료했습니다"
    r"|완료되었어요"
    r"|완료되었습니다"
    r"|완료됐어요"
    r"|완료됐습니다"
    r"|완료입니다"
    # 메모 단정 약속 — "기억해 두겠습니다 / 기억해 두었어요"
    r"|기억해[ ]?두겠어요"
    r"|기억해[ ]?두겠습니다"
    r"|기억해[ ]?두었어요"
    r"|기억해[ ]?두었습니다"
    r"|기억해[ ]?뒀어요"
    r"|기억해[ ]?뒀습니다"
    r"|기억해[ ]?둘게요"
    r"|기억해[ ]?둘께요"
    r"|기억해[ ]?놓겠습니다"
    # D79 사후 GPT-5.5 — plain active completion (구어체 짧은 완료)
    r"|등록했어요"
    r"|등록했습니다"
    r"|저장했어요"
    r"|저장했습니다"
    r"|기록했어요"
    r"|기록했습니다"
    r"|보냈어요"
    r"|보냈습니다"
    r"|발송했어요"
    r"|발송했습니다"
    r"|전송했어요"
    r"|전송했습니다"
    r"|예약했어요"
    r"|예약했습니다"
    r"|추가했어요"
    r"|추가했습니다"
    r"|처리했어요"
    r"|처리했습니다"
    # 해놨/해뒀 형식
    r"|등록해[ ]?놨어요"
    r"|등록해[ ]?놨습니다"
    r"|저장해[ ]?놨어요"
    r"|저장해[ ]?놨습니다"
    r"|메모해[ ]?놨어요"
    r"|메모해[ ]?놨습니다"
    r"|메모해[ ]?두었어요"
    r"|메모해[ ]?둘게요"
    r"|예약해[ ]?뒀어요"
    r"|예약해[ ]?뒀습니다"
    # bare 완료 (action noun + 완료)
    r"|등록\s*완료"
    r"|저장\s*완료"
    r"|기록\s*완료"
    r"|발송\s*완료"
    r"|전송\s*완료"
    r"|예약\s*완료"
    r"|메모\s*완료"
    r"|처리\s*완료"
    # 끝났습니다 / 해결됐습니다
    r"|끝났어요"
    r"|끝났습니다"
    r"|해결됐어요"
    r"|해결됐습니다)"
)

# D79 — 세부 명사 → 상위 도메인 키 정규화. _TRIGGER 가 sub-domain 명사
# (식비/회의/약속 등) 를 캡처해도 DOMAIN_TOOL_MAP 의 *상위 도메인 키* 로 lookup.
#
# D79 사후 GPT-5.5 권고 (2026-05-11) — "발송/전송" alias 제거:
# 발송/전송 은 도메인이 아닌 action verb. "파일 전송 완료 / 데이터 전송 기록"
# 같은 비-메일 도메인을 메일로 정규화하면 false-positive. _TRIGGER 에 그대로 두되
# alias 매핑은 명시적 메일 어휘 (메일/이메일) 에 한정.
_DOMAIN_ALIAS: dict[str, str] = {
    "회의": "일정",
    "미팅": "일정",
    "약속": "일정",
    "식비": "지출",
    "교통비": "지출",
    "회식비": "지출",
    "카페": "지출",
    "택시비": "지출",
    "영수증": "지출",
    "가계부": "지출",
    # 발송/전송 = action verb (파일/SMS/푸시 전송 가능) — 도메인 매핑 X.
    # _TRIGGER 매칭 시 발송/전송 captured → DOMAIN_TOOL_MAP.get("발송") = set()
    # → 빈 set → 차단 X (정상 도구 보유 봇 영향 0). 메일 도메인 명시 발화는
    # "메일|이메일" trigger 가 별도 매칭.
}


def _normalize_domain(trigger_term: str) -> str:
    """trigger 명사 → DOMAIN_TOOL_MAP 키로 정규화."""
    return _DOMAIN_ALIAS.get(trigger_term, trigger_term)


# 설명 맥락 예외 — 정보성 답변은 통과.
#
# D79 사후 GPT-5.5 (2026-05-11) — 정보성 상태 서술 추가:
# - "이미 X 되었습니다" — 사용자가 이전에 한 행동 정보 (봇 행위 X)
# - "자동 X 됩니다" / "자동으로 X 됩니다" — 시스템 자동 동작 설명
# - "X 기능이 추가되었습니다" — 제품/시스템 변경 안내
# - "X 시스템에 등록되어 있습니다" / "X 카드사에 기록되었습니다" — 외부 시스템 사실
_EXEMPT = re.compile(
    r"(절차|방법|가이드|정의|정책|요건|단계|순서|규정)"
    r".{0,8}"
    r"(은|는|입니다|예요|이에요|이며|이고|입니다\.|로|로는)"
    # D79 — 정보성 상태 단서
    # D82-A 보강: \S{0,8} (1+ → 0+) 로 "이미 저장되었습니다" 같이 사이 word 없는 케이스 포함.
    r"|이미\s+\S{0,8}\s?(등록|저장|예약|발송|전송|처리|기록|추가|완료)"
    r"|자동(으로)?\s+\S{0,8}\s?(등록|저장|예약|발송|전송|처리|기록|추가|완료)"
    r"|기능이\s+(추가|등록|개선|개편)"
    r"|(시스템|카드사|업체|회사|서버)에\s+\S{0,8}\s?(등록|저장|기록|발송|전송)"
    r"|영수증에\s+(표시|기재|등록|기록)"
    r"|상태입니다"
    r"|되어\s*있어요"
    r"|되어\s*있습니다"
    # D82-A 신규 — 정보성 안내 동사 / "표시됩니다" "안내됩니다"
    r"|(라고|이라고)\s+(표시|안내|기재|기록)"
    r"|할\s*수\s*있(습니다|어요|네요)"
    r"|하실\s*수\s*있(습니다|어요|네요)",
)


# 문장 분절 — 한국어 마침표/물음표/느낌표/개행 기준. 줄바꿈도 문장 경계 취급.
# 정확한 NLP 가 아닌 conservative split — 같은 문장 안 trig+end 검사용.
_SENTENCE_SPLIT = re.compile(r"(?<=[\.\?\!\n])\s*")


# D82-A — bot-agnostic 행위 완료 표현. 도메인 word *없이* 행위 동사 + 종결만으로
# 단정 응답 차단. GPT-5.5 사전 verdict (2026-05-11):
#   1. bare (되었|됐)(어요|습니다) 금지 — action stem 필수 결합
#   2. 능동 과거형 (예약했습니다 / 등록했습니다 등) 포함
#   3. 해 드렸/해 드리겠/해 드릴 / 해 줬 / 처리했 / 진행했 변형 포함
#
# D82-A 사후 GPT-5.5 #E (2026-05-13) — _GENERAL_ACTION_DONE false positive 회피:
#   동사 어간 분리 (원리 기반, case enum 아님):
#     (a) external_action_stem — 외부 state-change 단정 (등록/저장/예약/발송/전송
#         /취소/변경/체결/승인/반영/결제/구매/삭제/처리/진행). assistant 가 자기
#         답변 내부 객체에 *이 동사들* 을 적용할 일은 거의 없음 → 항상 차단 후보.
#     (b) dual_action_stem — 양방향 의미 (추가/작성/수정/보완/업데이트/입력/기입/
#         기록/완료). assistant-local edit ("답변에 내용을 추가했어요", "문장을
#         수정했습니다") 도 자연스럽게 사용 → assistant-local target 가드 필요.
#
# D82-A 사후 #E v2 (2026-05-13, v2 verdict) — false-negative 회피 보강:
#   기존 가드 = "stem 직전 메타-어휘 (내용/항목/표 등) 있음" 단독으로 EXEMPT.
#   문제: 메타-어휘가 외부 시스템 객체에도 자연스럽게 쓰임 ("고객 정보 항목을
#       수정", "신청서 내용을 입력") — 외부 state change 를 답변 편집으로 오분류
#       (false-negative).
#   보강: 메타-어휘를 두 group 으로 분리.
#     - self_referent_target = 답변 / 응답 / 메시지 — 자체로 assistant-local
#       anchor 역할. 외부 시스템에서 거의 안 쓰임 → 단독 EXEMPT.
#     - generic_local_target = 내용 / 예시 / 초안 / 표 / 항목 / 문장 / 단락 등 —
#       외부 객체로도 쓰일 수 있음. EXEMPT 하려면 sentence 안 어딘가에
#       assistant_local_anchor (아래 / 위 / 다음 / 이 / 본 / 앞서 / 방금 / 제가
#       / 저는 / 여기 / 이번 / 우리) 가 함께 있어야 함.
#
#   가드는 case enum 이 아니라 *언어 패턴 원리* — "(self-reference) 를/안에
#   (편집 동사) 했다" 라는 한국어 메타-언어 구조. 새 객체 (paragraph 등) 가
#   생겨도 같은 어휘 패턴으로 자연 일반화. 새 anchor (e.g. 상기/하기) 추가도
#   동일 클래스 확장으로 처리 — domain case 아님.

# 외부 state-change 단정 — assistant-local edit 가능성 거의 없음. 항상 차단.
_EXTERNAL_ACTION_STEM = (
    r"등록|저장|예약|발송|전송|취소|변경|삭제"
    r"|체결|승인|반영|결제|구매|처리|진행"
)
# 양방향 의미 stem — assistant-local target 가드 필요.
_DUAL_ACTION_STEM = (
    r"추가|작성|수정|보완|업데이트|입력|기입|기록|완료"
)

# 모든 stem (Tier-2 매칭 후보). 가드는 매칭 후 별도 검사.
_GENERAL_ACTION_DONE = re.compile(
    r"(?P<stem>"
    + _EXTERNAL_ACTION_STEM
    + r"|"
    + _DUAL_ACTION_STEM
    + r")"
    # 종결 — 동사 직후 (공백/한글 보조 조사 0-3 char) + 완료/봉사 어미
    r"(?:"
    # 봉사형 — "해 드렸어요 / 해 드리겠습니다 / 해 드릴게요 / 해 주었어요 / 해 줬어요"
    r"\s*해[ ]?(?:드렸|드리겠|드릴|주었|줬|놨|두었|뒀)\S{0,6}"
    # 능동 과거형 — "예약했습니다 / 등록했어요 / 처리했네요"
    r"|했(?:습니다|어요|네요|음|음\.?)"
    # 수동 완료 — 반드시 action stem 직후의 (되었|됐)(어요|습니다|네요)
    r"|되었(?:습니다|어요|네요)"
    r"|됐(?:습니다|어요|네요)"
    # 명사형 + 완료 — "등록 완료 / 처리 완료"
    r"|\s*완료(?:했|되|입니다|\.?$)?"
    r")"
)

# self-referent target — assistant 의 *자기 응답* 그 자체. 외부 시스템에서
# 거의 안 쓰임 → stem 직전 위치 시 단독 EXEMPT.
_SELF_REFERENT_TARGET = re.compile(
    r"(?:답변|응답|메시지)"
    r"[을를이가에에는도만의]*"
    r"\s{0,6}"
)

# generic-local target — 답변 *내부 객체* 어휘. 외부 시스템 객체에도 자연스럽게
# 쓰임 → 단독으로는 EXEMPT 안 함. sentence-level anchor 동반 시에만 EXEMPT.
#
# 어휘 선정 원리: 한국어 텍스트 단위 명사. 도메인 case 가 아닌 *텍스트 객체*
# 메타-어휘. 새 항목 (paragraph 등) 도 동일 패턴.
_GENERIC_LOCAL_TARGET = re.compile(
    r"(?:문장|문구|내용|예시|예제|초안|설명|요약|표|항목|단락|문맥|행"
    r"|제목|소제목|개요|코드\s?블록|코드|스니펫|샘플|단어|문단)"
    r"[을를이가에에는도만의]*"
    r"\s{0,6}"
)

# assistant-local anchor — 응답 *자체* 를 가리키는 deictic / 1인칭 self-
# reference 표현. generic-local target 의 EXEMPT 조건.
#
# v3 verdict (2026-05-13) — document-deictic 제외:
#   `이` / `본` / `상기` / `하기` 는 외부 *문서/양식* reference 에도 자주 쓰임
#   ("본 신청서 내용", "상기 문서 항목", "하기 표"). 외부 객체 false-negative
#   유발 → anchor 클래스에서 *제외*. 정말 self-reference 명확한 어휘만 유지.
#   ("이 답변" 같은 정상 케이스는 self_referent_target "답변" 이 단독 EXEMPT
#   path 로 통과 — 별도 anchor 불필요).
#
# v4 verdict (2026-05-13) — 우측 morpheme boundary 필수:
#   기존 left-only boundary `(?<![가-힣])` 는 "위임장 내용을 작성" 같이 anchor
#   어휘가 *외부 명사의 prefix* 와 매칭되는 false-negative 허용. 한국어 *조사*
#   morpheme set (단음절 + 다음절) lookahead 로 우측 경계 확립.
#   "위에" / "위의" / "위에서" / "위 " 합법 / "위임장" / "위층" 매칭 X.
#
# 한글 boundary lookbehind — 짧은 어휘 (위 등) 가 다른 단어 안에 부분 매칭
# 차단 (예: "범위" 안의 "위" → lookbehind 가 "범" 한글 → fail).
# regex alternation 은 *longer 먼저* — "위에" 가 "위" 보다 우선.
_ASSISTANT_LOCAL_ANCHOR = re.compile(
    r"(?<![가-힣])"
    r"(?:아래|위에|위|다음|앞서|앞에|뒤에|방금|여기|이번|이렇게"
    r"|제가|저는|저희|우리)"
    # 우측 boundary: 공백 / 구두점 / 문장 끝 / 한국어 조사 (단음절 + 다음절).
    # 조사 set 은 *언어학적 morpheme 클래스* — 도메인 case enum 아님.
    r"(?=\s|[.,!?:;]|$"
    r"|[은는이가을를의에로와과도만]"  # 단음절 격조사 + 보조사
    r"|에서|으로|부터|까지|마저|조차|뿐|에는|에도|에만"
    r")"
)

# backward-compat — 기존 코드 reference 보존. 신규 호출은 분리 패턴 사용 권장.
_ASSISTANT_LOCAL_TARGET = re.compile(
    _SELF_REFERENT_TARGET.pattern + r"|" + _GENERIC_LOCAL_TARGET.pattern
)


# D82-A — 사용자 발화 인용 블록 (따옴표 안) 은 봇 행위 X 로 취급. _GENERAL_ACTION_DONE
# scan 전에 제거.
_QUOTED_BLOCK = re.compile(r'["“”‘’\'][^"“”‘’\']*["“”‘’\']')


# D82-A — 정보성 안내 추가 패턴 (action verb 가 정보 맥락임을 시사):
#   - "...라고 표시됩니다" / "...라고 안내됩니다"
#   - "...할 수 있습니다" / "...하실 수 있어요"
#   - "...에 표기됩니다"
_INFO_CONTEXT = re.compile(
    r"(라고|이라고)\s+(표시|안내|기재|기록)"
    r"|할\s*수\s*있(?:습니다|어요|네요)"
    r"|하실\s*수\s*있(?:습니다|어요|네요)"
    r"|에\s+(?:표기|표시|기재)"
)


def _has_strong_state_evidence(tool_results: Iterable[Any] | None) -> bool:
    """D82-A — current-turn state-change 성공 evidence 가 있는지.

    D68 adversarial_checker._has_state_change_evidence 와 동일 시그널을 본 모듈
    안에 *복제* (private 결합도 회피). GPT-5.5 사전 권고 (2026-05-11):
        - confirm_id / evidence_id 존재
        - op_type ∈ {create, update, delete} + success
        - tool name 에 .create / .update / .delete / .send 어간 + status success
        - result.ok=True / rows_affected>0

    엄격화 (read-only / failed 제외):
        - status ∈ {error, failed, fail, false} → False
        - op_type=read → 단독으로는 evidence 아님

    D82-A 사후 GPT-5.5 #A (2026-05-13) — block_type 가드:
        - block_type == "tool_call" 인 entry 는 *실행 요청/preview* 일 수 있으므로
          단독으로 evidence 가 될 수 없다. chat_v1 path 가 이미 `tool_call` 을
          제거하지만 본 함수 자체도 방어해 caller 경로 변동에 무방.
    """
    if not tool_results:
        return False

    state_change_suffixes = (".create", ".update", ".delete", ".add", ".send")
    state_change_ops = {"create", "update", "delete", "add", "send"}

    for tr in tool_results:
        if not isinstance(tr, dict):
            continue
        # block_type == "tool_call" 은 실행 결과가 아닌 *요청/preview* — 거부.
        if (tr.get("block_type") or "").lower() == "tool_call":
            continue
        result = tr.get("result")
        if not isinstance(result, dict):
            continue

        # 명시 실패 시그널 — evidence 아님.
        status_raw = (tr.get("status") or result.get("status") or "").lower()
        if status_raw in {"error", "failed", "fail", "false"}:
            continue
        if result.get("success") is False or result.get("ok") is False:
            continue

        # confirm_id / evidence_id — 명시 evidence.
        if result.get("confirm_id"):
            return True
        if result.get("evidence_id"):
            return True

        # op_type + success
        op_type = (result.get("op_type") or "").lower()
        if op_type in state_change_ops and result.get("success") is True:
            return True

        # tool name + status success
        tool_name = (tr.get("tool") or tr.get("name") or "").lower()
        if status_raw in {"success", "ok", "completed", "true"} and any(
            suffix in tool_name for suffix in state_change_suffixes
        ):
            return True

        # rows_affected
        rows_affected = result.get("rows_affected")
        if isinstance(rows_affected, int) and rows_affected > 0:
            return True
        if result.get("ok") is True and any(
            suffix in tool_name for suffix in state_change_suffixes
        ):
            return True

    return False


T3_TEMPLATE = "필요하시면 메인 메뉴의 {domain} 기능으로 직접 진행해 주세요."
T3_GENERIC = "해당 작업은 직접 진행해 주세요. 메인 메뉴에서 원하는 기능을 이용하실 수 있어요."


def scope_filter_apply(
    response_text: str | None,
    allowed_tools: Iterable[str] | None,
    *,
    agent_persona: str | None = None,
    tool_results: Iterable[Any] | None = None,
) -> str:
    """응답이 *없는 도구 영역* 의 행위 제안 멘트면 T3 셀프가이드로 치환.

    Args:
        response_text: LLM 이 생성한 최종 응답 본문.
        allowed_tools: agent.allowed_tools (set / list / None 모두 허용).
        agent_persona: 보강용 (현재 미사용 — T3 멘트는 도메인 변수만 사용).
        tool_results: 현재 턴 tool 호출 결과 (D82-A 신규). evidence 검증용.
            None / 빈 리스트 시 evidence 없음 가정 (보수적 deny).

    Returns:
        치환된 본문. 매칭 안 됨 / 예외 케이스 시 입력 그대로 반환.

    Notes:
        - allowed_tools 가 None / 빈 set 이면 *모든 도구 미허용 가정* — 트리거
          매칭 시 차단. (보수적 default.)
        - _EXEMPT (정보성 설명) 가 먼저 매칭되면 우회. "도입 절차는?" 같은 답변
          은 통과.
        - 본 함수는 *side-effect free*. 로깅은 caller 에 위임.

    D82-A (2026-05-11) — capability deny-by-default + bot-agnostic action-done:
        1. 도메인 매칭 + DOMAIN_TOOL_MAP 매핑 *비어있음* → deny (skip X).
        2. 도메인 매칭 + allowed_tools *비어있음* → deny.
        3. 도메인 매칭 없어도 bot-agnostic 행위 완료 표현 + evidence 없음 → deny.
    """
    if not response_text:
        return response_text or ""

    # D78 — 분모 metric (진입 횟수 기록 — kill-switch 검사 *전*).
    try:
        from src.common.metrics import inc_guard_input

        inc_guard_input("tool_scope_filter")
    except Exception:  # noqa: BLE001 — metric site 안전망.
        pass

    # D78 kill-switch — bypass 시 원본 그대로 반환 (회귀 0).
    if not _is_enabled():
        return response_text

    # allowed_tools 정규화 (이후 path 들이 공유).
    allowed_set: set[str] = set()
    if allowed_tools:
        allowed_set = {str(t).strip() for t in allowed_tools if t}

    # GPT-5 보강 (2026-05-12) — 문장 단위 검사. 같은 문장 안에서 trig+end 동시
    # 매칭만 차단. EXEMPT 는 trig+end 가 *없는* 문장에만 적용 — 복합 답변
    # ("절차는 …. 등록해 드릴까요?") 우회 차단.
    sentences = _SENTENCE_SPLIT.split(response_text)
    blocked_domain: str | None = None
    bot_agnostic_hit: bool = False
    for sentence in sentences:
        if not sentence.strip():
            continue
        # D82-A — 인용 블록 (따옴표 안) 제거 후 scan. "매뉴얼에는 '결제 완료'라고
        # 표시됩니다" 같은 정보성 인용 보호.
        scan_sentence = _QUOTED_BLOCK.sub(" ", sentence)
        # 정보성 컨텍스트 (라고 표시됩니다 / 할 수 있습니다 / 에 표기됩니다) — skip.
        if _INFO_CONTEXT.search(scan_sentence):
            continue
        # 기존 EXEMPT — 정보성 설명 / 외부 시스템 사실. 통과.
        if _EXEMPT.search(scan_sentence):
            continue

        # Tier-1: 도메인 + 종결 매칭 (D65/D79 기존 path).
        s_trig = _TRIGGER.search(scan_sentence)
        s_end = _END.search(scan_sentence)
        if s_trig and s_end:
            blocked_domain = s_trig.group(1)
            break

        # Tier-2: bot-agnostic 행위 완료 표현 (D82-A 신규). 도메인 word 없이도
        # action verb + 완료 종결만으로 매칭. 매칭 시 evidence 검증 후 deny.
        #
        # D82-A 사후 #E (2026-05-13) — dual-meaning stem (추가/수정/보완/작성/입력
        # /기입/업데이트/기록/완료) 은 assistant-local target ("답변에 내용을 추가
        # 했어요", "문장을 수정했습니다") 와 외부 state change 양쪽에 쓰임.
        # v2 보강 — false-negative 회피. self-referent target (답변/응답/메시지) 만
        # 단독 EXEMPT. generic-local target (내용/항목/표/문장 등) 은 sentence-level
        # anchor (아래/위/다음/이/본/앞서/제가 등) 동반 시에만 EXEMPT — "고객 정보
        # 항목을 수정했습니다" 같은 외부 객체 케이스의 false-negative 차단.
        ad_match = _GENERAL_ACTION_DONE.search(scan_sentence)
        if ad_match:
            stem = ad_match.group("stem")
            # external stem 은 가드 없이 즉시 hit.
            if re.fullmatch(_EXTERNAL_ACTION_STEM, stem):
                bot_agnostic_hit = True
                break
            # dual stem — EXEMPT 두 단계 검사.
            # v3 verdict 보강 — anchor + target 모두 *stem 직전 동일 윈도우*
            # (0-12 char) 안에 있어야 EXEMPT. sentence 다른 쪽 anchor 인정 X —
            # "아래에서 설명한 신청서 내용을 입력했습니다" 같은 외부 객체 케이스
            # false-negative 회피.
            prefix_start = max(0, ad_match.start() - 12)
            prefix = scan_sentence[prefix_start: ad_match.start()]
            # 1) self-referent target (답변/응답/메시지) 직전 위치 시 단독 EXEMPT.
            if _SELF_REFERENT_TARGET.search(prefix):
                continue
            # 2) generic-local target (내용/예시/표/항목 등) + assistant-local
            #    anchor (아래/위/제가 등) 가 *둘 다* 같은 prefix 윈도우 안에 → EXEMPT.
            if _GENERIC_LOCAL_TARGET.search(prefix) and _ASSISTANT_LOCAL_ANCHOR.search(
                prefix
            ):
                continue
            # 그 외 dual stem 매칭은 외부 state change 가능성 우세 → hit.
            bot_agnostic_hit = True
            break

    # --- 차단 판단 -----------------------------------------------------------
    if blocked_domain:
        # Tier-1 path — 도메인 매칭. D82-A:
        #   1. 매핑 *비어있음* (결제 등) → deny
        #   2. allowed_tools *비어있음* → deny
        #   3. 매핑 ∩ allowed = ∅ → deny
        domain = _normalize_domain(blocked_domain)
        needed_tools = DOMAIN_TOOL_MAP.get(domain, set())

        # D82-A 신규 — capability empty (allowed_tools 비어있으면) → deny.
        if not allowed_set:
            try:
                from src.common.metrics import inc_tool_scope_filter_hit

                inc_tool_scope_filter_hit(domain)
            except Exception:  # noqa: BLE001
                pass
            return T3_TEMPLATE.format(domain=domain)

        # D82-A 신규 — DOMAIN_TOOL_MAP 매핑 *비어있음* → fail-closed deny.
        if not needed_tools:
            try:
                from src.common.metrics import inc_tool_scope_filter_hit

                inc_tool_scope_filter_hit(domain)
            except Exception:  # noqa: BLE001
                pass
            return T3_TEMPLATE.format(domain=domain)

        # 기존 — 해당 도메인 도구 하나라도 allowed 면 통과.
        if needed_tools & allowed_set:
            return response_text

        # 차단 — T3 셀프가이드로 치환.
        try:
            from src.common.metrics import inc_tool_scope_filter_hit

            inc_tool_scope_filter_hit(domain)
        except Exception:  # noqa: BLE001
            pass
        return T3_TEMPLATE.format(domain=domain)

    if bot_agnostic_hit:
        # Tier-2 path — bot-agnostic 행위 완료 표현. evidence 없으면 deny.
        # current-turn state-change evidence (confirm_id / op_type=create+success
        # / .create/.add/.send tool + status=success) 있으면 통과.
        if _has_strong_state_evidence(tool_results):
            return response_text
        # evidence 없음 — deny.
        try:
            from src.common.metrics import inc_tool_scope_filter_hit

            inc_tool_scope_filter_hit("bot_agnostic")
        except Exception:  # noqa: BLE001
            pass
        return T3_GENERIC

    return response_text


__all__ = [
    "DOMAIN_TOOL_MAP",
    "T3_TEMPLATE",
    "T3_GENERIC",
    "scope_filter_apply",
]
