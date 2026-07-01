"""Voice-friendly filter — TTS 친화 텍스트 변환.

§C #5 (음성 친화 답변) — 마크다운 strip + 숫자 한글화 + 짧은 문장 분리.

변환 규칙:
 - **bold** / *italic* / `code` / # 헤더 / - 불릿 → 평문
 - 이모지 (Emoji block) 제거
 - URL / `[label](url)` → label 만 (URL 은 음성에 부적합)
 - 천 단위 콤마 (1,234) → 숫자 그대로 (한글화 옵션)
 - 4자리 이하 정수 → 한글 ("3500" → "삼천오백")
 - 응답 끝 마침표 보장
 - 마지막에 white space 정규화
"""

from __future__ import annotations

import re

# 한국어 숫자 변환 — 4 자리 이하 정수만 정확.
_ONES = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_PLACES = ["", "십", "백", "천"]
_BIGS = [(10**8, "억"), (10**4, "만"), (1, "")]


def _under_10000_to_korean(n: int) -> str:
    """0~9999 정수를 한글로. 0 → "영"."""
    if n == 0:
        return "영"
    out: list[str] = []
    digits = str(n).rjust(4, "0")
    for i, ch in enumerate(digits):
        d = int(ch)
        place = _PLACES[3 - i]
        if d == 0:
            continue
        # 1 의 십/백/천 자리는 그냥 "십/백/천" (한국어 관례)
        if d == 1 and place in ("십", "백", "천"):
            out.append(place)
        else:
            out.append(_ONES[d] + place)
    return "".join(out)


def number_to_korean(n: int) -> str:
    """0~9억 미만 정수 한글 변환. 음수 / 큰 수는 그대로 str(n)."""
    if n < 0 or n >= 10**12:
        return str(n)
    if n < 10000:
        return _under_10000_to_korean(n)
    parts: list[str] = []
    remaining = n
    for unit, label in _BIGS:
        if remaining >= unit:
            chunk = remaining // unit
            remaining = remaining % unit
            if chunk > 0:
                if unit == 1:
                    parts.append(_under_10000_to_korean(chunk))
                else:
                    # 1만/1억 은 "만"/"억" 으로 약식
                    if chunk == 1:
                        parts.append(label)
                    else:
                        parts.append(_under_10000_to_korean(chunk) + label)
    return "".join(parts) or "영"


_NUM_RE = re.compile(
    # 숫자 양쪽이 영문/숫자/마침표/언더스코어/하이픈이 아닌 경계여야만 변환.
    # ASCII boundary 만 — Korean 같은 unicode word char (예: "원") 는 boundary 로 취급.
    # 예: "v1.2" 의 1, 2 / "8-bit" 의 8 / "id_4" 의 4 는 매치되지 않음.
    # 예: "3,500원" 의 3,500 은 매치 (원 은 ASCII word 가 아니므로).
    r"(?<![A-Za-z0-9_.\-])(\d{1,3}(?:,\d{3})+|\d+)(?![A-Za-z0-9_.\-])"
)


def humanize_numbers(text: str, *, enabled: bool = True) -> str:
    """텍스트의 숫자 토큰을 한글 (천/만/억) 표기로 치환.

    - "3,500" → "삼천오백"
    - "1234"  → "천이백삼십사"
    - 너무 큰 숫자(>=10^12)는 그대로 보존.
    - 토큰 경계는 단어 경계 — "v1.2" 의 1, 2 는 매칭 안 됨 (앞뒤 \\w 거름).
    - enabled=False 면 입력 그대로 반환 (toggle 호환).
    """
    if not enabled or not text:
        return text

    def _conv(m: re.Match) -> str:
        raw = m.group(1).replace(",", "")
        try:
            n = int(raw)
        except ValueError:
            return m.group(0)
        return number_to_korean(n)

    return _NUM_RE.sub(_conv, text)


# 이모지 + 픽토그램 + 심볼 블록 (Unicode)
_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F000-\U0001F1FF" "]+",
    flags=re.UNICODE,
)


def strip_markdown(text: str) -> str:
    """마크다운 마크업·이모지·이미지·URL·헤더·불릿을 음성용 평문으로 변환."""
    if not text:
        return ""
    s = text
    # code fence ``` ... ``` → 본문만
    s = re.sub(r"```[\w-]*\n?", "", s)
    s = re.sub(r"```", "", s)
    # 이미지 ![alt](url) → alt
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    # 링크 [label](url) → label
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    # 인라인 코드 `code` → code
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # bold/italic
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", s)
    # 헤더 # …
    s = re.sub(r"^\s{0,3}#+\s*", "", s, flags=re.M)
    # 불릿
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.M)
    s = re.sub(r"^\s*\d+\.\s+", "", s, flags=re.M)
    # 인용
    s = re.sub(r"^\s*>+\s*", "", s, flags=re.M)
    # HR
    s = re.sub(r"^\s*[-*_]{3,}\s*$", "", s, flags=re.M)
    # URL 노출 (음성에 부적합) — http(s)://... 제거
    s = re.sub(r"https?://\S+", "", s)
    # 이모지
    s = _EMOJI_RE.sub("", s)
    # 다중 공백/개행 정규화
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def ensure_terminal_period(text: str) -> str:
    """응답 끝 마침표 보장 (TTS 자연스러운 마무리)."""
    if not text:
        return text
    last = text.rstrip()[-1] if text.rstrip() else ""
    if last and last not in ".!?。…":
        return text.rstrip() + "."
    return text


def to_voice_friendly(text: str, *, humanize: bool = True) -> str:
    """전체 voice-friendly 변환 파이프라인.

    Parameters
    ----------
    text : str
        원본 응답 (마크다운 가능).
    humanize : bool
        숫자 한글화 활성 여부. False 면 마크다운 strip 만 적용.
    """
    if not text:
        return ""
    s = strip_markdown(text)
    if humanize:
        s = humanize_numbers(s)
    s = ensure_terminal_period(s)
    return s
