"""D31a (#206 v5) — schema + chunker propagation unit tests.

40+ 케이스 커버:
- InputBlock / MergedChunk schema 후방 호환 + 신규 필드
- aggregate_provenance / aggregate_extracted_metadata / KC marker allowlist
- merged_chunk_builder 풀세트 inject + deepcopy 방어
- SemanticBlockMerger / TypeAwareChunker._make_chunk metadata 보존
- import layering (src → scripts 의존 0)
"""
from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from scripts.seed.semantic_block_merger import (
    InputBlock as ScriptsInputBlock,
    MergedChunk as ScriptsMergedChunk,
    SemanticBlockMerger,
)
from src.pipeline.enrichers.chunk_metadata_propagator import (
    _KC_MARKER_KEYS,
    _flatten_entities,
    aggregate_block_metadata,
    aggregate_extracted_metadata,
    aggregate_provenance,
    es_normalize_entities,
    es_normalize_keywords,
    propagate,
)
from src.pipeline.models.chunking import InputBlock, MergedChunk
from src.pipeline.processing.merged_chunk_builder import build_merged_chunk


# ── 1. InputBlock schema (5) ─────────────────────────────────────────────────


class TestInputBlockSchema:
    def test_4_positional_back_compat(self) -> None:
        b = InputBlock(uuid4(), "paragraph", "hi", 0)
        assert b.metadata == {}
        assert b.contextual_prefix is None
        assert b.extracted_metadata is None
        assert b.source_location == {}
        assert b.block_hash == ""

    def test_full_kwargs(self) -> None:
        bid = uuid4()
        b = InputBlock(
            block_id=bid,
            block_type="paragraph",
            content="content",
            block_index=3,
            metadata={"topic_tags": ["a"]},
            contextual_prefix="prefix",
            extracted_metadata={"keywords": ["k1"]},
            source_location={"page": 2},
            block_hash="abc",
        )
        assert b.block_id == bid
        assert b.metadata == {"topic_tags": ["a"]}
        assert b.contextual_prefix == "prefix"
        assert b.extracted_metadata == {"keywords": ["k1"]}
        assert b.source_location == {"page": 2}
        assert b.block_hash == "abc"

    def test_re_export_identity(self) -> None:
        # 옛 import 와 신규 import 가 같은 클래스
        assert InputBlock is ScriptsInputBlock

    def test_default_factories_distinct(self) -> None:
        # mutable default 가 instance 간 공유되면 안 됨
        a = InputBlock(uuid4(), "p", "a", 0)
        b = InputBlock(uuid4(), "p", "b", 1)
        a.metadata["x"] = 1
        a.source_location["page"] = 5
        assert b.metadata == {}
        assert b.source_location == {}

    def test_empty_content_safe(self) -> None:
        b = InputBlock(uuid4(), "paragraph", "", 0)
        assert b.content == ""


# ── 2. MergedChunk schema (5) ────────────────────────────────────────────────


class TestMergedChunkSchema:
    def test_basic(self) -> None:
        cid = uuid4()
        bid = uuid4()
        c = MergedChunk(
            chunk_id=uuid4(),
            content="hello",
            chunk_index=0,
            cluster_id=cid,
            source_block_ids=[bid],
            block_types=["paragraph"],
            primary_block_id=bid,
        )
        assert c.char_count == 5
        assert c.merged_metadata == {}
        assert c.contextual_prefix is None

    def test_full(self) -> None:
        bid = uuid4()
        c = MergedChunk(
            chunk_id=uuid4(),
            content="abc",
            chunk_index=1,
            cluster_id=uuid4(),
            source_block_ids=[bid],
            block_types=["paragraph"],
            primary_block_id=bid,
            merged_metadata={"k": "v"},
            contextual_prefix="px",
            source_block_hashes=["hash"],
            source_locations=[{"page": 1}],
        )
        assert c.merged_metadata == {"k": "v"}
        assert c.contextual_prefix == "px"

    def test_post_init_char_count(self) -> None:
        bid = uuid4()
        c = MergedChunk(
            chunk_id=uuid4(),
            content="123456",
            chunk_index=0,
            cluster_id=uuid4(),
            source_block_ids=[bid],
            block_types=["p"],
            primary_block_id=bid,
        )
        assert c.char_count == 6

    def test_re_export_identity(self) -> None:
        assert MergedChunk is ScriptsMergedChunk

    def test_default_factories_distinct(self) -> None:
        bid = uuid4()
        a = MergedChunk(uuid4(), "a", 0, uuid4(), [bid], ["p"], bid)
        b = MergedChunk(uuid4(), "b", 0, uuid4(), [bid], ["p"], bid)
        a.merged_metadata["x"] = 1
        a.source_block_hashes.append("h")
        a.source_locations.append({"page": 1})
        assert b.merged_metadata == {}
        assert b.source_block_hashes == []
        assert b.source_locations == []


