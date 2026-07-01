"""LaTeX → 유니코드 결정론적 변환 (멀티채널 sanitizer).

2026-05-08 D18-v2 — 사용자 명시:
    "C로 해야 되는거 아닌가? 그리고 텔레그램도 같은 문제니까 같이 묶어서
     다양한 모양으로 표현이 될수 있도록 해야지."

KRX 봇 답변에 ``$\\rightarrow$`` raw 노출 결함 — Web (KaTeX 미설치) /
Telegram (MarkdownV2 LaTeX 미지원) 모두 동일. 본 모듈은 *결정론적 매핑*
으로 LaTeX command 를 유니코드로 변환해 *모든 채널* 에 평문 가독성 확보.

GPT-5 Phase 0 verdict 반영 (GO_WITH_CHANGES, 2026-05-08):
- 정확 토큰 매칭 (단어 경계) — `\\le` 가 `\\leqslant` 의 prefix 가 아니도록.
- 변환 범위는 `$…$` / `$$…$$` / `\\(...\\)` / `\\[...\\]` 안만 (통화 $100 false positive 차단).
- 변환 후 수식 구분자 ($, \\(, \\), \\[, \\]) 제거 (평문화).
- 사용자 입력에는 적용 X — *어시스턴트 응답 본문에만* 호출자 책임.
- Idempotent — 이미 유니코드면 no-op (재호출 안전).

설계 원칙:
- "하드코딩 금지" 절칙은 *LLM 분류 / 키워드 enum 으로 답변 결정* 에 한정.
  본 mapping 은 LaTeX command → 유니코드 *결정론적 일대일* 변환 (LLM 분류 X)
  이므로 사용자 절칙 *예외* (사용자 spec 명시).
- mapping table 은 길이 내림차순 정렬 — `\\leftrightarrow` 가 `\\leftarrow`
  보다 먼저 매치되도록.
"""
from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# 매핑 테이블 — LaTeX command → 유니코드.
# 길이 내림차순 정렬 (longest-first 매칭). 정확 토큰 매칭 (`\\le` 가 `\\leqslant`
# prefix 로 매치되지 X — regex 의 word-boundary 가 보장).
# ---------------------------------------------------------------------------

_LATEX_TO_UNICODE: Final[dict[str, str]] = {
    # 화살표 (3.1)
    "rightarrow": "→",
    "leftarrow": "←",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "leftrightarrow": "↔",
    "Leftrightarrow": "⇔",
    "uparrow": "↑",
    "downarrow": "↓",
    "Uparrow": "⇑",
    "Downarrow": "⇓",
    "to": "→",
    "gets": "←",
    "implies": "⇒",
    "iff": "⇔",
    "longrightarrow": "→",
    "longleftarrow": "←",
    "Longrightarrow": "⇒",
    "Longleftarrow": "⇐",
    "mapsto": "↦",

    # 부등호 / 비교 (3.2)
    "le": "≤",
    "leq": "≤",
    "leqq": "≤",
    "ge": "≥",
    "geq": "≥",
    "geqq": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "equiv": "≡",
    "sim": "∼",
    "simeq": "≃",
    "cong": "≅",
    "propto": "∝",
    "ll": "≪",
    "gg": "≫",

    # 산술 연산자 (3.3)
    "times": "×",
    "div": "÷",
    "cdot": "·",
    "cdots": "⋯",
    "ldots": "…",
    "vdots": "⋮",
    "ddots": "⋱",
    "pm": "±",
    "mp": "∓",
    "ast": "∗",
    "star": "⋆",
    "circ": "∘",
    "bullet": "•",
    "oplus": "⊕",
    "otimes": "⊗",
    "ominus": "⊖",
    "odot": "⊙",

    # 그리스 문자 - 소문자 (3.4)
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "omicron": "ο",
    "pi": "π",
    "varpi": "ϖ",
    "rho": "ρ",
    "varrho": "ϱ",
    "sigma": "σ",
    "varsigma": "ς",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",

    # 그리스 문자 - 대문자
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",

    # 집합 / 논리 (3.5)
    "infty": "∞",
    "emptyset": "∅",
    "varnothing": "∅",
    "in": "∈",
    "notin": "∉",
    "ni": "∋",
    "subset": "⊂",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "cup": "∪",
    "cap": "∩",
    "setminus": "∖",
    "forall": "∀",
    "exists": "∃",
    "nexists": "∄",
    "neg": "¬",
    "lnot": "¬",
    "land": "∧",
    "wedge": "∧",
    "lor": "∨",
    "vee": "∨",

    # 큰 연산자 (3.6)
    "sum": "∑",
    "prod": "∏",
    "coprod": "∐",
    "int": "∫",
    "iint": "∬",
    "iiint": "∭",
    "oint": "∮",
    "bigcup": "⋃",
    "bigcap": "⋂",
    "bigvee": "⋁",
    "bigwedge": "⋀",

    # 기타 자주 쓰이는 기호
    "partial": "∂",
    "nabla": "∇",
    # NOTE: `\sqrt` 는 매핑 *제외* (GPT-5 Phase 1 §1) — `\sqrt{x}` 는 인수 가
    # 따라오는 함수형 명령 이라 단순 치환하면 `√{x}` 같이 어색해지고, 특히
    # ``strip_math_delimiters=False`` (Web KaTeX) 경로에서 KaTeX 가 못 파싱.
    # 미매핑 잔여 → 평문 채널은 raw 유지, KaTeX 채널은 정상 렌더.
    "angle": "∠",
    "perp": "⊥",
    "parallel": "∥",
    "degree": "°",
    "prime": "′",
    "dagger": "†",
    "ddagger": "‡",
    "checkmark": "✓",
    "hbar": "ℏ",
    "ell": "ℓ",
    "Re": "ℜ",
    "Im": "ℑ",
    "aleph": "ℵ",
    "wp": "℘",
}


