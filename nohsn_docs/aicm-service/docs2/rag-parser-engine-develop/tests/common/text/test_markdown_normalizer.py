"""markdown_normalizer 단위 테스트.

GPT-5 Phase 0 verdict 반영 — false positive / idempotent / 표 separator 엄격.
"""
from __future__ import annotations

from src.common.text.markdown_normalizer import normalize_markdown


class TestHeading:
    def test_heading_after_paragraph_gets_blank_line(self) -> None:
        """paragraph + heading 형식 — 빈 줄 1개 자동 추가."""
        text = "본문입니다.\n### 1. 제목\n다음 본문."
        out = normalize_markdown(text)
        assert "\n\n### 1. 제목" in out
        assert out == "본문입니다.\n\n### 1. 제목\n다음 본문."

    def test_heading_already_has_blank_line_idempotent(self) -> None:
        """이미 `\\n\\n###` 인 경우 변경 X (lookbehind)."""
        text = "본문.\n\n### 제목\n뒷 본문."
        out = normalize_markdown(text)
        assert out == text  # 변경 X

    def test_heading_re_normalize_idempotent(self) -> None:
        """한 번 normalize 한 결과를 재호출해도 빈 줄이 3개 X."""
        text = "본문.\n### 제목\n본문2."
        once = normalize_markdown(text)
        twice = normalize_markdown(once)
        assert once == twice
        assert "\n\n\n" not in twice

    def test_first_line_heading_unchanged(self) -> None:
        """답변 첫 줄 heading — 앞에 `\\n` 자체가 없음. 변경 X."""
        text = "### 제목\n본문."
        out = normalize_markdown(text)
        assert out == text

    def test_h1_to_h6_all_levels(self) -> None:
        """h1-h6 모두 정상 처리."""
        for level in range(1, 7):
            hashes = "#" * level
            text = f"본문.\n{hashes} 제목"
            out = normalize_markdown(text)
            assert f"\n\n{hashes} 제목" in out

    def test_hash_inside_paragraph_not_touched(self) -> None:
        """문단 안 `#tag` 같은 hash 는 heading 아님 (뒤에 space 없음)."""
        text = "본문 #tag 입니다.\n### 진짜 제목"
        out = normalize_markdown(text)
        # `#tag` 앞 빈 줄은 추가되지 X (space 없음 → heading 아님).
        # `### 진짜 제목` 앞에는 빈 줄 추가됨.
        assert "\n\n### 진짜 제목" in out


class TestTable:
    def test_table_after_paragraph_gets_blank_line(self) -> None:
        """paragraph 다음 GFM 표 — 빈 줄 추가."""
        text = (
            "본문입니다.\n"
            "| 이름 | 나이 |\n"
            "| :--- | :---: |\n"
            "| Ricky | 30 |"
        )
        out = normalize_markdown(text)
        assert "\n\n| 이름 | 나이 |" in out

    def test_table_already_has_blank_line_idempotent(self) -> None:
        """이미 `\\n\\n|...|` 인 경우 변경 X."""
        text = (
            "본문.\n\n"
            "| 컬럼 |\n"
            "| :---: |\n"
            "| 값 |"
        )
        out = normalize_markdown(text)
        assert out == text

    def test_loose_separator_not_treated_as_table(self) -> None:
        """separator 가 `:--:` (대시 2개) 처럼 *느슨* 하면 표로 인식 X.

        GPT-5 Phase 0 verdict §3 — 본문 행을 header 로 오인하는 결함 차단.
        """
        # 대시 2개 — 표 아님 (보통 텍스트 아트).
        text = "본문.\n| a | b |\n| -- | -- |\n| 1 | 2 |"
        out = normalize_markdown(text)
        # 변경 없어야 함 (separator strict 매치 실패).
        assert out == text

    def test_strict_separator_with_alignment(self) -> None:
        """`:---:` (centered) / `:---` (left) / `---:` (right) 모두 인식."""
        text = (
            "본문.\n"
            "| L | C | R |\n"
            "| :--- | :---: | ---: |\n"
            "| a | b | c |"
        )
        out = normalize_markdown(text)
        assert "\n\n| L | C | R |\n| :--- | :---: | ---: |" in out