# ── 3. propagator full set (8) ───────────────────────────────────────────────


class TestPropagatorFull:
    def test_aggregate_provenance_kc_marker(self) -> None:
        metas = [
            {"source": "llm_summary", "generated": True},
            {"crosslinks": ["b1", "b2"]},
            {"is_decorative": False, "kc_owned": True},
        ]
        out = aggregate_provenance(metas)
        assert out["source"] == "llm_summary"
        assert out["generated"] is True
        assert out["kc_owned"] is True
        assert "b1" in out["crosslinks"]
        assert "b2" in out["crosslinks"]

    def test_aggregate_provenance_empty(self) -> None:
        assert aggregate_provenance([]) == {}

    def test_aggregate_provenance_kc_owned_prefix(self) -> None:
        metas = [{"_kc_owned_contextual_prefix": "kc-prefix"}]
        out = aggregate_provenance(metas)
        assert out["_kc_owned_contextual_prefix"] == "kc-prefix"

    def test_aggregate_provenance_marker_keys_constant(self) -> None:
        # KC marker allowlist 고정
        for k in (
            "source",
            "generated",
            "crosslinks",
            "kc_owned",
            "_kc_owned_contextual_prefix",
            "_kc_owned_extracted_metadata",
        ):
            assert k in _KC_MARKER_KEYS

    def test_propagate_with_extracted_meta(self) -> None:
        chunk_meta: dict = {}
        ext = [{"keywords": ["k1", "k2"]}, {"keywords": ["k2", "k3"]}]
        propagate(chunk_meta, [], source_extracted_meta=ext)
        assert "keywords" in chunk_meta
        # dedup
        assert chunk_meta["keywords"].count("k2") == 1

    def test_propagate_existing_value_preserved(self) -> None:
        chunk_meta = {"topic_tags": ["preexisting"]}
        propagate(chunk_meta, [{"topic_tags": ["new"]}])
        # 기존 값 보호
        assert chunk_meta["topic_tags"] == ["preexisting"]

    def test_propagate_no_block_meta_no_op(self) -> None:
        chunk_meta = {"x": 1}
        out = propagate(chunk_meta, [])
        assert out is chunk_meta
        assert out == {"x": 1}

    def test_aggregate_block_metadata_back_compat(self) -> None:
        metas = [{"topic_tags": ["a"]}, {"search_summary": "summary"}]
        out = aggregate_block_metadata(metas)
        assert out["topic_tags"] == ["a"]
        assert out["search_summaries"] == ["summary"]


# ── 4. aggregate_extracted_metadata (4 — v5 fix 4) ───────────────────────────


class TestAggregateExtractedMetadata:
    def test_single(self) -> None:
        out = aggregate_extracted_metadata([{"keywords": ["k1", "k2"]}])
        assert out["keywords"] == ["k1", "k2"]

    def test_multiple_dedup(self) -> None:
        out = aggregate_extracted_metadata([
            {"keywords": ["a", "b"]},
            {"keywords": ["b", "c"]},
        ])
        assert out["keywords"] == ["a", "b", "c"]

    def test_empty(self) -> None:
        assert aggregate_extracted_metadata([]) == {}
        assert aggregate_extracted_metadata([{}, {}]) == {}

    def test_full(self) -> None:
        out = aggregate_extracted_metadata([
            {
                "keywords": ["k1"],
                "entities": ["e1"],
                "topic": "t1",
                "topics": ["t2", "t3"],
            },
        ])
        assert out["keywords"] == ["k1"]
        assert out["entities"] == ["e1"]
        assert "t1" in out["topics"]
        assert "t2" in out["topics"]


