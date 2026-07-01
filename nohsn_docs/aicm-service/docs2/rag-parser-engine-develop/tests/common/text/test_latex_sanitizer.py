"""LaTeX → 유니코드 sanitizer 단위 테스트.

GPT-5 Phase 0 verdict (2026-05-08) 의 *반드시 통과해야 할* 결함 케이스 포함:
- 정확 토큰 매칭 (`\\le` 가 `\\leqslant` prefix 로 잘려선 안 됨).
- 통화 표기 `$100` false positive X.
- 사용자 입력 echo 시 손대지 않음 (caller 책임이지만 테스트로 강조).
- Idempotent (3회 호출 동일).
- 수식 구분자 4종 (`$...$`, `$$...$$`, `\\(...\\)`, `\\[...\\]`).
"""
from __future__ import annotations

import pytest

from src.common.text.latex_sanitizer import (
    has_unrendered_latex,
    sanitize_latex_to_unicode,
)


class TestKRXBugCase:
    """결함 사례 (KRX 봇) 회귀 테스트."""

    def test_krx_체결원칙_arrows(self) -> None:
        """KRX 봇 결함 — `$\\rightarrow$` 가 raw 로 노출."""
        original = (
            "**가격우선** $\\rightarrow$ **시간우선** $\\rightarrow$ **수량우선**"
        )
        result = sanitize_latex_to_unicode(original)
        # 모든 화살표 유니코드 변환 + $ 제거.
        assert "$\\rightarrow$" not in result
        assert result.count("→") == 2
        assert "**가격우선**" in result
        assert "**시간우선**" in result
        assert "**수량우선**" in result

    def test_krx_inline_math_to(self) -> None:
        """KRX `$\\to$` 단축형도 변환."""
        result = sanitize_latex_to_unicode("A $\\to$ B $\\to$ C")
        assert result == "A → B → C"


class TestArrowMappings:
    """3.1 화살표 매핑."""

    def test_basic_arrows(self) -> None:
        cases = [
            ("$\\rightarrow$", "→"),
            ("$\\leftarrow$", "←"),
            ("$\\Rightarrow$", "⇒"),
            ("$\\Leftarrow$", "⇐"),
            ("$\\leftrightarrow$", "↔"),
            ("$\\Leftrightarrow$", "⇔"),
            ("$\\mapsto$", "↦"),
        ]
        for original, expected in cases:
            assert sanitize_latex_to_unicode(original) == expected, (
                f"failed for {original!r}"
            )

    def test_long_arrows(self) -> None:
        """`\\longrightarrow` 가 `\\long` + 미정의 로 잘리지 않도록 (정확 토큰 매칭)."""
        assert sanitize_latex_to_unicode("$\\longrightarrow$") == "→"
        assert sanitize_latex_to_unicode("$\\Longrightarrow$") == "⇒"


class TestComparisonMappings:
    """3.2 부등호 / 비교."""

    def test_le_does_not_eat_leqq(self) -> None:
        """결정적 — `\\le` 가 `\\leqslant`(미정의) 의 prefix 로 매치 X."""
        # \leqslant 는 매핑에 없음 → 그대로 통과해야 함 (백슬래시 + cmd raw).
        result = sanitize_latex_to_unicode("$\\leqslant$")
        # \leqslant 가 \le 로 잘려 ≤slant 가 되면 결함. 그대로 또는 strip 만.
        assert "≤slant" not in result
        # \leqslant 는 매핑 미히트 → strip 후 raw 잔여.
        assert "\\leqslant" in result

    def test_le_leq_both_map(self) -> None:
        assert sanitize_latex_to_unicode("$\\le$") == "≤"
        assert sanitize_latex_to_unicode("$\\leq$") == "≤"
        assert sanitize_latex_to_unicode("$\\ge$") == "≥"
        assert sanitize_latex_to_unicode("$\\geq$") == "≥"
        assert sanitize_latex_to_unicode("$\\neq$") == "≠"
        assert sanitize_latex_to_unicode("$\\approx$") == "≈"


class TestArithmeticMappings:
    """3.3 산술."""

    def test_times_div_cdot(self) -> None:
        assert sanitize_latex_to_unicode("$5 \\times 3 = 15$") == "5 × 3 = 15"
        assert sanitize_latex_to_unicode("$10 \\div 2$") == "10 ÷ 2"
        assert sanitize_latex_to_unicode("$a \\cdot b$") == "a · b"

    def test_pm_mp(self) -> None:
        assert sanitize_latex_to_unicode("$x \\pm 1$") == "x ± 1"


class TestGreekMappings:
    """3.4 그리스 문자."""

    def test_lowercase_greek(self) -> None:
        assert sanitize_latex_to_unicode("$\\alpha + \\beta$") == "α + β"
        assert sanitize_latex_to_unicode("$\\pi r^2$") == "π r^2"

    def test_uppercase_greek(self) -> None:
        assert sanitize_latex_to_unicode("$\\Sigma \\Delta$") == "Σ Δ"


