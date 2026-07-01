"""voice_friendly_filter — 마크다운 strip + 숫자 한글화 + 마무리 정규화."""

from __future__ import annotations

from src.agent_framework.conversation.voice_friendly_filter import (
    ensure_terminal_period,
    humanize_numbers,
    number_to_korean,
    strip_markdown,
    to_voice_friendly,
)


class TestStripMarkdown:
    def test_strips_bold_italic_code(self):
        assert strip_markdown("**bold** *ital* `code`") == "bold ital code"

    def test_strips_headers_and_bullets(self):
        text = "# 제목\n## 부제\n- 첫째\n- 둘째\n1. 셋째"
        out = strip_markdown(text)
        assert "#" not in out
        assert "- " not in out
        assert "제목" in out and "첫째" in out and "셋째" in out

    def test_strips_emoji_and_link(self):
        text = "🟢 active 출처 [공지](https://x.com/y) 입니다"
        out = strip_markdown(text)
        assert "🟢" not in out
        assert "https://" not in out
        assert "공지" in out
        assert "active 출처 공지 입니다" in out

    def test_image_markdown_to_alt(self):
        out = strip_markdown("![고양이](http://a.com/c.png) 사진")
        assert "고양이 사진" == out

    def test_code_fence_removed(self):
        out = strip_markdown("```python\nprint('hi')\n```")
        assert "print('hi')" in out
        assert "```" not in out


class TestNumberToKorean:
    def test_zero_to_99(self):
        assert number_to_korean(0) == "영"
        assert number_to_korean(7) == "칠"
        assert number_to_korean(20) == "이십"
        assert number_to_korean(15) == "십오"

    def test_thousands(self):
        assert number_to_korean(3500) == "삼천오백"
        assert number_to_korean(1234) == "천이백삼십사"

    def test_man_eok(self):
        assert "만" in number_to_korean(15000)
        assert "억" in number_to_korean(2_500_000_000)

    def test_too_large_passthrough(self):
        assert number_to_korean(10**13) == str(10**13)


class TestHumanizeNumbers:
    def test_basic_replace(self):
        out = humanize_numbers("주문 3,500원 입니다")
        assert "삼천오백" in out
        assert "3,500" not in out

    def test_disabled_passthrough(self):
        out = humanize_numbers("결제 1,000원", enabled=False)
        assert out == "결제 1,000원"

    def test_does_not_touch_word_boundary(self):
        out = humanize_numbers("v1.2 모델")
        # 1, 2 가 단어 사이에 있어 변환 안 됨
        assert "v1.2" in out


class TestEnsureTerminalPeriod:
    def test_adds_period_when_missing(self):
        assert ensure_terminal_period("안녕") == "안녕."

    def test_keeps_existing_terminator(self):
        assert ensure_terminal_period("안녕!") == "안녕!"
        assert ensure_terminal_period("안녕?") == "안녕?"
        assert ensure_terminal_period("안녕.") == "안녕."

    def test_empty_input(self):
        assert ensure_terminal_period("") == ""


class TestToVoiceFriendly:
    def test_pipeline_full(self):
        text = "**3,500원** 결제 됩니다 🟢"
        out = to_voice_friendly(text)
        assert "**" not in out
        assert "🟢" not in out
        assert "삼천오백" in out
        assert out.endswith(".") or out.endswith("다.")

    def test_humanize_disabled(self):
        out = to_voice_friendly("**3,500원**", humanize=False)
        assert "3,500원" in out
        assert "**" not in out

    def test_empty(self):
        assert to_voice_friendly("") == ""