# ── 5. _es_normalize_entities (6 — v5 fix 4) ────────────────────────────────
# es normalizer 함수가 §4.4 D31c reseed_v4 에서 정의될 예정이므로 D31a 단계에서는
# aggregate_extracted_metadata 의 entities flatten 로 대체 검증.


class TestEntitiesFlatten:
    def test_list_str(self) -> None:
        out = aggregate_extracted_metadata([{"entities": ["홍길동", "강남구청"]}])
        assert "홍길동" in out["entities"]
        assert "강남구청" in out["entities"]

    def test_dict_list(self) -> None:
        out = aggregate_extracted_metadata([
            {"entities": {"people": ["홍길동"], "orgs": ["강남구청"]}},
        ])
        assert "홍길동" in out["entities"]
        assert "강남구청" in out["entities"]

    def test_dict_nested_str(self) -> None:
        out = aggregate_extracted_metadata([
            {"entities": {"product": "Laptop"}},
        ])
        assert "Laptop" in out["entities"]

    def test_mixed_aggregate(self) -> None:
        out = aggregate_extracted_metadata([
            {"entities": ["A"]},
            {"entities": {"orgs": ["B"]}},
        ])
        assert "A" in out["entities"]
        assert "B" in out["entities"]

    def test_dedup(self) -> None:
        out = aggregate_extracted_metadata([
            {"entities": ["dup", "dup"]},
            {"entities": ["dup"]},
        ])
        assert out["entities"].count("dup") == 1

    def test_cap_20(self) -> None:
        many = [f"e{i}" for i in range(25)]
        out = aggregate_extracted_metadata([{"entities": many}])
        assert len(out["entities"]) <= 20


# ── 6. merged_chunk_builder + semantic merger metadata (6) ───────────────────


class TestMergedChunkBuilder:
    def _block(self, idx: int, **kw) -> InputBlock:
        return InputBlock(
            block_id=uuid4(),
            block_type="paragraph",
            content=f"text {idx}",
            block_index=idx,
            **kw,
        )

    def test_metadata_propagated(self) -> None:
        b = self._block(
            0,
            metadata={"topic_tags": ["sales"]},
            extracted_metadata={"keywords": ["foo"]},
            contextual_prefix="ctx-prefix",
            source_location={"page": 1},
            block_hash="h0",
        )
        c = build_merged_chunk(
            text="content",
            source_blocks=[b],
            cluster_id=uuid4(),
            chunk_index=0,
        )
        assert c.merged_metadata.get("topic_tags") == ["sales"]
        assert c.merged_metadata.get("keywords") == ["foo"]
        assert c.contextual_prefix == "ctx-prefix"
        assert c.source_block_hashes == ["h0"]
        assert c.source_locations == [{"page": 1}]

    def test_kc_marker_propagated(self) -> None:
        b = self._block(
            0,
            metadata={"generated": True, "source": "llm_summary"},
        )
        c = build_merged_chunk(
            text="t", source_blocks=[b], cluster_id=uuid4(), chunk_index=0
        )
        assert c.merged_metadata.get("generated") is True
        assert c.merged_metadata.get("source") == "llm_summary"

    def test_empty_blocks_safe(self) -> None:
        c = build_merged_chunk(
            text="orphan", source_blocks=[], cluster_id=uuid4(), chunk_index=0
        )
        assert c.merged_metadata == {}
        assert c.contextual_prefix is None
        assert c.source_block_ids == []

    def test_force_split_metadata_shared(self) -> None:
        # 같은 source_blocks reference 로 build 된 두 chunk 가 metadata 독립 (deepcopy)
        b = self._block(0, metadata={"topic_tags": ["t"]})
        c1 = build_merged_chunk(text="a", source_blocks=[b], cluster_id=uuid4(), chunk_index=0)
        c2 = build_merged_chunk(text="b", source_blocks=[b], cluster_id=uuid4(), chunk_index=1)
        c1.merged_metadata["topic_tags"].append("MUTATED")
        # c2 metadata 영향 없음 (deepcopy 보장)
        assert "MUTATED" not in c2.merged_metadata.get("topic_tags", [])

    def test_source_locations_deepcopy(self) -> None:
        loc = {"page": 5}
        b = self._block(0, source_location=loc)
        c = build_merged_chunk(
            text="t", source_blocks=[b], cluster_id=uuid4(), chunk_index=0
        )
        loc["page"] = 999
        # deepcopy → c 의 location 독립
        assert c.source_locations[0]["page"] == 5

    def test_semantic_merger_uses_helper(self) -> None:
        # SemanticBlockMerger 가 build_merged_chunk 경로로 metadata 전파
        merger = SemanticBlockMerger(min_chars=10, max_chars=200)
        blocks = [
            InputBlock(
                uuid4(), "paragraph", "안녕하세요. 첫 문장입니다.", 0,
                metadata={"topic_tags": ["greeting"]}, block_hash="h0",
            ),
            InputBlock(
                uuid4(), "paragraph", "두 번째 문장입니다. 추가 정보가 있습니다.", 1,
                metadata={"topic_tags": ["info"]}, block_hash="h1",
            ),
        ]
        chunks = merger.merge(blocks)
        assert chunks
        first = chunks[0]
        # metadata 풀세트 확인 — topic_tags 합산
        assert "topic_tags" in first.merged_metadata
        assert first.source_block_hashes  # 비어있지 않음


