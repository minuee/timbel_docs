"""D85c-잔존 (2026-05-13) — stage2_segment prompt 의 N-column 도표 / page boundary
규칙 회귀 가드.

사용자 보고 결함 5 (N-column 박스형 도표가 numbered_list 로 mis-classify) +
결함 3 (numbered_list 가 page boundary 에서 부모 제목 누락한 채 분리) 의
prompt 강화 commit 후 *strucutural rule* 이 prompt 안에 보존되는지 직접 검증.

prompt 자체는 vision LLM 으로 전송되어 결과 chunk 가 생성되므로 *실제 인식률*
검증은 별도 evaluation harness (Phase D reprocess) 영역. 본 test 는 *prompt
template 내용* 의 회귀만 가드.
"""
from __future__ import annotations

from src.pipeline.stages.stage2_segment import _STAGE2_PROMPT_TEMPLATE


class TestNColumnBoxTablePrompt:
    """N-column 박스형 도표 분류 규칙이 prompt 에 명시되어 있는지."""

    def test_n_column_box_explicitly_marked_table(self) -> None:
        assert "N-column 박스형 도표" in _STAGE2_PROMPT_TEMPLATE
        # 시각적 layout = meaning 규칙도 명시.
        assert "시각적 layout 이 의미를 담으면" in _STAGE2_PROMPT_TEMPLATE
        # numbered_list / paragraph 가 아닌 *table* 로 분류 지시 명시.
        assert "paragraph / numbered_list 가 아닌 table" in _STAGE2_PROMPT_TEMPLATE

    def test_numeric_grid_with_label_grid_classified_as_table(self) -> None:
        """결함 5 의 직접 fixture — `6 8 / 개 개 / 기관 기관 / 7 10 / ...`
        같은 *숫자 + 단위 + 라벨* grid 가 반드시 table 로 분류되도록 명시."""
        assert "숫자 + 단위 + 라벨 grid" in _STAGE2_PROMPT_TEMPLATE
        # 텍스트 flatten 금지.
        assert "텍스트 flatten 하지 말고" in _STAGE2_PROMPT_TEMPLATE
        # row/column 라벨 추론 지시.
        assert "시각 위치로 추론" in _STAGE2_PROMPT_TEMPLATE

    def test_column_major_recovery_directive_present(self) -> None:
        """3-column 표 (전자정부법/통합기준/클라우드컴퓨팅법) 의 column-major
        broken 회복 규칙 — D85c-잔존 fix 핵심."""
        assert "column-major 텍스트" in _STAGE2_PROMPT_TEMPLATE
        # row 1 = 헤더, row 2 = 셀 매핑 규칙.
        assert "row 1 = 헤더" in _STAGE2_PROMPT_TEMPLATE
        # 통합 paragraph 로 concat 금지 — reflow 에 견고하도록 두 토큰으로 분리 검증.
        assert "하나의 paragraph" in _STAGE2_PROMPT_TEMPLATE
        assert "concat 금지" in _STAGE2_PROMPT_TEMPLATE


class TestListPageBoundaryPrompt:
    """list / table 이 page/batch 경계에서 부모 제목 누락한 채 분리되는 결함 3 의
    회귀 가드."""

    def test_page_boundary_merge_directive_present(self) -> None:
        # 결함 3 의 직접 패치 — 같은 batch 안 page 경계 결합 지시.
        assert "list/table 경계 규칙" in _STAGE2_PROMPT_TEMPLATE
        assert "batch 경계 또는 page 경계" in _STAGE2_PROMPT_TEMPLATE
        assert "반드시 하나의 list 로 결합" in _STAGE2_PROMPT_TEMPLATE

    def test_cross_batch_continuation_directive_present(self) -> None:
        """batch 범위를 벗어나면 두 번째 chunk 의 type 동일 유지 + 원 제목 명시."""
        # reflow 견고화 — 두 토큰으로 분리 검증.
        assert "같은 list/table type 유지" in _STAGE2_PROMPT_TEMPLATE
        # hallucination 차단 directive — GPT-5.5 verdict 권고.
        assert "추측" in _STAGE2_PROMPT_TEMPLATE and "hallucination 차단" in _STAGE2_PROMPT_TEMPLATE
        # 부모 제목 누락 사고 명시.
        assert "부모 제목 누락" in _STAGE2_PROMPT_TEMPLATE


class TestTableNegativeGuard:
    """GPT-5.5 verdict 권고 — 정상 paragraph / 2단 편집 등을 table 로 오분류 금지."""

    def test_negative_guard_section_present(self) -> None:
        assert "table 오분류 negative guard" in _STAGE2_PROMPT_TEMPLATE

    def test_plain_paragraph_not_table(self) -> None:
        assert "단순 줄바꿈" in _STAGE2_PROMPT_TEMPLATE
        assert "일반 문단" in _STAGE2_PROMPT_TEMPLATE

    def test_two_column_book_layout_not_table(self) -> None:
        assert "2단 편집" in _STAGE2_PROMPT_TEMPLATE
        assert "단순 layout" in _STAGE2_PROMPT_TEMPLATE

    def test_explicit_negative_directive(self) -> None:
        assert "table 로 만들지 않는다" in _STAGE2_PROMPT_TEMPLATE


class TestTableMarkdownFormatPreserved:
    """기존 (D85c) table markdown 형식 규칙 회귀 가드."""

    def test_markdown_pipe_format_required(self) -> None:
        assert "반드시 markdown 표" in _STAGE2_PROMPT_TEMPLATE
        assert "| col1 header | col2 header | col3 header |" in _STAGE2_PROMPT_TEMPLATE

    def test_table_nl_required(self) -> None:
        assert "table_nl 필수" in _STAGE2_PROMPT_TEMPLATE

    def test_block_types_intact(self) -> None:
        for t in (
            "heading_1/2/3",
            "paragraph",
            "table",
            "image",
            "bulleted_list",
            "numbered_list",
            "code",
            "quote",
            "callout",
            "noise",
            "divider",
        ):
            assert t in _STAGE2_PROMPT_TEMPLATE, f"block_type '{t}' missing"
