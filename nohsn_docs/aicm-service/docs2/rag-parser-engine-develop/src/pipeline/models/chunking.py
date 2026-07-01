"""Chunker 입출력 DTO — neutral layer.

D31a (2026-05-08): scripts.seed.semantic_block_merger 에 있던 InputBlock /
MergedChunk 를 src/pipeline/models 로 이동. src → scripts 의존 제거.

#206 spec v5 §2.1 — helper layering WARN 1 닫음.

확장 필드 (D31a):
- InputBlock: metadata / contextual_prefix / extracted_metadata / source_location / block_hash
- MergedChunk: merged_metadata / contextual_prefix / source_block_hashes / source_locations
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class InputBlock:
    """병합 입력 — block 한 단위.

    block_id 는 blocks 테이블 row 의 id. content / block_type / block_index 는
    그대로 chunks 메타에 보존.

    D31a 신규 필드 (default 끝에 — 후방 호환):
    - metadata: block.metadata jsonb (topic_tags / search_summary / 기타 enrich 결과)
    - contextual_prefix: contextual retrieval prefix (KC 또는 ContextualEnricher 가 채움)
    - extracted_metadata: block.extracted_metadata (entities / keywords / topic 등)
    - source_location: {page, line_start, line_end, char_offset 등}
    - block_hash: sha256(f"{block_index:08d}::{content}") — duplicate 안전 정책
    """

    block_id: UUID
    block_type: str
    content: str
    block_index: int
    # ── 신규 (D31a) — default 끝에 추가 (후방 호환) ─────────
    metadata: dict = field(default_factory=dict)
    contextual_prefix: str | None = None
    extracted_metadata: dict | None = None
    source_location: dict = field(default_factory=dict)
    block_hash: str = ""

    def __setstate__(self, state: dict) -> None:
        """옛 pickle 객체 unpickle 시 신규 필드 default 채움.

        D31a 사후 패치 — old pickle 호환 (D31a 전 객체에는 신규 필드 없음).
        """
        self.__dict__.update(state)
        self.__dict__.setdefault("metadata", {})
        self.__dict__.setdefault("contextual_prefix", None)
        self.__dict__.setdefault("extracted_metadata", None)
        self.__dict__.setdefault("source_location", {})
        self.__dict__.setdefault("block_hash", "")


@dataclass
class MergedChunk:
    """병합 결과 — chunk 한 단위.

    source_block_ids 로 어느 block 들이 합쳐졌는지 추적.
    cluster_id 는 같은 의미 그룹 mark (검색 시 grouping 가능).

    D31a 신규 필드:
    - merged_metadata: aggregate_block_metadata + aggregate_provenance + aggregate_extracted_metadata 합본
    - contextual_prefix: 첫 source block 의 prefix (검색 payload 용 — embedding prepend 는 D32 별도)
    - source_block_hashes: chunk 가 포함하는 block 들의 block_hash list
    - source_locations: chunk 가 포함하는 block 들의 source_location list (chunk-level coverage)
    """

    chunk_id: UUID
    content: str
    chunk_index: int
    cluster_id: UUID
    source_block_ids: list[UUID]
    block_types: list[str]  # 포함된 block_type 분포
    primary_block_id: UUID  # 대표 block (첫 block) — vector_id 용
    char_count: int = 0
    sentence_count: int = 0
    # ── 신규 (D31a) — default 끝에 추가 ─────
    merged_metadata: dict = field(default_factory=dict)
    contextual_prefix: str | None = None
    source_block_hashes: list[str] = field(default_factory=list)
    source_locations: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.char_count = len(self.content)

    def __setstate__(self, state: dict) -> None:
        """옛 pickle 객체 unpickle 시 신규 필드 default 채움.

        D31a 사후 패치 — old pickle 호환.
        """
        self.__dict__.update(state)
        self.__dict__.setdefault("char_count", len(self.__dict__.get("content", "")))
        self.__dict__.setdefault("sentence_count", 0)
        self.__dict__.setdefault("merged_metadata", {})
        self.__dict__.setdefault("contextual_prefix", None)
        self.__dict__.setdefault("source_block_hashes", [])
        self.__dict__.setdefault("source_locations", [])


__all__ = ["InputBlock", "MergedChunk"]
