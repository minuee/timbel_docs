"""D31c §6 — PDF/PPT source_location.page test.

stub `ParseResult` / `PageContent` 주입 (env 의존 0). PDF 의 page_number 와 PPTX 의
slide_number 를 _PipelineBlock.source_location["page"] 까지 전파 검증.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

from src.pipeline.full_pipeline import (
    _PipelineBlock,
    _split_long_paragraphs_with_pages,
    _split_faq_list_items_with_pages,
    partition_noise_text_blocks_with_index,
    process_document_full,
)


# ────────────────────────────────────────────────────────────────────────
# §6.1 — partition_noise_text_blocks_with_index — 원본 idx 반환
# ────────────────────────────────────────────────────────────────────────


class TestPartitionWithIndex:
    """§6.1 — partition_with_index 정합."""

    def test_basic_separation(self) -> None:
        """case 6.1.1 — content / noise / content_idx / noise_idx 4-tuple 반환."""
        blocks = [
            ("paragraph", "real content"),
            ("paragraph", "1"),  # 짧은 숫자 — noise
            ("paragraph", "more real"),
        ]
        content, noise, c_idx, n_idx = partition_noise_text_blocks_with_index(blocks)
        assert len(content) == 2
        assert len(noise) == 1
        assert c_idx == [0, 2]
        assert n_idx == [1]

    def test_pages_lookup_via_idx(self) -> None:
        """case 6.1.2 — content_idx → pages 매핑 가능."""
        blocks = [
            ("paragraph", "real"),
            ("paragraph", "1"),  # noise
            ("paragraph", "more"),
        ]
        pages = [10, 11, 12]
        content, noise, c_idx, n_idx = partition_noise_text_blocks_with_index(blocks)
        content_pages = [pages[i] for i in c_idx]
        noise_pages = [pages[i] for i in n_idx]
        assert content_pages == [10, 12]
        assert noise_pages == [11]


# ────────────────────────────────────────────────────────────────────────
# §6.2 — split helper page 동기 wrapper
# ────────────────────────────────────────────────────────────────────────


class TestSplitWithPages:
    """§6.2 — split_long_paragraphs_with_pages / split_faq_list_items_with_pages."""

    def test_short_paragraph_unchanged(self) -> None:
        """case 6.2.1 — 짧은 paragraph 는 그대로 + page 보존."""
        blocks = [("paragraph", "short")]
        pages = [3]
        out_blocks, out_pages = _split_long_paragraphs_with_pages(blocks, pages)
        assert out_blocks == blocks
        assert out_pages == [3]

    def test_long_paragraph_split_pages_inherit(self) -> None:
        """case 6.2.2 — 긴 paragraph split 시 모든 split 이 동일 page 공유."""
        long_text = "line\n" * 600  # 5*600=3000 chars
        blocks = [("paragraph", long_text)]
        pages = [7]
        out_blocks, out_pages = _split_long_paragraphs_with_pages(blocks, pages)
        assert len(out_blocks) > 1  # split 발생
        assert all(p == 7 for p in out_pages)
        assert len(out_blocks) == len(out_pages)

    def test_mismatch_fallback_safe(self) -> None:
        """case 6.2.3 — len mismatch 시 fallback 안전 (split 결과 길이에 맞춤)."""
        blocks = [("paragraph", "a"), ("paragraph", "b")]
        pages = [1]  # mismatch (1 < 2)
        out_blocks, out_pages = _split_long_paragraphs_with_pages(blocks, pages)
        assert len(out_blocks) == len(out_pages)
        assert all(p is None for p in out_pages)

    def test_faq_split_pages_inherit(self) -> None:
        """case 6.2.4 — FAQ list split 도 page 공유."""
        content = "- **질문1**: q\n- **MENT**: a\n- **질문2**: q2\n- **MENT**: a2"
        blocks = [("paragraph", content)]
        pages = [5]
        out_blocks, out_pages = _split_faq_list_items_with_pages(blocks, pages)
        assert len(out_blocks) >= 2
        assert all(p == 5 for p in out_pages)
        assert len(out_blocks) == len(out_pages)


# ────────────────────────────────────────────────────────────────────────
# §6.3 — process_document_full PDF/PPT page propagation (stub fixture)
# ────────────────────────────────────────────────────────────────────────


@dataclass
class _StubTextBlock:
    text: str = ""
    heading_level: int = 0


@dataclass
class _StubPage:
    page_number: int
    text_blocks: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    images: list = field(default_factory=list)
    text: str = ""


@dataclass
class _StubParseResult:
    pages: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)
    images: list = field(default_factory=list)
    raw_text: str = ""


@dataclass
class _StubVisionDecision:
    use_vision: bool = False
    reason: str = "stub"


class _StubParser:
    def __init__(self, parse_result: _StubParseResult):
        self._pr = parse_result

    async def parse(self) -> _StubParseResult:
        return self._pr


class TestProcessDocumentFullPagePropagation:
    """§6.3 — process_document_full PDF/PPT path 가 page 채움."""

    @pytest.mark.asyncio
    async def test_pdf_path_source_location_page(self, tmp_path) -> None:
        """case 6.3.1 — PDF stub: page 1 / page 2 의 block 이 각각 page=1/2 채움."""
        # 2-page stub
        pages = [
            _StubPage(
                page_number=1,
                text_blocks=[_StubTextBlock(text="page-one content body that is long enough to pass noise filter and structure analyze step normally")],
            ),
            _StubPage(
                page_number=2,
                text_blocks=[_StubTextBlock(text="page-two content body — second page longer text not noise sufficiently large for processing")],
            ),
        ]
        parse_result = _StubParseResult(pages=pages, metadata={})

        # fake parser — file extension 은 .pdf
        fake_pdf = tmp_path / "stub.pdf"
        fake_pdf.write_bytes(b"stub")

        with patch(
            "src.pipeline.parsers.router.detect_format",
            return_value="pdf",
        ), patch(
            "src.pipeline.parsers.router.select_parser",
            return_value=_StubParser(parse_result),
        ), patch(
            "src.pipeline.workers.vision_gate.decide_vision",
            return_value=_StubVisionDecision(),
        ):
            result = await process_document_full(
                title="stub-pdf",
                file_path=str(fake_pdf),
                llm_client=None,
                upload_source="test",
                document_type_hint="manual",
            )

        assert result.blocks_full
        # 모든 block 의 source_location.page 가 채워짐 (1 또는 2)
        pages_seen = {pb.source_location.get("page") for pb in result.blocks_full}
        assert pages_seen == {1, 2}, f"expected pages {{1,2}}, got {pages_seen}"

    @pytest.mark.asyncio
    async def test_pptx_path_slide_number_fallback(self, tmp_path) -> None:
        """case 6.3.2 — PPTX stub (slide_number only): fallback OK."""
        @dataclass
        class _StubSlidePage:
            slide_number: int
            text_blocks: list = field(default_factory=list)
            tables: list = field(default_factory=list)
            images: list = field(default_factory=list)
            text: str = ""
            page_number: int | None = None  # simulate slide-only

        pages = [
            _StubSlidePage(
                slide_number=1,
                text_blocks=[_StubTextBlock(text="slide one body content sufficiently long to pass noise filter and structure analyze step")],
            ),
            _StubSlidePage(
                slide_number=2,
                text_blocks=[_StubTextBlock(text="slide two body content sufficiently long to pass noise filter and structure analyze step")],
            ),
        ]
        parse_result = _StubParseResult(pages=pages, metadata={})

        fake_pptx = tmp_path / "stub.pptx"
        fake_pptx.write_bytes(b"stub")

        with patch(
            "src.pipeline.parsers.router.detect_format",
            return_value="pptx",
        ), patch(
            "src.pipeline.parsers.router.select_parser",
            return_value=_StubParser(parse_result),
        ), patch(
            "src.pipeline.workers.vision_gate.decide_vision",
            return_value=_StubVisionDecision(),
        ):
            result = await process_document_full(
                title="stub-pptx",
                file_path=str(fake_pptx),
                llm_client=None,
                upload_source="test",
                document_type_hint="presentation",
            )

        assert result.blocks_full
        pages_seen = {pb.source_location.get("page") for pb in result.blocks_full}
        # slide_number fallback → 1, 2
        assert pages_seen == {1, 2}, f"expected pages {{1,2}}, got {pages_seen}"

    @pytest.mark.asyncio
    async def test_markdown_path_source_location_empty(self) -> None:
        """case 6.3.3 — markdown path: source_location = {} (D31b 정책 유지)."""
        result = await process_document_full(
            title="md-text",
            markdown_text="# Heading\n\nlong paragraph body content sufficient.\n\n## Another\n\nsecond paragraph body content sufficient for the pipeline.",
            llm_client=None,
            upload_source="test",
            document_type_hint="manual",
        )

        assert result.blocks_full
        # markdown 은 pn=None → source_location = {}
        for pb in result.blocks_full:
            assert pb.source_location == {}, f"expected empty, got {pb.source_location}"

    @pytest.mark.asyncio
    async def test_all_blocks_have_page_when_pdf(self, tmp_path) -> None:
        """case 6.3.4 — PDF 의 모든 block 이 page 채워짐 (None X)."""
        pages = [
            _StubPage(
                page_number=1,
                text_blocks=[
                    _StubTextBlock(text="first long block sufficient for processing noise filter pass through pipeline"),
                    _StubTextBlock(text="second long block sufficient for processing noise filter pass through pipeline"),
                ],
            ),
        ]
        parse_result = _StubParseResult(pages=pages, metadata={})

        fake_pdf = tmp_path / "stub2.pdf"
        fake_pdf.write_bytes(b"stub")

        with patch(
            "src.pipeline.parsers.router.detect_format",
            return_value="pdf",
        ), patch(
            "src.pipeline.parsers.router.select_parser",
            return_value=_StubParser(parse_result),
        ), patch(
            "src.pipeline.workers.vision_gate.decide_vision",
            return_value=_StubVisionDecision(),
        ):
            result = await process_document_full(
                title="stub-pdf2",
                file_path=str(fake_pdf),
                llm_client=None,
                upload_source="test",
                document_type_hint="manual",
            )

        assert result.blocks_full
        for pb in result.blocks_full:
            assert pb.source_location.get("page") == 1

    @pytest.mark.asyncio
    async def test_noise_blocks_full_also_page_propagated(self, tmp_path) -> None:
        """case 6.3.5 — noise_blocks_full 도 page 채움 (content 대칭)."""
        pages = [
            _StubPage(
                page_number=1,
                text_blocks=[
                    _StubTextBlock(text="real content block long enough to be classified as content not noise"),
                    _StubTextBlock(text="1"),  # 짧고 숫자만 → noise
                ],
            ),
        ]
        parse_result = _StubParseResult(pages=pages, metadata={})

        fake_pdf = tmp_path / "stub3.pdf"
        fake_pdf.write_bytes(b"stub")

        with patch(
            "src.pipeline.parsers.router.detect_format",
            return_value="pdf",
        ), patch(
            "src.pipeline.parsers.router.select_parser",
            return_value=_StubParser(parse_result),
        ), patch(
            "src.pipeline.workers.vision_gate.decide_vision",
            return_value=_StubVisionDecision(),
        ):
            result = await process_document_full(
                title="stub-pdf3",
                file_path=str(fake_pdf),
                llm_client=None,
                upload_source="test",
                document_type_hint="manual",
            )

        # noise_blocks_full 가 채워진 경우 page 도 채워져야 (1)
        if result.noise_blocks_full:
            for pb in result.noise_blocks_full:
                assert pb.source_location.get("page") == 1
