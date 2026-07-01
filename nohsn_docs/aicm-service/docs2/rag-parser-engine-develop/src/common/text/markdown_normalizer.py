"""Markdown 정합성 정규화 — heading / GFM 표 앞 빈 줄 자동 보장.

2026-05-08 사용자 보고:
    "표가 만들어질때 너가 만드는것처럼 딱 줄 맞춰서 나오는게 힘든가?
     그리고 ### 은 뭐야?"

KRX 봇 답변에 `### 1. 주문 유형` 이 raw text 로 노출되는 결함 + 표 정렬 정합성
부족 보고. 진단:
    - DB 답변 dump 결과 *대부분 답변* 은 `\\n\\n###` (CommonMark 정상 형식) 보유.
    - 일부 answer 는 `\\n###` (단일 newline) — paragraph 안 inline text 로 인식되어
      raw `###` 노출 가능. 또한 streaming 중간 partial state 에서도 raw 노출.
    - LLM 이 `### 1.` 과 `**1.**` 을 *혼용* — 일관성 X.

본 모듈은 LLM 답변 후처리에서 *결정론적* markdown 정합성 보강:
    1. ATX heading (`#`-`######` + space) 앞 빈 줄 보장.
    2. GFM 표 (header + separator 라인) 앞 빈 줄 보장.
    3. fenced code block 안은 *손대지 X* (false positive 방지).
    4. idempotent — 이미 빈 줄 있으면 no-op.
    5. 답변 첫 줄 heading 은 그대로 (앞에 newline 없음 → CommonMark 인식).

GPT-5 Phase 0 verdict (GO_WITH_CHANGES, 2026-05-08):
    - lookbehind `(?<!\\n)\\n` 가 idempotent 보장.
    - heading 치환 후 fence 위치 shift → 표 단계는 fences 재계산.
    - 표 separator regex *엄격* — `^\\|(?:\\s*:?-{3,}:?\\s*\\|)+\\s*$` 사용
      (각 column `-{3,}` 강제). 느슨한 `[\\s:|-]+` 사용 시 본문 행 + cell 라인을
      header+separator 로 오인 위험 있음.

사용자 절칙 ("하드코딩 금지") *예외* — markdown 형식은 결정론적 spec 이라 LLM
분류 X. latex_sanitizer 와 동일한 *결정론적 후처리* 모듈 카테고리.
"""
from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# 정규식
# ---------------------------------------------------------------------------

# heading 앞 빈 줄 보장 — `\\n` 1개 다음 `#{1,6} ` 매치, 단 직전 char 가 newline 이
# 아닐 때만 (즉 `\\n\\n###` 은 idempotent 로 skip).
# MULTILINE 불필요 — `\\n` 자체로 줄 시작 인식.
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\n)(\n)(#{1,6} )")

# GFM 표 — header 라인 + separator 라인 한 묶음. separator 는 *엄격*:
#   - `\\|` 로 시작.
#   - 각 column `\\s*:?-{3,}:?\\s*\\|` (대시 3개 이상, 양옆 optional `:` for 정렬).
#   - 1+ column.
#   - line 끝까지 `\\s*` 만.
# header 라인 (group 2) 은 일반 `\\|...\\|` 만 — separator 의 엄격성으로 본문 행을
# header 로 오인하는 false positive 차단.
# (?<!\\n) lookbehind 로 idempotent.
_TABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\n)(\n)(\|[^\n]+\|)\n(\|(?:\s*:?-{3,}:?\s*\|)+\s*)(?=\n|$)"
)

# fenced code block — ```lang\\n...\\n```. DOTALL 필요 (`.` 가 `\\n` 매치).
# inline code 는 backtick 한 쌍이라 `\\n` 매치 X — 무시 가능.
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def _fence_ranges(text: str) -> list[tuple[int, int]]:
    """fenced code block 위치 (start, end) 리스트."""
    return [(m.start(), m.end()) for m in _FENCE_RE.finditer(text)]


def _in_fence(pos: int, ranges: list[tuple[int, int]]) -> bool:
    """주어진 position 이 fenced block 내부인지."""
    for s, e in ranges:
        if s <= pos < e:
            return True
    return False


def normalize_markdown(text: str) -> str:
    """LLM 답변 markdown 의 heading / 표 앞 빈 줄 자동 보장.

    Args:
        text: 어시스턴트 응답 본문. 사용자 입력에는 호출 X.

    Returns:
        정규화된 본문. 입력이 빈 문자열 / heading·표 없으면 그대로.

    동작:
        1. heading (`#{1,6} `) 앞 *단일* `\\n` 을 `\\n\\n` 으로 보강.
        2. GFM 표 (header + 엄격한 separator 라인) 앞 *단일* `\\n` 을 `\\n\\n`.
        3. fenced code block (```...```) 안은 손대지 않음.
        4. 답변 첫 줄 heading (앞에 newline 자체가 없음) 은 변경 X — CommonMark
           는 첫 줄 `### ` 도 heading 으로 정상 인식.

    Idempotency:
        이미 `\\n\\n###` 인 경우 lookbehind `(?<!\\n)` 가 매치 차단 → no-op.
        n회 호출 결과 동일.

    범위:
        false positive 0 — fence 내부 스킵, 표 separator 엄격 매칭으로 본문 행
        오인 차단.
    """
    if not text:
        return text
    # fast path — heading / 표 후보 없음.
    if "#" not in text and "|" not in text:
        return text

    # 1. heading 정규화 — fence 외부만.
    fences = _fence_ranges(text)

    def _heading_sub(m: re.Match) -> str:
        if _in_fence(m.start(), fences):
            return m.group(0)
        return "\n" + m.group(1) + m.group(2)  # 추가 \\n

    text = _HEADING_RE.sub(_heading_sub, text)

    # 2. 표 정규화 — heading 추가 후 fence 위치 shift 가능 → 재계산.
    fences2 = _fence_ranges(text)

    def _table_sub(m: re.Match) -> str:
        if _in_fence(m.start(), fences2):
            return m.group(0)
        return "\n" + m.group(1) + m.group(2) + "\n" + m.group(3)

    text = _TABLE_RE.sub(_table_sub, text)
    return text


__all__ = ["normalize_markdown"]
