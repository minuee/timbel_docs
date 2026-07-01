"""D31b unit tests — `_PipelineBlock` + `FullPipelineResult.blocks_full`.

Spec v4 §5 — 40+ unit test (5.1 ~ 5.6 + canonical move smoke).

본 파일: §5.1 / §5.2 / §5.3 / §5.4 / §5.5 / §5.6 — 32+ 케이스.
canonical move smoke 6 + 본 파일 32+ + identity 6 = 합계 ≥ 40.
"""
from __future__ import annotations

import copy
from uuid import UUID, uuid4

import pytest

from src.pipeline.full_pipeline import (
    FullPipelineResult,
    _PipelineBlock,
    _compute_block_hash,
    _to_input_block,
    process_document_full,
)
from src.pipeline.models.chunking import InputBlock, MergedChunk


# ────────────────────────────────────────────────────────────────────────
# §5.1 — _PipelineBlock 생성 + validation (≥ 8)
# ────────────────────────────────────────────────────────────────────────


class TestPipelineBlockSchema:
    """§5.1 — _PipelineBlock 생성 + validation."""

    def test_full_kwargs_construction(self) -> None:
        """case 1 — 풀 인자 dataclass 생성."""
        bid = uuid4()
        pb = _PipelineBlock(
            block_id=bid,
            block_type="paragraph",
            content="hello",
            block_index=0,
            metadata={"a": 1},
            contextual_prefix="prefix",
            extracted_metadata={"keywords": ["k"]},
            source_location={"page": 1},
            block_hash="hash",
            kc_markers={"kc_owned": True},
        )
        assert pb.block_id == bid
        assert pb.block_type == "paragraph"
        assert pb.content == "hello"
        assert pb.block_index == 0
        assert pb.metadata == {"a": 1}
        assert pb.contextual_prefix == "prefix"
        assert pb.extracted_metadata == {"keywords": ["k"]}
        assert pb.source_location == {"page": 1}
        assert pb.block_hash == "hash"
        assert pb.kc_markers == {"kc_owned": True}

    def test_4_positional_construction(self) -> None:
        """case 2 — 4 positional (block_id/type/content/index) — default 채움."""
        bid = uuid4()
        pb = _PipelineBlock(bid, "paragraph", "hello", 0)
        assert pb.metadata == {}
        assert pb.kc_markers == {}
        assert pb.block_hash == ""
        assert pb.source_location == {}
        assert pb.extracted_metadata is None
        assert pb.contextual_prefix is None

    def test_metadata_default_empty_dict(self) -> None:
        """case 3 — metadata default = {}."""
        pb = _PipelineBlock(uuid4(), "p", "c", 0)
        assert isinstance(pb.metadata, dict) and not pb.metadata

    def test_kc_markers_default_empty_dict(self) -> None:
        """case 4 — kc_markers default = {}."""
        pb = _PipelineBlock(uuid4(), "p", "c", 0)
        assert isinstance(pb.kc_markers, dict) and not pb.kc_markers

    def test_block_hash_default_empty_string(self) -> None:
        """case 5 — block_hash default = ""."""
        pb = _PipelineBlock(uuid4(), "p", "c", 0)
        assert pb.block_hash == ""

    def test_source_location_default_empty_dict(self) -> None:
        """case 6 — source_location default = {}."""
        pb = _PipelineBlock(uuid4(), "p", "c", 0)
        assert isinstance(pb.source_location, dict) and not pb.source_location

    def test_extracted_metadata_default_none(self) -> None:
        """case 7 — extracted_metadata default = None."""
        pb = _PipelineBlock(uuid4(), "p", "c", 0)
        assert pb.extracted_metadata is None

    def test_compute_block_hash_idempotent(self) -> None:
        """case 8 — _compute_block_hash 같은 (idx, content) → 같은 hash."""
        h1 = _compute_block_hash("hello", 5)
        h2 = _compute_block_hash("hello", 5)
        assert h1 == h2
        # 다른 idx → 다른 hash
        h3 = _compute_block_hash("hello", 6)
        assert h1 != h3
        # 다른 content → 다른 hash
        h4 = _compute_block_hash("world", 5)
        assert h1 != h4


# ────────────────────────────────────────────────────────────────────────
# §5.2 — _to_input_block 변환 (≥ 6)
# ────────────────────────────────────────────────────────────────────────


