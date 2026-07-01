"""W4 — SourceLocation.file_url 채움 (semantic chunker)

검증:
- _fallback_split: source_file_url 인자가 SourceLocation.file_url 로 전파.
- _find_source_location: source_file_url 인자가 SourceLocation.file_url 로 전파.
- chunk(): source_file_url 이 _build_chunks 를 거쳐 chunk.source_location.file_url 로 전파.
- 기존 호출자 호환: source_file_url 생략 시 file_url = None (기본값).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.pipeline.chunkers.semantic import SemanticChunker
from src.pipeline.models.document import ProcessingConfig, SourceLocation
from src.pipeline.models.parse_result import PageContent, TextBlock


def _make_chunker() -> SemanticChunker:
    return SemanticChunker(ProcessingConfig())


def _make_page(text: str = "본문 텍스트입니다.", page_number: int = 1) -> PageContent:
    return PageContent(
        page_number=page_number,
        text=text,
        text_blocks=[
            TextBlock(
                text=text,
                start_char_offset=0,
                end_char_offset=len(text),
            )
        ],
    )


# ---------------------------------------------------------------------------
# _fallback_split
# ---------------------------------------------------------------------------


def test_fallback_split_propagates_file_url() -> None:
    """_fallback_split 이 source_file_url 을 SourceLocation.file_url 로 채운다."""
    chunker = _make_chunker()
    pages = [_make_page("본문 텍스트입니다.")]
    _, sources = chunker._fallback_split(
        pages,
        source_file_path="/storage/docs/abc.pdf",
        source_file_url="https://kms/repos/r1/docs/d1",
    )
    assert len(sources) > 0
    assert sources[0].file_url == "https://kms/repos/r1/docs/d1"
    assert sources[0].file_path == "/storage/docs/abc.pdf"


def test_fallback_split_empty_url_default() -> None:
    """source_file_url 생략 시 file_url = None (기존 호출자 호환)."""
    chunker = _make_chunker()
    pages = [_make_page("줄 하나.")]
    _, sources = chunker._fallback_split(
        pages,
        source_file_path="/tmp/x.pdf",
    )
    assert sources[0].file_url is None


# ---------------------------------------------------------------------------
# _find_source_location
# ---------------------------------------------------------------------------


def test_find_source_location_propagates_file_url_with_matching_block() -> None:
    """_find_source_location: 매칭 블럭이 있을 때 file_url 이 전파된다."""
    page = _make_page("운영 리스크는 핵심 관리 대상이다.")
    sl = SemanticChunker._find_source_location(
        sentence="운영 리스크는 핵심 관리 대상이다.",
        page=page,
        source_file_path="/data/policy.pdf",
        source_file_url="https://kms/repos/r2/docs/d2",
    )
    assert sl.file_url == "https://kms/repos/r2/docs/d2"
    assert sl.file_path == "/data/policy.pdf"


def test_find_source_location_propagates_file_url_no_blocks() -> None:
    """_find_source_location: 블럭 없을 때 폴백 SourceLocation 에도 file_url 이 전파된다."""
    page = PageContent(page_number=1, text="some text", text_blocks=[])
    sl = SemanticChunker._find_source_location(
        sentence="some text",
        page=page,
        source_file_path="/data/x.pdf",
        source_file_url="https://kms/repos/r3/docs/d3",
    )
    assert sl.file_url == "https://kms/repos/r3/docs/d3"


def test_find_source_location_empty_url_default() -> None:
    """source_file_url 생략 시 file_url = None."""
    page = _make_page("내용.")
    sl = SemanticChunker._find_source_location(
        sentence="내용.",
        page=page,
        source_file_path="/data/x.pdf",
    )
    assert sl.file_url is None


# ---------------------------------------------------------------------------
# chunk() end-to-end (KSS 없을 때 _fallback_split 경로)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_e2e_file_url_propagated_fallback_path() -> None:
    """chunk() 가 source_file_url 을 최종 ChunkObject.source_location.file_url 로 전파.

    kss 없는 환경에서 _fallback_split 경로로 실행.
    """
    chunker = _make_chunker()
    pages = [_make_page("첫 번째 문장입니다.\n두 번째 문장입니다.")]

    # kss 없는 환경 강제 (fallback_split 실행 보장)
    with patch.dict("sys.modules", {"kss": None}):
        chunks = await chunker.chunk(
            pages,
            source_file_path="/storage/docs/policy.pdf",
            source_file_url="https://kms/repos/r4/docs/d4",
            document_id=str(uuid4()),
        )

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.source_location.file_url == "https://kms/repos/r4/docs/d4", (
            f"chunk {chunk.chunk_index} file_url = {chunk.source_location.file_url!r}"
        )


@pytest.mark.asyncio
async def test_chunk_e2e_empty_file_url_default() -> None:
    """source_file_url 생략 시 chunk.source_location.file_url = None (기존 호환)."""
    chunker = _make_chunker()
    pages = [_make_page("내용입니다.")]

    with patch.dict("sys.modules", {"kss": None}):
        chunks = await chunker.chunk(
            pages,
            source_file_path="/tmp/doc.pdf",
            document_id=str(uuid4()),
        )

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.source_location.file_url is None
