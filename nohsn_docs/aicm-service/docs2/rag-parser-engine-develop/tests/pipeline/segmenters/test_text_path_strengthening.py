"""T11+T12 — text 경로 (LLMBlockSegmenter) LayoutMapper hint + file_url 전파 단위 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.pipeline.stages.layout_map import DetectedTable, ParseMap


# ─────────────────────────────────────────────────────────────────────
# 1. _build_text_table_hint
# ─────────────────────────────────────────────────────────────────────


class TestBuildTextTableHint:
    """_build_text_table_hint 함수 단위 테스트."""

    def _fn(self, parse_map, page_number):
        from src.pipeline.segmenters.llm_block_segmenter import _build_text_table_hint

        return _build_text_table_hint(parse_map, page_number)

    def test_none_parse_map_returns_empty(self):
        """ParseMap None 이면 빈 문자열."""
        result = self._fn(None, 1)
        assert result == ""

    def test_page_with_no_tables_returns_empty(self):
        """해당 페이지에 표 없으면 빈 문자열."""
        pm = ParseMap()
        pm.add(2, DetectedTable(bbox=[0, 0, 100, 50], kind="grid_table", confidence=1.0))
        result = self._fn(pm, 1)  # page 1 에는 표 없음
        assert result == ""

    def test_page_with_grid_table_returns_hint(self):
        """grid_table 감지 시 hint 문자열 포함."""
        pm = ParseMap()
        pm.add(1, DetectedTable(bbox=[10.0, 20.0, 200.0, 100.0], kind="grid_table", confidence=1.0))
        result = self._fn(pm, 1)
        assert "사전 감지된 표/도표 영역" in result
        assert "grid_table" in result
        assert "bbox=[10.0, 20.0, 200.0, 100.0]" in result
        assert "열 우선" in result

    def test_page_with_box_table_returns_hint(self):
        """box_table 감지 시 hint 포함."""
        pm = ParseMap()
        pm.add(3, DetectedTable(bbox=[0.0, 0.0, 300.0, 200.0], kind="box_table", confidence=0.8))
        result = self._fn(pm, 3)
        assert "box_table" in result

    def test_multiple_tables_all_listed(self):
        """복수 표 모두 열거."""
        pm = ParseMap()
        pm.add(2, DetectedTable(bbox=[0, 0, 100, 50], kind="grid_table", confidence=1.0))
        pm.add(2, DetectedTable(bbox=[100, 0, 200, 50], kind="box_table", confidence=0.7))
        result = self._fn(pm, 2)
        assert "grid_table" in result
        assert "box_table" in result


# ─────────────────────────────────────────────────────────────────────
# 2. build_segmentation_prompt — table_hint 주입
# ─────────────────────────────────────────────────────────────────────


class TestBuildSegmentationPromptTableHint:
    """build_segmentation_prompt 에 table_hint 인자 추가 확인."""

    def test_empty_table_hint_not_injected(self):
        """table_hint 빈 문자열이면 prompt 에 'LayoutMapper' 없음."""
        from src.pipeline.prompts.block_segmentation import build_segmentation_prompt

        prompt = build_segmentation_prompt("텍스트 내용", 800, "generic", table_hint="")
        assert "LayoutMapper" not in prompt

    def test_table_hint_injected_in_prompt(self):
        """table_hint 가 있으면 prompt 에 포함됨."""
        from src.pipeline.prompts.block_segmentation import build_segmentation_prompt

        hint = "## 사전 감지된 표/도표 영역 (LayoutMapper)\n- grid_table 영역 bbox=[0, 0, 100, 50]\n"
        prompt = build_segmentation_prompt("텍스트 내용", 800, "generic", table_hint=hint)
        assert "LayoutMapper" in prompt
        assert "grid_table" in prompt

    def test_doc_type_and_table_hint_together(self):
        """doc_type hint 와 table_hint 가 함께 포함."""
        from src.pipeline.prompts.block_segmentation import build_segmentation_prompt

        hint = "## 사전 감지된 표/도표 영역 (LayoutMapper)\n- box_table 영역 bbox=[1,2,3,4]\n"
        prompt = build_segmentation_prompt("본문", 800, "manual", table_hint=hint)
        assert "매뉴얼" in prompt or "manual" in prompt.lower()
        assert "box_table" in prompt

    def test_backward_compat_no_table_hint_arg(self):
        """기존 호출자 — table_hint 없이 호출해도 정상 동작."""
        from src.pipeline.prompts.block_segmentation import build_segmentation_prompt

        prompt = build_segmentation_prompt("텍스트", 800, "faq")
        assert len(prompt) > 100  # 최소 길이 확인


# ─────────────────────────────────────────────────────────────────────
# 3. LLMBlockSegmenter.segment — SourceLocation.file_url 전파
# ─────────────────────────────────────────────────────────────────────


class TestLLMBlockSegmenterFileUrl:
    """segment() 호출 시 SourceLocation.file_url 이 채워지는지 확인."""

    @pytest.mark.asyncio
    async def test_source_file_url_propagated_to_blocks(self):
        """source_file_url 이 segment() → SourceLocation.file_url 로 전파됨."""
        from uuid import UUID

        from src.pipeline.models.document import ProcessingConfig
        from src.pipeline.models.parse_result import PageContent, ParseResult
        from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

        doc_id = uuid4()
        config = ProcessingConfig(use_block_pipeline=True, block_max_tokens=800)

        # LLM 클라이언트 mock — segment_batch LLM 응답 반환
        mock_llm = MagicMock()
        mock_llm.__class__.__name__ = "AsyncOpenAI"

        llm_response = (
            '[{"content": "테스트 본문입니다.", "type": "paragraph", "hint": "테스트", "properties": {}}]'
        )

        segmenter = LLMBlockSegmenter(config, llm_client=mock_llm)

        with patch.object(segmenter, "_call_llm", new=AsyncMock(return_value=llm_response)):
            parse_result = ParseResult(
                pages=[
                    PageContent(
                        page_number=1,
                        text="테스트 본문입니다.",
                        text_blocks=[],
                        tables=[],
                        images=[],
                    )
                ],
                source_file_path="/tmp/test.pdf",
            )

            file_url = "/repos/repo-123/docs/doc-456"
            blocks = await segmenter.segment(
                parse_result,
                document_id=doc_id,
                source_file_url=file_url,
            )

        assert len(blocks) > 0, "최소 1개 블럭이 생성돼야 함"
        for block in blocks:
            if block.source_location:
                assert block.source_location.file_url == file_url, (
                    f"file_url 이 {file_url!r} 이어야 하는데 "
                    f"{block.source_location.file_url!r} 가 됨"
                )

    @pytest.mark.asyncio
    async def test_segment_backward_compat_no_new_args(self):
        """기존 인자만으로 호출해도 정상 작동 (신규 인자 default)."""
        from uuid import UUID

        from src.pipeline.models.document import ProcessingConfig
        from src.pipeline.models.parse_result import PageContent, ParseResult
        from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

        doc_id = uuid4()
        config = ProcessingConfig(use_block_pipeline=True, block_max_tokens=800)
        mock_llm = MagicMock()
        llm_response = '[{"content": "내용", "type": "paragraph", "hint": "내용", "properties": {}}]'

        segmenter = LLMBlockSegmenter(config, llm_client=mock_llm)

        with patch.object(segmenter, "_call_llm", new=AsyncMock(return_value=llm_response)):
            parse_result = ParseResult(
                pages=[
                    PageContent(
                        page_number=1,
                        text="내용",
                        text_blocks=[],
                        tables=[],
                        images=[],
                    )
                ],
                source_file_path="/tmp/test.pdf",
            )
            # 기존 시그니처 — 추가 인자 없음
            blocks = await segmenter.segment(parse_result, document_id=doc_id)

        assert len(blocks) > 0


# ─────────────────────────────────────────────────────────────────────
# 4. _build_text_table_hint — parse_map.tables_for_page 예외 흡수
# ─────────────────────────────────────────────────────────────────────


class TestBuildTextTableHintExceptionSafety:
    """parse_map 이 잘못된 객체일 때 예외를 흡수해야 함."""

    def test_broken_parse_map_returns_empty(self):
        """tables_for_page 가 예외를 던지면 빈 문자열 반환."""
        from src.pipeline.segmenters.llm_block_segmenter import _build_text_table_hint

        bad_map = MagicMock()
        bad_map.tables_for_page.side_effect = RuntimeError("broken")
        result = _build_text_table_hint(bad_map, 1)
        assert result == ""


# ─────────────────────────────────────────────────────────────────────
# 5. _split_heading_with_body — 제목 블럭이 본문을 흡수한 경우 분리
#    (audit C9: LLM 이 "제목 + 첫 단락"을 하나의 heading 블럭으로 묶는 버그)
# ─────────────────────────────────────────────────────────────────────


class TestSplitHeadingWithBody:
    """heading 블럭에 본문이 흡수되면 heading + paragraph 로 분리하는 안전망."""

    def _fn(self, items):
        from src.pipeline.segmenters.llm_block_segmenter import _split_heading_with_body

        return _split_heading_with_body(items)

    def test_heading_with_trailing_body_is_split(self):
        """heading_1 = 제목줄 + 긴 본문 → heading(제목) + paragraph(본문) 2개로 분리."""
        items = [{
            "content": "「청년 주택드림 청약통장」 약관\n제1조 약관의 적용 ① '청년 주택드림 청약통장'은 이 약관이 정하는 바에 따라 거래합니다.",
            "type": "heading_1",
            "hint": "약관",
        }]
        out = self._fn(items)
        assert len(out) == 2
        assert out[0]["type"] == "heading_1"
        assert out[0]["content"] == "「청년 주택드림 청약통장」 약관"
        assert out[1]["type"] == "paragraph"
        assert out[1]["content"].startswith("제1조 약관의 적용")

    def test_short_multiline_heading_not_split(self):
        """제목 뒤 짧은 줄(본문 아님)은 분리하지 않음 (다줄 제목 보존)."""
        items = [{"content": "「청년 주택드림 청약통장」\n약관", "type": "heading_1", "hint": "약관"}]
        out = self._fn(items)
        assert len(out) == 1
        assert out[0]["content"] == "「청년 주택드림 청약통장」\n약관"

    def test_single_line_heading_unchanged(self):
        """줄바꿈 없는 단일 제목은 그대로."""
        items = [{"content": "제1장 총칙", "type": "heading_1", "hint": "총칙"}]
        out = self._fn(items)
        assert len(out) == 1
        assert out[0]["content"] == "제1장 총칙"

    def test_paragraph_block_unchanged(self):
        """heading 이 아닌 블럭은 본문이 길어도 분리 안 함."""
        items = [{"content": "첫 줄\n" + "본문 " * 40, "type": "paragraph", "hint": "본문"}]
        out = self._fn(items)
        assert len(out) == 1
        assert out[0]["type"] == "paragraph"

    def test_long_first_line_not_treated_as_heading(self):
        """첫 줄 자체가 길면(제목 아님) 분리하지 않음 — heading 오라벨 케이스는 별개."""
        long_first = "이것은 제목이 아니라 매우 긴 한 문장으로 이루어진 본문 단락입니다 " * 3
        items = [{"content": long_first + "\n추가 본문", "type": "heading_2", "hint": "x"}]
        out = self._fn(items)
        assert len(out) == 1

    def test_order_preserved_across_items(self):
        """여러 item 중 해당 케이스만 분리하고 순서 유지."""
        items = [
            {"content": "intro", "type": "paragraph", "hint": ""},
            {"content": "제목\n" + "본문입니다. " * 10, "type": "heading_1", "hint": "h"},
            {"content": "tail", "type": "paragraph", "hint": ""},
        ]
        out = self._fn(items)
        assert [i["type"] for i in out] == ["paragraph", "heading_1", "paragraph", "paragraph"]
        assert out[1]["content"] == "제목"


# ─────────────────────────────────────────────────────────────────────
# 6. qna_postprocess(_merge_qna_blocks) doc_type 게이팅
#    비-FAQ(generic 약관 등)에서 heading 을 질문으로 오탐해 문서 전체를
#    단일 qna 로 과병합하고 제목을 흡수(소실)하던 회귀 차단.
# ─────────────────────────────────────────────────────────────────────


class TestQnaMergeGatedByDocType:
    """_merge_qna_blocks 는 doc_type == 'faq' 일 때만 호출돼야 한다."""

    def _make(self):
        from src.pipeline.models.document import ProcessingConfig
        from src.pipeline.models.parse_result import PageContent, ParseResult
        from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

        config = ProcessingConfig(use_block_pipeline=True, block_max_tokens=800)
        mock_llm = MagicMock()
        mock_llm.__class__.__name__ = "AsyncOpenAI"
        segmenter = LLMBlockSegmenter(config, llm_client=mock_llm)
        parse_result = ParseResult(
            pages=[PageContent(
                page_number=1, text="제1조 약관의 적용 내용입니다.",
                text_blocks=[], tables=[], images=[],
            )],
            source_file_path="/tmp/test.pdf",
        )
        return segmenter, parse_result

    @pytest.mark.asyncio
    async def test_merge_skipped_for_generic_doc(self):
        """generic 문서는 _merge_qna_blocks 를 호출하지 않는다(heading 과병합 방지)."""
        segmenter, parse_result = self._make()
        resp = '[{"content": "제1조 약관의 적용 내용입니다.", "type": "paragraph", "hint": "x", "properties": {}}]'
        with patch.object(segmenter, "_call_llm", new=AsyncMock(return_value=resp)), \
             patch("src.pipeline.segmenters.llm_block_segmenter._merge_qna_blocks",
                   side_effect=lambda b: b) as spy:
            await segmenter.segment(parse_result, document_id=uuid4(), doc_type="generic")
        spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_merge_applied_for_faq_doc(self):
        """FAQ 문서는 _merge_qna_blocks 를 호출한다(기존 동작 보존)."""
        segmenter, parse_result = self._make()
        resp = '[{"content": "Q. 가입 대상은?\\n만 19~34세입니다.", "type": "qna", "hint": "대상", "properties": {}}]'
        with patch.object(segmenter, "_call_llm", new=AsyncMock(return_value=resp)), \
             patch("src.pipeline.segmenters.llm_block_segmenter._merge_qna_blocks",
                   side_effect=lambda b: b) as spy:
            await segmenter.segment(parse_result, document_id=uuid4(), doc_type="faq")
        spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_applied_for_generic_with_real_qna_content(self):
        """내용기반 보강: doc_type 이 generic 이라도 실제 Q. 패턴이 2개 이상이면 병합(오탐 FAQ 보존)."""
        segmenter, parse_result = self._make()
        resp = ('[{"content": "Q. 가입 대상은?\\n만 19~34세입니다.", "type": "qna", "hint": "대상"},'
                ' {"content": "Q. 한도는?\\n연 600만원입니다.", "type": "qna", "hint": "한도"}]')
        with patch.object(segmenter, "_call_llm", new=AsyncMock(return_value=resp)), \
             patch("src.pipeline.segmenters.llm_block_segmenter._merge_qna_blocks",
                   side_effect=lambda b: b) as spy:
            await segmenter.segment(parse_result, document_id=uuid4(), doc_type="generic")
        spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_skipped_for_generic_heading_only(self):
        """약관 케이스: generic 이고 heading 만 있고 실제 Q. 패턴이 없으면 스킵(과병합 방지)."""
        segmenter, parse_result = self._make()
        resp = ('[{"content": "「청년 주택드림 청약통장」 약관", "type": "heading_1", "hint": "제목"},'
                ' {"content": "제1조 약관의 적용 내용입니다. 매우 긴 본문 단락.", "type": "paragraph", "hint": "제1조"}]')
        with patch.object(segmenter, "_call_llm", new=AsyncMock(return_value=resp)), \
             patch("src.pipeline.segmenters.llm_block_segmenter._merge_qna_blocks",
                   side_effect=lambda b: b) as spy:
            await segmenter.segment(parse_result, document_id=uuid4(), doc_type="generic")
        spy.assert_not_called()