class TestToInputBlock:
    """§5.2 — _to_input_block 1:1 변환 + deepcopy + kc_markers allowlist."""

    def test_full_metadata_round_trip(self) -> None:
        """case 9 — 풀 metadata 1:1 복사."""
        bid = uuid4()
        pb = _PipelineBlock(
            block_id=bid,
            block_type="paragraph",
            content="hello",
            block_index=2,
            metadata={"topic_tags": ["x"]},
            contextual_prefix="prefix",
            extracted_metadata={"keywords": ["k1"]},
            source_location={"page": 1},
            block_hash="abc",
            kc_markers={},
        )
        ib = _to_input_block(pb)
        assert isinstance(ib, InputBlock)
        assert ib.block_id == bid
        assert ib.block_type == "paragraph"
        assert ib.content == "hello"
        assert ib.block_index == 2
        assert ib.metadata == {"topic_tags": ["x"]}
        assert ib.contextual_prefix == "prefix"
        assert ib.extracted_metadata == {"keywords": ["k1"]}
        assert ib.source_location == {"page": 1}
        assert ib.block_hash == "abc"

    def test_metadata_deepcopy_isolation(self) -> None:
        """case 10 — metadata 변경 시 InputBlock 영향 0 (top-level)."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0, metadata={"a": 1}, block_hash="h"
        )
        ib = _to_input_block(pb)
        pb.metadata["a"] = 999
        pb.metadata["b"] = "added"
        assert ib.metadata == {"a": 1}

    def test_extracted_metadata_none_preserved(self) -> None:
        """case 11 — extracted_metadata None → None preserve."""
        pb = _PipelineBlock(uuid4(), "p", "c", 0, extracted_metadata=None)
        ib = _to_input_block(pb)
        assert ib.extracted_metadata is None

    def test_extracted_metadata_dict_isolation(self) -> None:
        """case 12 — extracted_metadata mutation 격리."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0, extracted_metadata={"keywords": ["k"]}
        )
        ib = _to_input_block(pb)
        pb.extracted_metadata["keywords"].append("evil")
        # nested list 도 deepcopy 되어야 함
        assert ib.extracted_metadata == {"keywords": ["k"]}

    def test_kc_markers_promotion_to_metadata(self) -> None:
        """case 13 — allowlist 안 kc_markers 가 metadata 로 promotion."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            metadata={"existing": True},
            kc_markers={"kc_owned": True, "kc_compiled_at": "2026-05-08"},
        )
        ib = _to_input_block(pb)
        assert ib.metadata.get("existing") is True
        assert ib.metadata.get("kc_owned") is True
        assert ib.metadata.get("kc_compiled_at") == "2026-05-08"

    def test_empty_kc_markers_no_op(self) -> None:
        """case 14 — kc_markers 빈 dict 시 metadata mutation 0."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            metadata={"a": 1},
            kc_markers={},
        )
        ib = _to_input_block(pb)
        assert ib.metadata == {"a": 1}


# ────────────────────────────────────────────────────────────────────────
# §5.3 — FullPipelineResult.blocks_full (≥ 6)
# ────────────────────────────────────────────────────────────────────────