# ── 7. type_aware_chunker metadata (6) ───────────────────────────────────────


class TestTypeAwareChunkerMetadata:
    def test_paragraph_strategy(self) -> None:
        from src.pipeline.chunkers.type_aware_chunker import TypeAwareChunker

        blocks = [
            InputBlock(
                uuid4(), "paragraph", "first paragraph 입니다. 매우 좋습니다.", 0,
                metadata={"topic_tags": ["A"]},
                block_hash="h0",
            ),
            InputBlock(
                uuid4(), "paragraph", "second paragraph 입니다. 매우 좋습니다.", 1,
                metadata={"topic_tags": ["B"]},
                block_hash="h1",
            ),
        ]
        result = TypeAwareChunker().chunk(blocks, document_type="manual")
        assert result.chunks
        # chunk 가 metadata 갖고 있는지
        first = result.chunks[0]
        # source_block_ids 채워짐
        assert len(first.source_block_ids) >= 1

    def test_make_chunk_uses_helper(self) -> None:
        from src.pipeline.chunkers.type_aware_chunker import TypeAwareChunker

        b = InputBlock(
            uuid4(), "paragraph", "x", 0,
            metadata={"topic_tags": ["X"]},
            extracted_metadata={"keywords": ["kw"]},
        )
        c = TypeAwareChunker._make_chunk("xx", [b], uuid4(), 0)
        assert c.merged_metadata.get("topic_tags") == ["X"]
        assert c.merged_metadata.get("keywords") == ["kw"]

    def test_empty_blocks(self) -> None:
        from src.pipeline.chunkers.type_aware_chunker import TypeAwareChunker

        c = TypeAwareChunker._make_chunk("orphan", [], uuid4(), 0)
        assert c.merged_metadata == {}
        assert c.source_block_ids == []

    def test_contextual_prefix_propagated(self) -> None:
        from src.pipeline.chunkers.type_aware_chunker import TypeAwareChunker

        b = InputBlock(
            uuid4(), "paragraph", "x", 0,
            contextual_prefix="my-prefix",
        )
        c = TypeAwareChunker._make_chunk("xx", [b], uuid4(), 0)
        assert c.contextual_prefix == "my-prefix"

    def test_source_location_propagated(self) -> None:
        from src.pipeline.chunkers.type_aware_chunker import TypeAwareChunker

        b = InputBlock(
            uuid4(), "paragraph", "x", 0,
            source_location={"page": 7},
        )
        c = TypeAwareChunker._make_chunk("xx", [b], uuid4(), 0)
        assert c.source_locations == [{"page": 7}]

    def test_block_hash_propagated(self) -> None:
        from src.pipeline.chunkers.type_aware_chunker import TypeAwareChunker

        b = InputBlock(uuid4(), "paragraph", "x", 0, block_hash="myhash")
        c = TypeAwareChunker._make_chunk("xx", [b], uuid4(), 0)
        assert c.source_block_hashes == ["myhash"]