# ---------------------------------------------------------------------------
# 변환 정규식 — *수식 구분자 안에서만* 매핑 적용 (false positive 차단).
# ---------------------------------------------------------------------------

# 수식 구분자 — 4 종 지원 (GPT-5 verdict §8.4):
# - $...$ (inline)
# - $$...$$ (block)
# - \(...\) (LaTeX inline)
# - \[...\] (LaTeX block)
#
# regex 는 *비탐욕* 매치 — 본문에 여러 수식이 있어도 각각 분리 처리.
# `$$` 가 `$` 보다 먼저 매치되도록 longest-first.

# block first (더 긴 패턴), then inline.
_MATH_DELIMITER_RE = re.compile(
    r"\$\$(?P<block_dollar>.+?)\$\$"
    r"|\$(?P<inline_dollar>[^$\n]+?)\$"
    r"|\\\[(?P<block_paren>.+?)\\\]"
    r"|\\\((?P<inline_paren>.+?)\\\)",
    re.DOTALL,
)

# LaTeX command — 백슬래시 + 알파벳 1+ + (뒤에 알파벳이 없을 때만 매치).
# negative lookahead `(?![A-Za-z])` 가 *정확 토큰* 보장 — `\le` 가 `\leqslant`
# 를 prefix 로 잘라먹지 않도록.
_LATEX_CMD_RE = re.compile(r"\\(?P<cmd>[A-Za-z]+)(?![A-Za-z])")


def _convert_latex_commands(math_body: str) -> tuple[str, bool]:
    """수식 구분자 *안* 의 LaTeX command 를 유니코드로 변환.

    Args:
        math_body: 수식 구분자 안 raw text.

    Returns:
        (변환된 텍스트, 모든 LaTeX command 가 매핑에 hit 했는지).
        후자가 False 면 caller 가 평문화 (구분자 strip) 시 남은 LaTeX 가 raw 로 보임.
    """
    all_matched = True

    def _sub(m: re.Match) -> str:
        nonlocal all_matched
        cmd = m.group("cmd")
        unicode_char = _LATEX_TO_UNICODE.get(cmd)
        if unicode_char is None:
            all_matched = False
            return m.group(0)  # 미매핑은 그대로 (caller 가 결정).
        return unicode_char

    converted = _LATEX_CMD_RE.sub(_sub, math_body)
    return converted, all_matched


def _looks_like_math(body: str) -> bool:
    """`$...$` 안 본문이 *진짜 수식* 인지 휴리스틱 검사.

    GPT-5 Phase 1 verdict §2 결정적 fix — `가격은 $100 ... $200` 같은 통화 페어가
    하나의 inline math 로 잘못 매치돼 평문화되는 결함 차단.

    조건: body 에 *백슬래시 LaTeX command* 가 1개 이상 있어야 함. 단순
    숫자/한글 본문 (`100 입니다. ... 200`) 은 math 로 인정 X.

    block math (`$$...$$`, `\\(...\\)`, `\\[...\\]`) 는 명시적 구분자라
    추가 검증 X — 사용자가 명백히 수식 의도.
    """
    if not body:
        return False
    return bool(_LATEX_CMD_RE.search(body))