class TestFullPipelineResultBlocksFull:
    """§5.3 — FullPipelineResult.blocks_full 노출."""

    def test_default_blocks_full_empty(self) -> None:
        """case 15 — default 시 blocks_full = []."""
        r = FullPipelineResult(
            document_id=uuid4(), title="t",
            blocks=[], chunks=[], noise_blocks=[],
        )
        assert r.blocks_full == []
        assert r.noise_blocks_full == []

    @pytest.mark.asyncio
    async def test_markdown_invariant_lengths(self) -> None:
        """case 16 — process_document_full markdown 결과 invariant 길이."""
        md = "# Title\n\n첫 문단입니다." * 3
        r = await process_document_full(title="t", markdown_text=md)
        assert len(r.blocks) == len(r.blocks_full)
        assert len(r.noise_blocks) == len(r.noise_blocks_full)

    @pytest.mark.asyncio
    async def test_markdown_blocks_blocks_full_consistency(self) -> None:
        """case 17 — blocks[i] ↔ blocks_full[i] 1:1 매핑."""
        md = "# Title\n\n첫 문단입니다.\n\n둘째 문단입니다."
        r = await process_document_full(title="t", markdown_text=md)
        for i, (btype, content, bid) in enumerate(r.blocks):
            pb = r.blocks_full[i]
            assert pb.block_type == btype
            assert pb.content == content
            assert pb.block_id == bid

    @pytest.mark.asyncio
    async def test_noise_blocks_full_metadata(self) -> None:
        """case 18 — noise_blocks_full[*].metadata.is_noise == True."""
        md = "# Title\n\n실제 본문입니다.\n\n2 / 3"  # `2 / 3` 은 노이즈 패턴
        r = await process_document_full(title="t", markdown_text=md)
        for pb in r.noise_blocks_full:
            assert pb.metadata.get("is_noise") is True

    @pytest.mark.asyncio
    async def test_blocks_full_block_hash_filled(self) -> None:
        """case 19 — blocks_full[*].block_hash 모두 non-empty."""
        md = "# Title\n\n문단1\n\n문단2"
        r = await process_document_full(title="t", markdown_text=md)
        for pb in r.blocks_full:
            assert pb.block_hash != ""
            assert len(pb.block_hash) == 64  # sha256 hex

    @pytest.mark.asyncio
    async def test_content_blocks_no_is_noise_marker(self) -> None:
        """case 20 — content blocks_full 의 metadata 에 is_noise=True 없음."""
        md = "# Title\n\n문단1입니다.\n\n문단2입니다."
        r = await process_document_full(title="t", markdown_text=md)
        for pb in r.blocks_full:
            assert pb.metadata.get("is_noise") is not True


# ────────────────────────────────────────────────────────────────────────
# §5.4 — backward compat (≥ 6)
# ────────────────────────────────────────────────────────────────────────


class TestBackwardCompat:
    """§5.4 — 기존 caller 가 변경 없이 동작."""

    @pytest.mark.asyncio
    async def test_blocks_3tuple_unpacking(self) -> None:
        """case 21 — result.blocks 3-tuple unpack OK."""
        md = "# T\n\n첫 줄"
        r = await process_document_full(title="t", markdown_text=md)
        for btype, content, bid in r.blocks:
            assert isinstance(btype, str)
            assert isinstance(content, str)
            assert isinstance(bid, UUID)

    @pytest.mark.asyncio
    async def test_noise_blocks_3tuple_unpacking(self) -> None:
        """case 22 — result.noise_blocks 3-tuple unpack OK."""
        md = "# T\n\n실제 본문 입니다.\n\n1 / 2"
        r = await process_document_full(title="t", markdown_text=md)
        for btype, content, bid in r.noise_blocks:
            assert isinstance(btype, str)
            assert isinstance(content, str)
            assert isinstance(bid, UUID)

    @pytest.mark.asyncio
    async def test_chunks_unchanged(self) -> None:
        """case 23 — result.chunks 가 MergedChunk list — D31a propagation 동작."""
        md = "# T\n\n첫 문단 의미 보존 테스트입니다."
        r = await process_document_full(title="t", markdown_text=md)
        assert all(isinstance(c, MergedChunk) for c in r.chunks)

    @pytest.mark.asyncio
    async def test_processing_meta_unchanged_keys(self) -> None:
        """case 24 — result.processing_meta 기존 키 모두 보존."""
        md = "# T\n\n본문"
        r = await process_document_full(title="t", markdown_text=md)
        assert "pipeline_version" in r.processing_meta
        assert "upload_source" in r.processing_meta
        assert "stage1" in r.processing_meta
        assert "chunker" in r.processing_meta

    @pytest.mark.asyncio
    async def test_block_type_dist_unchanged(self) -> None:
        """case 25 — block_type_dist dict — 기존 keys."""
        md = "# T\n\n본문 paragraph 1\n\n본문 paragraph 2"
        r = await process_document_full(title="t", markdown_text=md)
        assert isinstance(r.block_type_dist, dict)
        # heading_1 + paragraph 가 분포에 있어야
        assert sum(r.block_type_dist.values()) == len(r.blocks)

    @pytest.mark.asyncio
    async def test_elapsed_ms_int(self) -> None:
        """case 26 — elapsed_ms int 그대로."""
        md = "# T\n\n본문"
        r = await process_document_full(title="t", markdown_text=md)
        assert isinstance(r.elapsed_ms, int)
        assert r.elapsed_ms >= 0


