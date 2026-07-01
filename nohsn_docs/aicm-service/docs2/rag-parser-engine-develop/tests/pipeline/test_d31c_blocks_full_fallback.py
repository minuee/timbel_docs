"""D31c §1+§2 — blocks_full fallback + chunk_meta merge unit test.

reseed_v4 의 INSERT 로직을 직접 호출하기는 DB 의존. 본 test 는 *순수 함수*
부분 (chunk_meta merge 정책 / blocks_full fallback iter 구성 / properties payload
빌드) 만 검증.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest


# ────────────────────────────────────────────────────────────────────────
# §1 — blocks_full / blocks fallback iter 정합
# ────────────────────────────────────────────────────────────────────────


@dataclass
class _StubPB:
    block_id: UUID
    block_type: str
    content: str
    block_index: int
    metadata: dict = field(default_factory=dict)
    contextual_prefix: str | None = None
    extracted_metadata: dict | None = None
    source_location: dict = field(default_factory=dict)
    block_hash: str = ""
    kc_markers: dict = field(default_factory=dict)


@dataclass
class _StubResult:
    blocks: list = field(default_factory=list)
    noise_blocks: list = field(default_factory=list)
    blocks_full: list = field(default_factory=list)
    noise_blocks_full: list = field(default_factory=list)


def _build_iters(result: _StubResult) -> tuple[list, list]:
    """reseed_v4 의 §1 iter 구성 정책 — 순수 함수로 추출."""
    blocks_full = getattr(result, "blocks_full", None) or []
    noise_blocks_full = getattr(result, "noise_blocks_full", None) or []

    if blocks_full:
        content_iter = [
            (pb.block_type, pb.content, pb.block_id, False, pb)
            for pb in blocks_full
        ]
    else:
        content_iter = [
            (btype, content, bid, False, None)
            for btype, content, bid in result.blocks
        ]

    if noise_blocks_full:
        noise_iter = [
            (pb.block_type, pb.content, pb.block_id, True, pb)
            for pb in noise_blocks_full
        ]
    else:
        noise_iter = [
            (btype, content, bid, True, None)
            for btype, content, bid in (getattr(result, "noise_blocks", None) or [])
        ]

    return content_iter, noise_iter


class TestBlocksFullFallback:
    """§1 — blocks_full 우선, blocks fallback 대칭 (v3 fix 1 + 3)."""

    def test_blocks_full_present_uses_pb(self) -> None:
        """case 1.1 — blocks_full 채워진 case → pb 객체 carry."""
        bid = uuid4()
        pb = _StubPB(
            block_id=bid,
            block_type="paragraph",
            content="hello",
            block_index=0,
            source_location={"page": 5},
        )
        result = _StubResult(blocks_full=[pb])
        content_iter, _ = _build_iters(result)
        assert len(content_iter) == 1
        btype, content, ret_bid, is_noise, ret_pb = content_iter[0]
        assert ret_pb is pb
        assert is_noise is False
        assert ret_pb.source_location == {"page": 5}

    def test_blocks_full_empty_falls_back_to_blocks(self) -> None:
        """case 1.2 — blocks_full=[] but blocks 채워진 경우 fallback."""
        bid = uuid4()
        result = _StubResult(blocks=[("paragraph", "hello", bid)])
        content_iter, _ = _build_iters(result)
        assert len(content_iter) == 1
        btype, content, ret_bid, is_noise, ret_pb = content_iter[0]
        assert btype == "paragraph"
        assert content == "hello"
        assert ret_bid == bid
        assert ret_pb is None  # fallback 에서는 pb 없음

    def test_noise_blocks_full_present(self) -> None:
        """case 1.3 — noise_blocks_full 채워진 case (대칭)."""
        bid = uuid4()
        pb = _StubPB(
            block_id=bid,
            block_type="paragraph",
            content="noise",
            block_index=0,
            metadata={"is_noise": True},
            source_location={"page": 1},
        )
        result = _StubResult(noise_blocks_full=[pb])
        _, noise_iter = _build_iters(result)
        assert len(noise_iter) == 1
        btype, content, ret_bid, is_noise, ret_pb = noise_iter[0]
        assert is_noise is True
        assert ret_pb is pb

    def test_noise_blocks_full_empty_falls_back(self) -> None:
        """case 1.4 — noise_blocks_full=[] but noise_blocks 채워진 경우 fallback."""
        bid = uuid4()
        result = _StubResult(noise_blocks=[("paragraph", "noise", bid)])
        _, noise_iter = _build_iters(result)
        assert len(noise_iter) == 1
        btype, content, ret_bid, is_noise, ret_pb = noise_iter[0]
        assert is_noise is True
        assert ret_pb is None

    def test_both_iters_combined_with_enumerate(self) -> None:
        """case 1.5 — content+noise 결합 후 enumerate idx 일관."""
        c_bid = uuid4()
        n_bid = uuid4()
        result = _StubResult(
            blocks=[("paragraph", "real", c_bid)],
            noise_blocks=[("paragraph", "noise", n_bid)],
        )
        content_iter, noise_iter = _build_iters(result)
        all_blocks = content_iter + noise_iter
        for idx, (btype, content, bid, is_noise, pb) in enumerate(all_blocks):
            if idx == 0:
                assert is_noise is False
                assert content == "real"
            else:
                assert is_noise is True
                assert content == "noise"

    def test_empty_result_returns_empty_iters(self) -> None:
        """case 1.6 — 모두 비면 iter 도 빈."""
        result = _StubResult()
        content_iter, noise_iter = _build_iters(result)
        assert content_iter == []
        assert noise_iter == []


# ────────────────────────────────────────────────────────────────────────
# §1 — properties payload 빌드 (v3 fix 1 — block_hash_v2 / pipeline_block_index)
# ────────────────────────────────────────────────────────────────────────


def _build_properties(pb) -> dict:
    """reseed_v4 의 §1.3 properties 빌더 — 순수 함수 추출."""
    return {
        "contextual_prefix": pb.contextual_prefix if pb else None,
        "extracted_metadata": pb.extracted_metadata if pb else None,
        "block_hash_v2": pb.block_hash if pb else "",
        "pipeline_block_index": pb.block_index if pb else None,
        "kc_markers": (pb.kc_markers if pb and pb.kc_markers else {}),
    }


class TestPropertiesBuilder:
    """§1.3 — properties = {contextual_prefix, extracted_metadata, block_hash_v2, pipeline_block_index, kc_markers}."""

    def test_full_properties_with_pb(self) -> None:
        """case 1.7 — pb 풀 metadata 시 properties 풀 채움."""
        pb = _StubPB(
            block_id=uuid4(),
            block_type="paragraph",
            content="x",
            block_index=42,
            contextual_prefix="prefix-A",
            extracted_metadata={"keywords": ["k"]},
            block_hash="hash-v2",
            kc_markers={"kc_owned": True},
        )
        props = _build_properties(pb)
        assert props["contextual_prefix"] == "prefix-A"
        assert props["extracted_metadata"] == {"keywords": ["k"]}
        assert props["block_hash_v2"] == "hash-v2"
        assert props["pipeline_block_index"] == 42
        assert props["kc_markers"] == {"kc_owned": True}

    def test_pb_none_fallback(self) -> None:
        """case 1.8 — pb=None 시 default properties."""
        props = _build_properties(None)
        assert props == {
            "contextual_prefix": None,
            "extracted_metadata": None,
            "block_hash_v2": "",
            "pipeline_block_index": None,
            "kc_markers": {},
        }

    def test_kc_markers_none_normalized_to_empty(self) -> None:
        """case 1.9 — kc_markers None → {} 정규화."""
        pb = _StubPB(
            block_id=uuid4(),
            block_type="paragraph",
            content="x",
            block_index=0,
            kc_markers=None,  # type: ignore
        )
        props = _build_properties(pb)
        assert props["kc_markers"] == {}


# ────────────────────────────────────────────────────────────────────────
# §2 — chunk_meta merge: base_chunk_meta 가 *마지막* overlay (reseed marker 우선)
# ────────────────────────────────────────────────────────────────────────


def _merge_chunk_meta(
    *,
    propagated: dict,
    base_chunk_meta: dict,
) -> dict:
    """v3 fix 2 — base_chunk_meta 가 마지막 overlay."""
    return {**propagated, **base_chunk_meta}


class TestChunkMetaMerge:
    """§2 — base_chunk_meta 가 마지막 overlay (reseed marker 우선)."""

    def test_base_overrides_propagated(self) -> None:
        """case 2.1 — propagated 의 reseed_by 가 있어도 base 가 우선."""
        propagated = {
            "reseed_by": "OLD",
            "reseed_at": "2025-01-01",
            "extra_field": "preserved",
        }
        base = {
            "reseed_by": "NEW",
            "reseed_at": "2026-05-08",
            "is_sop": True,
        }
        merged = _merge_chunk_meta(propagated=propagated, base_chunk_meta=base)
        assert merged["reseed_by"] == "NEW"
        assert merged["reseed_at"] == "2026-05-08"
        assert merged["is_sop"] is True
        assert merged["extra_field"] == "preserved"  # propagated 의 새 키는 보존

    def test_classified_kind_wins_against_propagator(self) -> None:
        """case 2.2 — classified_kind 가 propagated 에 다른 값 있어도 base 우선."""
        propagated = {"classified_kind": "OLD_KIND"}
        base = {"classified_kind": "manual"}
        merged = _merge_chunk_meta(propagated=propagated, base_chunk_meta=base)
        assert merged["classified_kind"] == "manual"

    def test_chunker_strategy_wins(self) -> None:
        """case 2.3 — chunker_strategy 도 base 우선."""
        propagated = {"chunker_strategy": "OLD"}
        base = {"chunker_strategy": "faq_qa"}
        merged = _merge_chunk_meta(propagated=propagated, base_chunk_meta=base)
        assert merged["chunker_strategy"] == "faq_qa"

    def test_propagated_unique_keys_preserved(self) -> None:
        """case 2.4 — propagated 에만 있는 키는 그대로."""
        propagated = {"keywords": ["k1"], "entities": ["e1"]}
        base = {"reseed_by": "v4"}
        merged = _merge_chunk_meta(propagated=propagated, base_chunk_meta=base)
        assert merged["keywords"] == ["k1"]
        assert merged["entities"] == ["e1"]
        assert merged["reseed_by"] == "v4"

    def test_empty_propagated_safe(self) -> None:
        """case 2.5 — propagated={} 안전."""
        base = {"reseed_by": "v4", "is_sop": False}
        merged = _merge_chunk_meta(propagated={}, base_chunk_meta=base)
        assert merged == base

    def test_json_serializable_after_merge(self) -> None:
        """case 2.6 — merge 후 JSON 직렬화 가능 (set 등 비-JSON 타입 없음)."""
        merged = _merge_chunk_meta(
            propagated={"keywords": ["k1"]},
            base_chunk_meta={
                "reseed_by": "v4",
                "is_sop": True,
                "source_block_hashes": ["h1"],
                "source_locations": [{"page": 1}],
            },
        )
        # raises if non-JSON
        s = json.dumps(merged, ensure_ascii=False)
        assert "v4" in s