class TestSetLogicMappings:
    """3.5 집합 / 논리."""

    def test_infinity_emptyset(self) -> None:
        assert sanitize_latex_to_unicode("$\\infty$") == "∞"
        assert sanitize_latex_to_unicode("$\\emptyset$") == "∅"

    def test_in_subset(self) -> None:
        assert sanitize_latex_to_unicode("$x \\in A$") == "x ∈ A"
        assert sanitize_latex_to_unicode("$A \\subset B$") == "A ⊂ B"


class TestBigOperators:
    """3.6 큰 연산자."""

    def test_sum_int(self) -> None:
        assert sanitize_latex_to_unicode("$\\sum$") == "∑"
        assert sanitize_latex_to_unicode("$\\int_0^1$") == "∫_0^1"


class TestMathDelimiters:
    """수식 구분자 4종."""

    def test_inline_dollar(self) -> None:
        assert sanitize_latex_to_unicode("text $\\alpha$ end") == "text α end"

    def test_block_dollar(self) -> None:
        assert sanitize_latex_to_unicode("text $$\\alpha$$ end") == "text α end"

    def test_inline_paren(self) -> None:
        assert sanitize_latex_to_unicode("text \\(\\alpha\\) end") == "text α end"

    def test_block_bracket(self) -> None:
        assert sanitize_latex_to_unicode("text \\[\\alpha\\] end") == "text α end"


class TestFalsePositives:
    """수식 구분자 *밖* 본문은 손대지 않음 — false positive 차단."""

    def test_currency_dollar_not_converted(self) -> None:
        """`$100` 같은 통화 표기 — 단일 $ 는 수식 구분자 X."""
        original = "가격은 $100 입니다."
        # `$100 입니다.` 는 한 쌍의 `$` 로 보일 수도 있는데, `\n` 또는 `$` 종결 없으면
        # regex 매치 X (negative lookahead). 결과는 그대로.
        result = sanitize_latex_to_unicode(original)
        assert "$100" in result

    def test_text_outside_math_untouched(self) -> None:
        """수식 구분자 밖 본문은 변환 X."""
        original = "문서 작성 시 \\rightarrow 화살표를 사용하세요."
        result = sanitize_latex_to_unicode(original)
        # 본문 (수식 구분자 밖) 의 \rightarrow 는 raw 로 유지.
        assert "\\rightarrow" in result

    def test_korean_text_preserved(self) -> None:
        """한국어 본문 — 그대로 통과."""
        original = "**가격우선** $\\rightarrow$ **시간우선**"
        result = sanitize_latex_to_unicode(original)
        assert "**가격우선**" in result
        assert "**시간우선**" in result


class TestIdempotency:
    """3회 호출 결과 동일 — 이미 유니코드면 no-op."""

    def test_already_unicode(self) -> None:
        original = "**가격우선** → **시간우선** → **수량우선**"
        result = sanitize_latex_to_unicode(original)
        assert result == original

    def test_three_round_trips(self) -> None:
        original = "$\\rightarrow$ $\\le$ $\\alpha$"
        first = sanitize_latex_to_unicode(original)
        second = sanitize_latex_to_unicode(first)
        third = sanitize_latex_to_unicode(second)
        assert first == second == third
        assert first == "→ ≤ α"


class TestStripDelimitersFlag:
    """``strip_math_delimiters=False`` (Web KaTeX 채널용) — 구분자 보존."""

    def test_preserve_delimiters(self) -> None:
        result = sanitize_latex_to_unicode(
            "$\\rightarrow$", strip_math_delimiters=False
        )
        assert result == "$→$"

    def test_preserve_unmapped_latex(self) -> None:
        """매핑 없는 식 (`\\frac{a}{b}`) 은 그대로 + 구분자 보존."""
        result = sanitize_latex_to_unicode(
            "$\\frac{a}{b}$", strip_math_delimiters=False
        )
        assert result == "$\\frac{a}{b}$"


class TestUnmappedLatex:
    """매핑에 없는 LaTeX 는 raw 유지 (caller 가 채널별 fallback)."""

    def test_complex_frac(self) -> None:
        """`\\frac{a}{b}` 는 매핑에 없음 — strip 모드에선 구분자만 제거."""
        result = sanitize_latex_to_unicode("$\\frac{a}{b}$")
        # \frac 는 매핑 X — raw 잔여 + $ 제거.
        assert "\\frac" in result
        assert "$" not in result

    def test_has_unrendered_latex(self) -> None:
        """미변환 LaTeX detect helper."""
        assert has_unrendered_latex("\\frac{a}{b}")
        assert has_unrendered_latex("$\\frac{a}{b}$")
        assert not has_unrendered_latex("→ ≤ α")  # 모두 유니코드.
        assert not has_unrendered_latex("hello world")
        assert not has_unrendered_latex("")