class TestFenceProtection:
    def test_heading_inside_fence_not_touched(self) -> None:
        """fenced code block 안의 `### text` 는 변경 X (코드 의미 보존)."""
        text = "본문.\n```python\n# comment\n### NOT a heading\n```\n다음."
        out = normalize_markdown(text)
        # fence 안 `### NOT a heading` 앞에는 빈 줄 추가 X.
        assert "\n\n### NOT a heading" not in out
        # fence 자체는 그대로.
        assert "```python\n# comment\n### NOT a heading\n```" in out

    def test_table_inside_fence_not_touched(self) -> None:
        """fenced code block 안의 `|sep|` 표 시뮬은 손 안 댐."""
        text = (
            "본문.\n```\n"
            "| a | b |\n"
            "| :---: | :---: |\n"
            "| 1 | 2 |\n"
            "```"
        )
        out = normalize_markdown(text)
        # fence 안에 빈 줄 추가 X.
        assert "\n\n| a | b |" not in out


class TestRealKRXAnswer:
    def test_krx_answer_full_paragraph(self) -> None:
        """KRX 봇 답변 형태 (2026-05-08 사용자 보고).

        원본 dump 기준 — `\\n\\n###` 이미 정상 형식이라 *변경 없음* 이 정답.
        """
        text = (
            "KRX(한국거래소) 및 코스닥에서 사용되는 주요 주문 유형과 그 특징에 대해 안내해 드릴게요. [1] [3]\n\n"
            "주문 유형은 크게 가격 지정 여부와 체결 조건에 따라 다음과 같이 구분할 수 있습니다.\n\n"
            "### 1. 기본 주문 유형\n"
            "가장 일반적으로 사용되는 주문 방식입니다.\n"
            "- **보통(지정가)**: 투자자가 지정한 가격 또는 그보다 유리한 가격으로 체결하고자 하는 주문이에요.\n\n"
            "### 4. 주문 가능 시간 안내\n"
            "주문 유형에 따라 이용 가능한 시간대가 다르니 주의가 필요합니다.\n\n"
            "| 주문 유형 | 08:30 ~ 09:00 | 09:00 ~ 15:20 | 15:20 ~ 15:30 |\n"
            "| :--- | :---: | :---: | :---: |\n"
            "| 보통 / 시장가 / 스톱지정가 | O | O | O |"
        )
        out = normalize_markdown(text)
        # 이미 빈 줄 정상 — idempotent.
        assert out == text

    def test_krx_answer_missing_blank_line(self) -> None:
        """KRX 봇 답변 변형 — heading 앞 단일 `\\n` 만 있는 결함 케이스."""
        text = (
            "주문 유형은 다음과 같이 구분할 수 있습니다.\n"
            "### 1. 기본 주문 유형\n"
            "가장 일반적으로 사용되는 주문 방식입니다.\n"
            "| 컬럼A | 컬럼B |\n"
            "| :---: | :---: |\n"
            "| 1 | 2 |"
        )
        out = normalize_markdown(text)
        # heading 앞 빈 줄 추가.
        assert "\n\n### 1. 기본 주문 유형" in out
        # 표 앞 빈 줄 추가.
        assert "\n\n| 컬럼A | 컬럼B |" in out


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert normalize_markdown("") == ""

    def test_no_markdown_chars(self) -> None:
        text = "그냥 평문 답변입니다. 표나 heading 없음."
        assert normalize_markdown(text) == text

    def test_only_heading_no_other_content(self) -> None:
        text = "### 단일 heading"
        assert normalize_markdown(text) == text  # 첫 줄 heading 유지.

    def test_heading_with_emoji_unicode(self) -> None:
        """heading 텍스트가 유니코드 (한글/이모지) 도 처리."""
        text = "본문.\n## 한글 제목"
        out = normalize_markdown(text)
        assert "\n\n## 한글 제목" in out
