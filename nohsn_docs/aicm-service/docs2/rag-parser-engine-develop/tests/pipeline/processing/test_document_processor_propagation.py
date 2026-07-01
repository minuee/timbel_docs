"""T14 — DocumentProcessor 의 source_file_url / parse_map / doc_type 전파 단위 테스트.

검증 항목:
1. LLMBlockSegmenter 경로: 세 인자가 segmenter.segment() 에 그대로 전달된다.
2. FallbackSegmenter 경로: 새 kwargs 미전달 (isinstance 분기 보장).
3. 배치 처리(_process_in_batches) 경로: 인자가 각 배치 _segment 호출에 전달된다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import ProcessingConfig
from src.pipeline.models.parse_result import PageContent, ParseResult
from src.pipeline.processing.document_processor import DocumentProcessor


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------


def _make_parse_result(page_count: int = 2) -> ParseResult:
    """간단한 ParseResult 를 생성한다."""
    pages = [
        PageContent(page_number=i + 1, text=f"페이지 {i + 1} 본문 텍스트입니다.")
        for i in range(page_count)
    ]
    return ParseResult(pages=pages, tables=[], images=[])


def _make_block() -> BlockObject:
    return BlockObject(
        id=uuid4(),
        document_id=uuid4(),
        block_type=BlockType.PARAGRAPH,
        content="테스트 블럭 본문.",
        block_index=0,
        metadata={},
    )


# ---------------------------------------------------------------------------
# 테스트 1: LLMBlockSegmenter 경로 — 인자 전파 확인
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_segment_passes_kwargs_to_llm_segmenter():
    """LLMBlockSegmenter 가 선택될 때 source_file_url / parse_map / doc_type 전달."""
    dummy_block = _make_block()
    mock_segmenter = AsyncMock()
    mock_segmenter.segment = AsyncMock(return_value=[dummy_block])

    mock_llm = MagicMock()
    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=mock_llm)

    # LLMBlockSegmenter 인스턴스로 패치
    from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter

    mock_segmenter.__class__ = LLMBlockSegmenter

    with patch.object(processor, "_create_segmenter", return_value=mock_segmenter):
        parse_result = _make_parse_result(page_count=1)
        doc_id = uuid4()
        fake_parse_map = MagicMock()

        await processor._segment(
            parse_result,
            doc_id,
            source_file_url="https://example.com/doc.pdf",
            parse_map=fake_parse_map,
            doc_type="manual",
        )

    mock_segmenter.segment.assert_awaited_once()
    call_kwargs = mock_segmenter.segment.await_args.kwargs
    assert call_kwargs["source_file_url"] == "https://example.com/doc.pdf"
    assert call_kwargs["parse_map"] is fake_parse_map
    assert call_kwargs["doc_type"] == "manual"
    assert call_kwargs["document_id"] == doc_id


# ---------------------------------------------------------------------------
# 테스트 2: FallbackSegmenter 경로 — 새 kwargs 미전달
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_segment_no_kwargs_for_fallback_segmenter():
    """FallbackSegmenter 는 source_file_url / parse_map / doc_type 을 받지 않는다."""
    dummy_block = _make_block()
    mock_segmenter = AsyncMock()
    mock_segmenter.segment = AsyncMock(return_value=[dummy_block])

    from src.pipeline.segmenters.fallback_segmenter import FallbackSegmenter

    mock_segmenter.__class__ = FallbackSegmenter

    # llm_client=None → FallbackSegmenter 경로
    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=None)

    with patch.object(processor, "_create_segmenter", return_value=mock_segmenter):
        parse_result = _make_parse_result(page_count=1)
        doc_id = uuid4()
        fake_parse_map = MagicMock()

        await processor._segment(
            parse_result,
            doc_id,
            source_file_url="https://example.com/doc.pdf",
            parse_map=fake_parse_map,
            doc_type="manual",
        )

    mock_segmenter.segment.assert_awaited_once()
    call_kwargs = mock_segmenter.segment.await_args.kwargs
    # FallbackSegmenter 호출에 새 kwargs 없어야 함
    assert "source_file_url" not in call_kwargs
    assert "parse_map" not in call_kwargs
    assert "doc_type" not in call_kwargs
    assert call_kwargs["document_id"] == doc_id


# ---------------------------------------------------------------------------
# 테스트 3: _process_single 이 인자를 _segment 로 전달
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_single_propagates_kwargs():
    """_process_single 이 source_file_url / parse_map / doc_type 을 _segment 로 전달."""
    dummy_block = _make_block()
    mock_llm = MagicMock()
    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=mock_llm)

    fake_parse_map = MagicMock()

    with patch.object(
        processor,
        "_segment",
        new_callable=AsyncMock,
        return_value=[dummy_block],
    ) as mock_seg:
        parse_result = _make_parse_result(page_count=1)
        doc_id = uuid4()

        await processor._process_single(
            parse_result,
            doc_id,
            source_file_url="/repos/r/docs/d",
            parse_map=fake_parse_map,
            doc_type="faq",
        )

    mock_seg.assert_awaited_once()
    call_kwargs = mock_seg.await_args.kwargs
    assert call_kwargs["source_file_url"] == "/repos/r/docs/d"
    assert call_kwargs["parse_map"] is fake_parse_map
    assert call_kwargs["doc_type"] == "faq"


# ---------------------------------------------------------------------------
# 테스트 4: _process_in_batches 가 인자를 각 배치 _segment 로 전달
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_in_batches_propagates_kwargs():
    """_process_in_batches 에서 각 배치 _segment 호출 시 새 kwargs 전달."""
    dummy_block = _make_block()
    mock_llm = MagicMock()
    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=mock_llm)
    # 배치 크기(20) 초과하는 페이지 수
    parse_result = _make_parse_result(page_count=25)
    doc_id = uuid4()
    fake_parse_map = MagicMock()

    with patch.object(
        processor,
        "_segment",
        new_callable=AsyncMock,
        return_value=[dummy_block],
    ) as mock_seg, patch.object(
        processor, "_save_checkpoint", new_callable=AsyncMock
    ), patch.object(
        processor, "_save_intermediate_blocks", new_callable=AsyncMock
    ):
        await processor._process_in_batches(
            parse_result,
            doc_id,
            checkpoint=None,
            source_file_url="/repos/r/docs/d",
            parse_map=fake_parse_map,
            doc_type="report",
        )

    # 2 배치 (25 페이지 / BATCH_SIZE 20 → 2 배치) 호출되어야 함
    assert mock_seg.await_count == 2
    for call in mock_seg.await_args_list:
        kw = call.kwargs
        assert kw["source_file_url"] == "/repos/r/docs/d"
        assert kw["parse_map"] is fake_parse_map
        assert kw["doc_type"] == "report"