# ────────────────────────────────────────────────────────────────────────
# §5.5 — chain integrity (≥ 6)
# ────────────────────────────────────────────────────────────────────────


class TestChainIntegrity:
    """§5.5 — 단계 간 metadata carrier 정합."""

    @pytest.mark.asyncio
    async def test_faq_chunks_have_merged_metadata(self) -> None:
        """case 27 — markdown FAQ → chunks merged_metadata 존재 (D31a propagation 정합)."""
        # 짧은 FAQ pattern (chunker 가 faq strategy 진입할 수 있도록)
        md = (
            "# FAQ\n\n"
            "- **질문 1:** 가입 방법\n  - **MENT:** 홈페이지 가입 절차\n\n"
            "- **질문 2:** 비밀번호 변경\n  - **MENT:** 마이페이지 → 비밀번호\n\n"
            "- **질문 3:** 결제 방법\n  - **MENT:** 카드 또는 계좌이체"
        )
        r = await process_document_full(title="t", markdown_text=md)
        # 모든 chunk 에 merged_metadata attribute 존재
        for c in r.chunks:
            assert hasattr(c, "merged_metadata")
            assert isinstance(c.merged_metadata, dict)

    @pytest.mark.asyncio
    async def test_blocks_full_block_hash_unique(self) -> None:
        """case 28 — markdown manual → blocks_full[*].block_hash 모두 unique."""
        md = "# T\n\n다른 문단 1입니다.\n\n다른 문단 2입니다.\n\n다른 문단 3입니다."
        r = await process_document_full(title="t", markdown_text=md)
        hashes = [pb.block_hash for pb in r.blocks_full]
        assert len(hashes) == len(set(hashes))

    @pytest.mark.asyncio
    async def test_empty_markdown_safe(self) -> None:
        """case 29 — 빈 markdown → blocks_full = [], noise_blocks_full = []."""
        r = await process_document_full(title="t", markdown_text="")
        assert r.blocks_full == []
        assert r.noise_blocks_full == []
        assert r.blocks == []

    @pytest.mark.asyncio
    async def test_blocks_full_filled_for_path_coverage(self) -> None:
        """case 30 — markdown 입력 → blocks_full 채움 (v3 fix 3 — source_location 검증 X)."""
        md = "# T\n\n본문 내용입니다."
        r = await process_document_full(title="t", markdown_text=md)
        assert len(r.blocks_full) > 0
        # source_location 은 D31b 단계에서 항상 빈 dict
        for pb in r.blocks_full:
            assert pb.source_location == {}

    def test_to_input_block_round_trip_safe(self) -> None:
        """case 31 — _to_input_block 변환 후 같은 schema 일치."""
        pb = _PipelineBlock(
            uuid4(), "paragraph", "text", 5,
            metadata={"k": "v"}, source_location={"page": 1},
            block_hash="h",
        )
        ib = _to_input_block(pb)
        assert ib.block_index == pb.block_index
        assert ib.content == pb.content

    @pytest.mark.asyncio
    async def test_block_index_matches_enumerate(self) -> None:
        """case 32 — _PipelineBlock.block_index == enumerate(0..)."""
        md = "# T\n\n문단 A.\n\n문단 B.\n\n문단 C."
        r = await process_document_full(title="t", markdown_text=md)
        for i, pb in enumerate(r.blocks_full):
            assert pb.block_index == i


# ────────────────────────────────────────────────────────────────────────
# §5.6 — v2 fix 6 + v4 fix 6 — nested deepcopy + kc_markers + import smoke + identity
# ────────────────────────────────────────────────────────────────────────