class TestRealWorldCases:
    """5 봇 실제 답변 sample."""

    def test_krx_체결원칙_full_paragraph(self) -> None:
        """KRX 봇 답변 paragraph — 화살표 + bold + 한국어 모두 보존."""
        original = (
            "거래소 매매 체결은 다음 우선순위로 진행됩니다.\n\n"
            "**가격우선** $\\rightarrow$ **시간우선** $\\rightarrow$ **수량우선**\n\n"
            "이때 가격이 같다면 먼저 호가한 주문이 우선됩니다."
        )
        result = sanitize_latex_to_unicode(original)
        assert "$\\rightarrow$" not in result
        assert "→" in result
        assert "**가격우선**" in result
        assert "거래소 매매 체결" in result
        assert "먼저 호가한 주문이 우선됩니다." in result

    def test_mixed_arrows_and_bold(self) -> None:
        """본문 안 markdown bold 가 보존 (sanitize 가 markdown 손상 X)."""
        original = "절차: **STEP1** $\\Rightarrow$ **STEP2**"
        result = sanitize_latex_to_unicode(original)
        assert result == "절차: **STEP1** ⇒ **STEP2**"

    def test_multiple_math_blocks(self) -> None:
        """여러 수식 블록 각각 독립 변환."""
        original = "1) $\\alpha$ 2) $\\beta$ 3) $\\gamma$"
        result = sanitize_latex_to_unicode(original)
        assert result == "1) α 2) β 3) γ"


class TestGPT5Phase1Fixes:
    """GPT-5 Phase 1 verdict §2 / §1 fix 회귀."""

    def test_currency_pair_not_matched_as_math(self) -> None:
        """`가격은 $100 부터 $200 입니다` — 두 개의 `$` 가 짝으로 잘못 math 로
        잡히면 안 됨. 백슬래시 command 가 없으면 math 아님.
        """
        original = "가격은 $100 부터 $200 입니다."
        result = sanitize_latex_to_unicode(original)
        # 내용 보존 — 통화 표기 손상 X.
        assert "$100" in result
        assert "$200" in result
        assert "가격은" in result
        assert "입니다" in result

    def test_inline_math_with_command_still_works(self) -> None:
        """`가격은 $100 → $200 으로 $\\to$ 변경` — 진짜 math 인 `$\\to$` 만 변환."""
        original = "가격은 $100 → $200 으로 $\\to$ 변경"
        result = sanitize_latex_to_unicode(original)
        # `$100`, `$200` 통화는 보존, `$\to$` 만 → 으로 변환.
        assert "$100" in result
        assert "$200" in result
        # `\to` 변환 → `→`.
        assert result.count("→") >= 2  # 본문 → + 변환 →

    def test_block_math_no_command_still_strips(self) -> None:
        """block (`$$X$$`) / `\\(X\\)` 는 명시적이라 command 없어도 strip OK."""
        # `$$ABC$$` — 비록 command 없어도 명시적 block 이라 strip.
        result = sanitize_latex_to_unicode("$$x = 5$$")
        assert "$$" not in result
        assert "x = 5" in result

    def test_sqrt_command_not_in_mapping(self) -> None:
        """`\\sqrt` 는 매핑 제외 (KaTeX 채널 보존). raw 잔여."""
        # strip 모드 — $ 만 제거되고 \sqrt 잔여.
        result = sanitize_latex_to_unicode("$\\sqrt{x}$")
        assert "\\sqrt" in result
        assert "$" not in result
        # 보존 모드 (KaTeX) — 그대로 통과.
        result_kx = sanitize_latex_to_unicode(
            "$\\sqrt{x}$", strip_math_delimiters=False
        )
        assert result_kx == "$\\sqrt{x}$"


class TestEdgeCases:
    """경계 케이스."""

    def test_empty_string(self) -> None:
        assert sanitize_latex_to_unicode("") == ""

    def test_whitespace_only(self) -> None:
        assert sanitize_latex_to_unicode("   \n\t") == "   \n\t"

    def test_no_math_no_change(self) -> None:
        plain = "안녕하세요. 단순한 한국어 본문입니다."
        assert sanitize_latex_to_unicode(plain) == plain

    def test_nested_math_not_supported_but_safe(self) -> None:
        """`$a$ 와 $b$` — 백슬래시 command 없으면 math 아님 (GPT-5 §2 fix).

        통화/단순 변수 표기 보호 — body 안 LaTeX command 없으면 raw 유지.
        """
        result = sanitize_latex_to_unicode("$a$ 와 $b$")
        # _looks_like_math 휴리스틱 — body 에 \ 없으면 math 아님.
        assert result == "$a$ 와 $b$"

    def test_inline_with_backslash_cmd_does_strip(self) -> None:
        """`$\\alpha$` — body 에 백슬래시 command 있어 진짜 math → strip + 변환."""
        assert sanitize_latex_to_unicode("$\\alpha$") == "α"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