def sanitize_latex_to_unicode(text: str, *, strip_math_delimiters: bool = True) -> str:
    """LaTeX command 를 유니코드로 변환 + (옵션) 수식 구분자 제거.

    GPT-5 Phase 0 verdict 반영 (GO_WITH_CHANGES, 2026-05-08).

    동작:
    1. 본문에서 수식 구분자 (`$…$`, `$$…$$`, `\\(…\\)`, `\\[…\\]`) 를 찾음.
    2. 각 수식 안의 LaTeX command 를 매핑 테이블로 유니코드 치환.
    3. ``strip_math_delimiters=True`` (기본) 면 변환 후 구분자 제거 (평문화).
       Web KaTeX 채널은 ``False`` 로 호출 (구분자 보존 → KaTeX 가 렌더).

    Args:
        text: 어시스턴트 응답 본문 (markdown). 사용자 입력에는 호출 X.
        strip_math_delimiters: True 면 구분자 제거. False 면 보존
            (KaTeX 활성 채널용).

    Returns:
        변환된 본문. 입력이 빈 문자열이면 그대로.

    Idempotency:
        이미 유니코드 (`→`, `≤`) 인 본문에 재호출 → no-op (LaTeX command
        부재로 변환 대상 X). 3회 호출 결과 동일.

    범위:
        수식 구분자 *밖* 의 본문은 손대지 않음. 통화 표기 `$100`,
        본문 안 `\\backslash` 등 false positive 차단.
    """
    if not text or "$" not in text and "\\" not in text:
        # fast path — math 구분자 후보 없음.
        return text

    def _replace_math(m: re.Match) -> str:
        # 어느 그룹이 매치됐는지 — 비어있지 않은 그룹 1개만 검사.
        body: str | None = None
        delim_pair: tuple[str, str] = ("$", "$")  # 기본 inline.
        is_inline_dollar = False
        if m.group("block_dollar") is not None:
            body = m.group("block_dollar")
            delim_pair = ("$$", "$$")
        elif m.group("inline_dollar") is not None:
            body = m.group("inline_dollar")
            delim_pair = ("$", "$")
            is_inline_dollar = True
        elif m.group("block_paren") is not None:
            body = m.group("block_paren")
            delim_pair = ("\\[", "\\]")
        elif m.group("inline_paren") is not None:
            body = m.group("inline_paren")
            delim_pair = ("\\(", "\\)")
        if body is None:
            return m.group(0)

        # GPT-5 Phase 1 verdict §2 — `$...$` (inline dollar) 만 휴리스틱 검증.
        # 통화 페어 (`가격은 $100 ... $200 입니다`) 가 잘못 math 로 잡혀 평문화
        # 되는 결함 차단. body 안 백슬래시 command 가 *없으면* math 아님 → 그대로.
        # block math / `\(\)` / `\[\]` 는 명시적이라 검증 skip.
        if is_inline_dollar and not _looks_like_math(body):
            return m.group(0)

        converted, _all_matched = _convert_latex_commands(body)
        if strip_math_delimiters:
            # 평문화 — 구분자 제거. 잔여 LaTeX 는 그대로 raw 로 보임 (caller
            # 가 채널별 추가 fallback 결정).
            return converted
        # KaTeX 채널 — 구분자 보존 + 변환된 body. (단순 화살표 등 유니코드만
        # 본문에 보여도 시각적으로 동일 — 구분자만 보존하면 KaTeX 도 안전.)
        return f"{delim_pair[0]}{converted}{delim_pair[1]}"

    return _MATH_DELIMITER_RE.sub(_replace_math, text)


def has_unrendered_latex(text: str) -> bool:
    """본문에 *미변환 LaTeX command* (백슬래시 + 알파벳) 가 남아있는지 검사.

    sanitize 후에도 매핑에 없는 LaTeX (`\\frac{a}{b}` 등) 는 raw 로 남음.
    Telegram / KakaoWork 같은 KaTeX 미지원 채널이 이 함수로 *후처리 fallback*
    필요 여부 판단.

    수식 구분자 안 / 밖 모두 검사 — 구분자 제거 후에도 잔여 LaTeX 있으면 True.
    """
    if not text:
        return False
    return bool(_LATEX_CMD_RE.search(text))


__all__ = ["sanitize_latex_to_unicode", "has_unrendered_latex"]