# ── 8. import layering (2 — v5 fix 4) ────────────────────────────────────────


class TestImportLayering:
    """src/pipeline/{processing,models}/* 가 scripts.* 를 import 하지 않음."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "src/pipeline/processing/merged_chunk_builder.py",
            "src/pipeline/models/chunking.py",
        ],
    )
    def test_no_scripts_import(self, rel_path: str) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / rel_path).read_text(encoding="utf-8")
        tree = ast.parse(text)
        bad: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("scripts"):
                        bad.append(a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("scripts"):
                    bad.append(node.module)
        assert not bad, f"{rel_path} imports scripts: {bad}"

    def test_re_export_works(self) -> None:
        # 옛 import 경로 동작 확인
        from scripts.seed.semantic_block_merger import (  # noqa: F401
            InputBlock as IB,
            MergedChunk as MC,
            SemanticBlockMerger as SBM,
        )
        assert IB is InputBlock
        assert MC is MergedChunk


# ── 9. _es_normalize_entities / keywords (사후 패치 — D31a) ──────────────────


class TestESNormalizers:
    def test_entities_list_str(self) -> None:
        assert es_normalize_entities({"entities": ["A", "B"]}) == ["A", "B"]

    def test_entities_dict_list(self) -> None:
        out = es_normalize_entities(
            {"entities": {"people": ["A"], "orgs": ["B"]}}
        )
        assert "A" in out and "B" in out

    def test_entities_extracted_metadata_list(self) -> None:
        out = es_normalize_entities(
            {"extracted_metadata": {"entities": ["X"]}}
        )
        assert "X" in out

    def test_entities_extracted_metadata_dict(self) -> None:
        out = es_normalize_entities(
            {"extracted_metadata": {"entities": {"orgs": ["Y"]}}}
        )
        assert "Y" in out

    def test_entities_dedup(self) -> None:
        out = es_normalize_entities(
            {"entities": ["dup", "dup"], "extracted_metadata": {"entities": ["dup"]}}
        )
        assert out.count("dup") == 1

    def test_entities_cap_20(self) -> None:
        many = [f"e{i}" for i in range(30)]
        out = es_normalize_entities({"entities": many})
        assert len(out) <= 20

    def test_keywords_combined(self) -> None:
        out = es_normalize_keywords(
            {
                "query_keywords": ["q1"],
                "topic_tags": ["t1"],
                "keywords": ["k1"],
                "extracted_metadata": {"keywords": ["k2"]},
            }
        )
        for k in ("q1", "t1", "k1", "k2"):
            assert k in out

    def test_keywords_dedup_cap(self) -> None:
        out = es_normalize_keywords(
            {"keywords": ["dup"] * 30, "topic_tags": ["dup"]}
        )
        assert out.count("dup") == 1
        assert len(out) <= 20


# ── 10. pickle compat (사후 패치) ────────────────────────────────────────────


class TestPickleCompat:
    def test_old_state_input_block_default_fill(self) -> None:
        # 옛 pickle state — 기존 4 필드만
        ib = InputBlock.__new__(InputBlock)
        ib.__setstate__(
            {
                "block_id": uuid4(),
                "block_type": "paragraph",
                "content": "x",
                "block_index": 0,
            }
        )
        assert ib.metadata == {}
        assert ib.contextual_prefix is None
        assert ib.extracted_metadata is None
        assert ib.source_location == {}
        assert ib.block_hash == ""

    def test_old_state_merged_chunk_default_fill(self) -> None:
        bid = uuid4()
        mc = MergedChunk.__new__(MergedChunk)
        mc.__setstate__(
            {
                "chunk_id": uuid4(),
                "content": "abcd",
                "chunk_index": 0,
                "cluster_id": uuid4(),
                "source_block_ids": [bid],
                "block_types": ["paragraph"],
                "primary_block_id": bid,
            }
        )
        assert mc.merged_metadata == {}
        assert mc.contextual_prefix is None
        assert mc.source_block_hashes == []
        assert mc.source_locations == []
        assert mc.char_count == 4
        assert mc.sentence_count == 0

    def test_full_pickle_roundtrip(self) -> None:
        import pickle

        b = InputBlock(
            uuid4(), "paragraph", "x", 0,
            metadata={"k": "v"},
            block_hash="h",
        )
        b2 = pickle.loads(pickle.dumps(b))
        assert b2.metadata == {"k": "v"}
        assert b2.block_hash == "h"


# ── 11. propagate KC markers None vs empty list (사후 패치) ─────────────────


class TestPropagateKCMarkersDistinction:
    def test_kc_markers_empty_list_explicit(self) -> None:
        chunk_meta: dict = {}
        # source_kc_markers=[] 명시 → KC marker 0건 (provenance 빈 dict)
        propagate(
            chunk_meta,
            [{"generated": True}],  # source_blocks_meta 에는 KC marker 있지만
            source_kc_markers=[],   # 명시적으로 빈 list 우선 — KC marker 적용 X
        )
        assert "generated" not in chunk_meta

    def test_kc_markers_none_fallback(self) -> None:
        chunk_meta: dict = {}
        # source_kc_markers=None → source_blocks_meta 에서 KC marker 추출
        propagate(chunk_meta, [{"generated": True}])
        assert chunk_meta.get("generated") is True


# ── 12. _flatten_entities (사후 패치) ─────────────────────────────────────


class TestFlattenEntities:
    def test_nested_dict_str(self) -> None:
        out = _flatten_entities({"product": "Laptop"})
        assert "Laptop" in out

    def test_nested_dict_dict(self) -> None:
        out = _flatten_entities({"category": {"sub": ["A"]}})
        assert "A" in out

    def test_list_with_dict(self) -> None:
        out = _flatten_entities([{"orgs": ["B"]}])
        assert "B" in out


# ── 13. extracted_metadata query_keywords/synonyms (사후 패치) ────────────


class TestExtractedQueryKeywordsSynonyms:
    def test_query_keywords_aggregated(self) -> None:
        out = aggregate_extracted_metadata([
            {"query_keywords": ["q1", "q2"]},
            {"query_keywords": ["q2", "q3"]},
        ])
        assert "query_keywords" in out
        assert out["query_keywords"].count("q2") == 1

    def test_synonyms_aggregated(self) -> None:
        out = aggregate_extracted_metadata([
            {"synonyms": ["s1"]},
            {"synonyms": ["s2"]},
        ])
        assert "synonyms" in out
        assert "s1" in out["synonyms"]
        assert "s2" in out["synonyms"]

    def test_synonyms_dict_flatten(self) -> None:
        # 사후2 패치 — synonyms dict 형태도 안전
        out = aggregate_extracted_metadata([
            {"synonyms": {"by_lang": ["s_kr", "s_en"]}},
        ])
        assert "s_kr" in out["synonyms"]
        assert "s_en" in out["synonyms"]

    def test_topic_singular_and_topics(self) -> None:
        # 사후2 패치 — topic singular 도 보강
        out = aggregate_extracted_metadata([
            {"topics": ["t1", "t2"]},
        ])
        assert out["topics"] == ["t1", "t2"]
        assert out["topic"] == "t1"


# ── 14. underscore alias (사후2 패치) ────────────────────────────────────────


class TestUnderscoreAlias:
    def test_underscore_es_normalize_entities(self) -> None:
        from src.pipeline.enrichers.chunk_metadata_propagator import (
            _es_normalize_entities,
        )

        out = _es_normalize_entities({"entities": ["A"]})
        assert "A" in out

    def test_underscore_es_normalize_keywords(self) -> None:
        from src.pipeline.enrichers.chunk_metadata_propagator import (
            _es_normalize_keywords,
        )

        out = _es_normalize_keywords({"keywords": ["k"]})
        assert "k" in out