class TestNestedDeepcopy:
    """§5.6 — nested mutation 격리."""

    def test_nested_metadata_deepcopy(self) -> None:
        """case 33 — nested metadata mutation isolation."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            metadata={"a": {"b": [1, 2, 3]}},
        )
        ib = _to_input_block(pb)
        pb.metadata["a"]["b"].append(99)
        pb.metadata["a"]["new_key"] = "evil"
        assert ib.metadata == {"a": {"b": [1, 2, 3]}}

    def test_nested_extracted_metadata_deepcopy(self) -> None:
        """case 34 — nested extracted_metadata mutation isolation."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            extracted_metadata={"entities": {"people": ["홍길동"]}},
        )
        ib = _to_input_block(pb)
        pb.extracted_metadata["entities"]["people"].append("evil")
        assert ib.extracted_metadata == {"entities": {"people": ["홍길동"]}}

    def test_nested_source_location_deepcopy(self) -> None:
        """case 35 — nested source_location mutation isolation."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            source_location={"page": 1, "bbox": [10, 20, 30, 40]},
        )
        ib = _to_input_block(pb)
        pb.source_location["bbox"].append(99)
        pb.source_location["page"] = 999
        assert ib.source_location == {"page": 1, "bbox": [10, 20, 30, 40]}


class TestKcMarkersAllowlist:
    """§5.6 — kc_markers allowlist policy."""

    def test_kc_markers_allowlist_only(self) -> None:
        """case 36 — allowlist 안 키만 promotion, 밖은 무시."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            kc_markers={"kc_owned": True, "evil_key": "X", "another_evil": 1},
        )
        ib = _to_input_block(pb)
        assert "kc_owned" in ib.metadata
        assert "evil_key" not in ib.metadata
        assert "another_evil" not in ib.metadata

    def test_kc_markers_non_allowlisted_no_side_effects(self) -> None:
        """case 37 — allowlist 밖 key 가 다른 곳에 새지 않음."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            kc_markers={"random_key": "leak"},
        )
        ib = _to_input_block(pb)
        # InputBlock 어떤 필드에도 random_key 가 없어야
        assert "random_key" not in ib.metadata
        # contextual_prefix / extracted_metadata 도 영향 0
        assert ib.contextual_prefix is None
        assert ib.extracted_metadata is None

    def test_kc_markers_collision_metadata_wins(self) -> None:
        """case 38 — 동일 key 충돌 시 pb.metadata 우선."""
        pb = _PipelineBlock(
            uuid4(), "p", "c", 0,
            metadata={"source": "original"},
            kc_markers={"source": "kc_summary"},
        )
        ib = _to_input_block(pb)
        # setdefault 정책 — metadata 가 우선
        assert ib.metadata["source"] == "original"


class TestSourceLocationAndImports:
    """§5.6 — source_location + import smoke."""

    @pytest.mark.asyncio
    async def test_source_location_d31b_empty_unified(self) -> None:
        """case 39 — markdown 입력 시 source_location = {} unified."""
        md = "# T\n\n본문"
        r = await process_document_full(title="t", markdown_text=md)
        for pb in r.blocks_full:
            assert pb.source_location == {}
        for pb in r.noise_blocks_full:
            assert pb.source_location == {}

    def test_full_pipeline_imports_clean(self) -> None:
        """case 40 — full_pipeline.py 가 src 내부에서만 import (scripts.* 0)."""
        import ast
        from pathlib import Path

        p = Path(__file__).resolve().parents[2] / "src" / "pipeline" / "full_pipeline.py"
        tree = ast.parse(p.read_text(encoding="utf-8"))
        bad: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("scripts"):
                        bad.append(a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("scripts"):
                    bad.append(node.module)
        assert not bad, f"full_pipeline.py imports scripts: {bad}"

    def test_old_path_re_export_works(self) -> None:
        """case 41 — `from scripts.seed.semantic_block_merger import ...` 동작."""
        from scripts.seed.semantic_block_merger import (
            InputBlock,
            MergedChunk,
            SemanticBlockMerger,
        )
        assert InputBlock is not None
        assert MergedChunk is not None
        assert SemanticBlockMerger is not None

    def test_re_export_identity(self) -> None:
        """case 42 — old path 와 new path 가 동일 객체 (`Old is New`)."""
        from scripts.seed.semantic_block_merger import (
            InputBlock as OldInputBlock,
        )
        from scripts.seed.semantic_block_merger import (
            MergedChunk as OldMergedChunk,
        )
        from scripts.seed.semantic_block_merger import (
            SemanticBlockMerger as OldMerger,
        )
        from src.pipeline.models.chunking import (
            InputBlock as NewInputBlock,
        )
        from src.pipeline.models.chunking import (
            MergedChunk as NewMergedChunk,
        )
        from src.pipeline.processing.semantic_block_merger import (
            SemanticBlockMerger as NewMerger,
        )

        assert OldInputBlock is NewInputBlock
        assert OldMergedChunk is NewMergedChunk
        assert OldMerger is NewMerger
