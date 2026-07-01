"""D31c §7 — Qdrant dry-run snapshot test.

`upsert_qdrant_v4` payload 의 key 집합과 핵심 값 정합성 snapshot.
변경 시 명시적 review 강제. optional client 주입으로 mock 안정성 확보.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.seed.reseed_5_agents_kms_pipeline_v4 import upsert_qdrant_v4


# ────────────────────────────────────────────────────────────────────────
# §7.1 — payload key 집합 snapshot
# ────────────────────────────────────────────────────────────────────────


EXPECTED_PAYLOAD_KEYS = {
    "document_id",
    "repository_id",
    "document_title",
    "repository_name",
    "block_type",
    "block_index",
    "content",
    "token_count",
    "source_location",
    "metadata",
    "category_ids",
    "document_status",
    "is_sop",
    "classified_kind",
    "nature",
    "time_resolved",
    "speakers",
    "entities_people",
    "entities_orgs",
    "validity_status",
    "domain_category_ids",
    "classification_confidence",
    "document_type",
    "chunker_strategy",
    # D31c §3 신규
    "source_locations",
    "contextual_prefix",
    "source_block_hashes",
    "keywords",
    "entities",
}


class _CapturingClient:
    """Qdrant client stub — upsert 호출 인자 캡처."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert(self, *, collection_name: str, points: list) -> None:
        self.calls.append({"collection_name": collection_name, "points": points})


def _build_chunk_with_vectors(metadata_overrides: dict | None = None) -> list[dict]:
    md = {
        "is_sop": True,
        "classified_kind": "manual",
        "industry": "test",
        "document_type": "faq",
        "chunker_strategy": "faq_qa",
        "source_locations": [{"page": 7}, {"page": 8}],
        "contextual_prefix": "Section A",
        "source_block_hashes": ["h1", "h2"],
        "keywords": ["k1", "k2"],
        "entities": ["e1"],
        "nature": "fact",
        "speakers": ["s1"],
        "entities_people": ["p1"],
        "entities_orgs": ["o1"],
        "validity_status": "active",
    }
    if metadata_overrides:
        md.update(metadata_overrides)
    return [
        {
            "id": "cid-1",
            "content": "snapshot test content",
            "document_id": "did",
            "repository_id": "rid",
            "block_type": "paragraph",
            "block_index": 0,
            "token_count": 5,
            "dense": [0.1] * 8,
            "sparse": {0: 0.5, 5: 0.3},
            "metadata": md,
            "document_title": "doc",
            "repository_name": "repo",
        }
    ]


class TestQdrantPayloadSnapshot:
    """§7.1 — payload key 집합 snapshot."""

    @pytest.mark.asyncio
    async def test_payload_keys_match_snapshot(self) -> None:
        """case 7.1.1 — payload key set == EXPECTED_PAYLOAD_KEYS."""
        client = _CapturingClient()
        n = await upsert_qdrant_v4(
            "test-collection",
            _build_chunk_with_vectors(),
            client=client,
        )
        assert n == 1
        assert client.calls
        points = client.calls[0]["points"]
        assert len(points) == 1
        payload = points[0].payload
        actual_keys = set(payload.keys())
        # snapshot 정합 — 변경 시 review 강제
        added = actual_keys - EXPECTED_PAYLOAD_KEYS
        removed = EXPECTED_PAYLOAD_KEYS - actual_keys
        assert not added, f"unexpected new keys: {added}"
        assert not removed, f"missing expected keys: {removed}"

    @pytest.mark.asyncio
    async def test_source_location_first_of_locations(self) -> None:
        """case 7.1.2 — source_location = source_locations[0]."""
        client = _CapturingClient()
        await upsert_qdrant_v4(
            "test", _build_chunk_with_vectors(), client=client
        )
        payload = client.calls[0]["points"][0].payload
        assert payload["source_location"] == {"page": 7}
        assert payload["source_locations"] == [{"page": 7}, {"page": 8}]

    @pytest.mark.asyncio
    async def test_empty_source_locations_safe(self) -> None:
        """case 7.1.3 — source_locations 빈 list 시 source_location = {}."""
        client = _CapturingClient()
        await upsert_qdrant_v4(
            "test",
            _build_chunk_with_vectors({"source_locations": []}),
            client=client,
        )
        payload = client.calls[0]["points"][0].payload
        assert payload["source_location"] == {}
        assert payload["source_locations"] == []

    @pytest.mark.asyncio
    async def test_d31c_new_fields_propagated(self) -> None:
        """case 7.1.4 — D31c 신규 필드 propagate."""
        client = _CapturingClient()
        await upsert_qdrant_v4(
            "test", _build_chunk_with_vectors(), client=client
        )
        payload = client.calls[0]["points"][0].payload
        assert payload["contextual_prefix"] == "Section A"
        assert payload["source_block_hashes"] == ["h1", "h2"]
        assert payload["keywords"] == ["k1", "k2"]
        assert payload["entities"] == ["e1"]

    @pytest.mark.asyncio
    async def test_ontology_propagated(self) -> None:
        """case 7.1.5 — ontology 필드 (nature/speakers/entities_*/validity_status)."""
        client = _CapturingClient()
        await upsert_qdrant_v4(
            "test", _build_chunk_with_vectors(), client=client
        )
        payload = client.calls[0]["points"][0].payload
        assert payload["nature"] == "fact"
        assert payload["speakers"] == ["s1"]
        assert payload["entities_people"] == ["p1"]
        assert payload["entities_orgs"] == ["o1"]
        assert payload["validity_status"] == "active"

    @pytest.mark.asyncio
    async def test_time_resolved_from_time_reference_dict(self) -> None:
        """case 7.1.6 — time_resolved 가 time_reference.resolved 우선 추출."""
        client = _CapturingClient()
        await upsert_qdrant_v4(
            "test",
            _build_chunk_with_vectors(
                {"time_reference": {"resolved": "2026-05-08"}}
            ),
            client=client,
        )
        payload = client.calls[0]["points"][0].payload
        assert payload["time_resolved"] == "2026-05-08"

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_zero(self) -> None:
        """case 7.1.7 — 빈 chunks 입력 시 0 반환 (qdrant 호출 X)."""
        client = _CapturingClient()
        n = await upsert_qdrant_v4("test", [], client=client)
        assert n == 0
        assert not client.calls

    @pytest.mark.asyncio
    async def test_no_dense_skipped(self) -> None:
        """case 7.1.8 — dense 없는 chunk 는 skip."""
        client = _CapturingClient()
        chunks = _build_chunk_with_vectors()
        chunks[0]["dense"] = None
        n = await upsert_qdrant_v4("test", chunks, client=client)
        assert n == 0  # points 비어서 upsert 호출 X
