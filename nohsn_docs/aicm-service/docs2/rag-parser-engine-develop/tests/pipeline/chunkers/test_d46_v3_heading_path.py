"""D46-v3 §4 — chunker heading_path 상속 SoT 동등성 tests.

검증:
- semantic chunker: first_src 의 heading_path 가 chunk.source_location.heading_path 로 상속.
- hierarchical chunker: parent_path → chunk.source_location.heading_path 정확히 설정.
- table chunker: table_title 기반 heading_path 정확히 설정.
- SoT 동등성: block.source_location.heading_path 와 chunk.source_location.heading_path
  가 동일 source 에서 출발하여 일관됨.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.pipeline.chunkers.semantic import SemanticChunker
from src.pipeline.models.document import (
    ChunkObject,
    ProcessingConfig,
    SourceLocation,
)


pytestmark = pytest.mark.asyncio


def _make_config() -> ProcessingConfig:
    return ProcessingConfig()


# ---------------------------------------------------------------------------
# Semantic chunker heading_path 상속 (D46-v3 §4 핵심 fix)
# ---------------------------------------------------------------------------


async def test_semantic_chunker_inherits_heading_path() -> None:
    """semantic chunker 가 sources[group[0]].heading_path 를 상속."""
    chunker = SemanticChunker(_make_config())
    sentences = ["문장 1.", "문장 2.", "문장 3."]
    sources = [
        SourceLocation(
            file_path="/tmp/test.md",
            page_number=1,
            heading_path=["1. 개요", "1.1 목적"],
        ),
        SourceLocation(
            file_path="/tmp/test.md",
            page_number=1,
            heading_path=["1. 개요", "1.1 목적"],
        ),
        SourceLocation(
            file_path="/tmp/test.md",
            page_number=1,
            heading_path=["1. 개요", "1.1 목적"],
        ),
    ]
    chunks = chunker._build_chunks(sentences, sources, split_points=[], document_id=uuid4())
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.source_location.heading_path == ["1. 개요", "1.1 목적"], (
            f"chunk {chunk.chunk_index} heading_path = "
            f"{chunk.source_location.heading_path}, expected inherited"
        )


async def test_semantic_chunker_empty_heading_path_unchanged() -> None:
    """heading_path 가 비어 있으면 빈 list 유지 (회귀 0)."""
    chunker = SemanticChunker(_make_config())
    sentences = ["A", "B"]
    sources = [
        SourceLocation(file_path="/tmp/x.md", page_number=1),
        SourceLocation(file_path="/tmp/x.md", page_number=1),
    ]
    chunks = chunker._build_chunks(sentences, sources, split_points=[], document_id=uuid4())
    for chunk in chunks:
        assert chunk.source_location.heading_path == []


async def test_semantic_chunker_isolates_per_group_heading_path() -> None:
    """split_points 로 그룹 분할 시 각 그룹의 first_src.heading_path 가 상속."""
    chunker = SemanticChunker(_make_config())
    sentences = ["g1-s1", "g1-s2", "g2-s1", "g2-s2"]
    sources = [
        SourceLocation(file_path="x", heading_path=["Sec1"]),
        SourceLocation(file_path="x", heading_path=["Sec1"]),
        SourceLocation(file_path="x", heading_path=["Sec2"]),
        SourceLocation(file_path="x", heading_path=["Sec2"]),
    ]
    chunks = chunker._build_chunks(
        sentences, sources, split_points=[2], document_id=uuid4()
    )
    # 작은 그룹은 merge 될 수 있어 정확한 chunk 수 보장 X — 그러나 heading_path 가
    # 비어 있지 않은지 + 상속 list 의 멤버인지 검증.
    assert len(chunks) >= 1
    seen_paths = {tuple(c.source_location.heading_path) for c in chunks}
    # Either both [Sec1] and [Sec2] OR merged single chunk inherits first_src [Sec1].
    assert seen_paths.issubset({("Sec1",), ("Sec2",)})
    assert () not in seen_paths  # 빈 path 없음 — 상속 동작 확인.


# ---------------------------------------------------------------------------
# Hierarchical chunker heading_path (회귀 가드)
# ---------------------------------------------------------------------------


async def test_hierarchical_chunker_sets_heading_path() -> None:
    """hierarchical chunker 가 parent_path → chunk.source_location.heading_path 설정."""
    from src.pipeline.chunkers.hierarchical import HierarchicalChunker, Section

    chunker = HierarchicalChunker(_make_config())
    sections = [
        Section(
            title="Top",
            level=1,
            content=["문단 1 내용. 길이가 충분히 긴 본문 문단입니다."],
            children=[
                Section(
                    title="Sub",
                    level=2,
                    content=["하위 섹션 본문 1. 길이가 충분히 긴 본문 문단입니다."],
                    children=[],
                    page_number=2,
                ),
            ],
            page_number=1,
        ),
    ]
    chunks = chunker._sections_to_chunks(
        sections, document_id=uuid4(), source_file_path="x.md", parent_path=[]
    )
    assert len(chunks) >= 2
    # Top section chunk → heading_path = ["Top"]
    top_chunks = [c for c in chunks if c.source_location.heading_path == ["Top"]]
    sub_chunks = [
        c for c in chunks if c.source_location.heading_path == ["Top", "Sub"]
    ]
    assert len(top_chunks) >= 1
    assert len(sub_chunks) >= 1


# ---------------------------------------------------------------------------
# SoT 동등성 — block.source_location ↔ chunk.source_location
# ---------------------------------------------------------------------------


async def test_block_to_chunk_heading_path_sot_equivalence() -> None:
    """block.source_location.heading_path 가 chunker 단계에서 chunk 로 전파.

    block_worker 가 BlockObject.source_location 에 heading_path 를 설정한 후,
    그 SourceLocation 이 chunker 의 sources 인자로 전달되면 chunk 에 동일 값 상속.
    """
    chunker = SemanticChunker(_make_config())

    # 시뮬레이션: block_worker 가 heading_propagator 로 채운 source_location.
    block_sl = SourceLocation(
        file_path="/data/policy.md",
        page_number=3,
        heading_path=["3. 위험 관리", "3.2 운영 리스크"],
    )

    sentences = ["운영 리스크는 핵심 관리 대상이다."]
    sources = [block_sl]
    chunks = chunker._build_chunks(
        sentences, sources, split_points=[], document_id=uuid4()
    )
    assert len(chunks) == 1
    # SoT 동등성: chunk.source_location.heading_path == block.source_location.heading_path.
    assert (
        chunks[0].source_location.heading_path
        == block_sl.heading_path
    )
