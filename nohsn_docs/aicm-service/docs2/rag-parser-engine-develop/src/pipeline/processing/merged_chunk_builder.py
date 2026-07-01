"""MergedChunk 빌더 — 두 chunker (SemanticBlockMerger + TypeAwareChunker) 공유.

D31a (#206 v5 §2.5) — InputBlock metadata 풀세트 → MergedChunk.merged_metadata
inject. KC marker / extracted_metadata / source_location / block_hash 모두 보존.

**의존 방향** (#206 v5 §2.1 fix 1):
이 모듈은 `src.pipeline.models.chunking` 의 InputBlock / MergedChunk 만 import.
**`scripts.seed.*` 미import** — src → scripts 의존 0.
"""
from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid4

from src.pipeline.enrichers.chunk_metadata_propagator import (
    aggregate_block_metadata,
    aggregate_extracted_metadata,
    aggregate_provenance,
)
from src.pipeline.models.chunking import InputBlock, MergedChunk


def build_merged_chunk(
    *,
    text: str,
    source_blocks: list[InputBlock] | tuple[InputBlock, ...],
    cluster_id: UUID,
    chunk_index: int,
) -> MergedChunk:
    """metadata 풀세트 inject 헬퍼 — 두 chunker 공유.

    aggregate_block_metadata + aggregate_provenance + aggregate_extracted_metadata
    호출 합본. _force_split() 시 source_blocks 가 동일 reference 면 deepcopy
    (mutation 방어).

    Args:
        text: chunk content
        source_blocks: 이 chunk 가 포함하는 InputBlock 들 (1+ 또는 빈 list 도 안전)
        cluster_id: SemanticBlockMerger 의 cluster id (TypeAwareChunker 는 uuid4)
        chunk_index: chunk 순번

    Returns:
        MergedChunk — merged_metadata / contextual_prefix / source_block_hashes /
        source_locations 모두 채워짐. 빈 source_blocks 일 때는 default 값.
    """
    blocks = list(source_blocks) if source_blocks else []
    primary_id: UUID = blocks[0].block_id if blocks else uuid4()
    primary_prefix = blocks[0].contextual_prefix if blocks else None

    merged_meta: dict[str, Any] = {}
    if blocks:
        block_metas = [b.metadata for b in blocks if b.metadata]
        if block_metas:
            merged_meta.update(aggregate_block_metadata(block_metas))
            merged_meta.update(aggregate_provenance(block_metas))
        ext_metas = [b.extracted_metadata for b in blocks if b.extracted_metadata]
        if ext_metas:
            merged_meta.update(aggregate_extracted_metadata(ext_metas))

    return MergedChunk(
        chunk_id=uuid4(),
        content=text,
        chunk_index=chunk_index,
        cluster_id=cluster_id,
        source_block_ids=[b.block_id for b in blocks],
        block_types=[b.block_type for b in blocks],
        primary_block_id=primary_id,
        sentence_count=text.count(".") + text.count("?") + text.count("!"),
        merged_metadata=copy.deepcopy(merged_meta),
        contextual_prefix=primary_prefix,
        source_block_hashes=[b.block_hash for b in blocks if b.block_hash],
        source_locations=[copy.deepcopy(b.source_location) for b in blocks if b.source_location],
    )


__all__ = ["build_merged_chunk"]
