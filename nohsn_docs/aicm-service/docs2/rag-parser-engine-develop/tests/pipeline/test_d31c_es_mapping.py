"""D31c §5 — ES mapping fixture test.

`BLOCK_INDEX_MAPPING` 과 `es_index()` INSERT 시 사용 필드의 정합성 검증.
mapping 에 정의되지 않은 키가 INSERT 되면 ES dynamic mapping 으로 부정확한 타입
생성 위험 — 본 test 가 차단.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.search.hybrid.es_keyword import BLOCK_INDEX_MAPPING


# ────────────────────────────────────────────────────────────────────────
# §5.1 — mapping 정합 (mapping ⊇ doc keys 또는 metadata enabled:false 처리)
# ────────────────────────────────────────────────────────────────────────


class TestESMappingFieldCoverage:
    """§5.1 — ES doc keys ⊆ mapping properties (또는 metadata 안)."""

    def _build_es_doc(self) -> dict:
        """es_index 로직과 동일한 doc 구조 — D31c §4 풀세트."""
        md = {
            "keywords": ["k1", "k2"],
            "entities": ["e1"],
            "source_locations": [{"page": 1}],
            "nature": "fact",
            "validity_status": "active",
            "entities_people": ["p1"],
            "entities_orgs": ["o1"],
            "speakers": ["s1"],
        }
        return {
            "block_id": "bid",
            "document_id": "did",
            "repository_id": "rid",
            "document_title": "title",
            "repository_name": "repo",
            "block_type": "paragraph",
            "content": "hello",
            "block_index": 0,
            "document_status": "active",
            "keywords": md["keywords"],
            "entities": md["entities"],
            "source_location": md["source_locations"][0],
            "metadata": md,
            "category_ids": [],
            "nature": md["nature"],
            "validity_status": md["validity_status"],
            "entities_people": md["entities_people"],
            "entities_orgs": md["entities_orgs"],
            "speakers": md["speakers"],
        }

    def test_all_doc_keys_in_mapping(self) -> None:
        """case 5.1.1 — D31c es_index doc 의 모든 key 가 mapping 에 정의됨."""
        doc = self._build_es_doc()
        mapping_keys = set(BLOCK_INDEX_MAPPING["properties"].keys())
        doc_keys = set(doc.keys())
        missing = doc_keys - mapping_keys
        assert not missing, f"ES mapping missing keys: {missing}"

    def test_block_id_keyword_type(self) -> None:
        """case 5.1.2 — block_id mapping = keyword."""
        assert BLOCK_INDEX_MAPPING["properties"]["block_id"]["type"] == "keyword"

    def test_document_id_keyword_type(self) -> None:
        """case 5.1.3 — document_id mapping = keyword."""
        assert BLOCK_INDEX_MAPPING["properties"]["document_id"]["type"] == "keyword"

    def test_repository_id_keyword_type(self) -> None:
        """case 5.1.4 — repository_id mapping = keyword."""
        assert BLOCK_INDEX_MAPPING["properties"]["repository_id"]["type"] == "keyword"

    def test_content_text_korean_analyzer(self) -> None:
        """case 5.1.5 — content mapping = text + analyzer korean."""
        content_map = BLOCK_INDEX_MAPPING["properties"]["content"]
        assert content_map["type"] == "text"
        assert content_map["analyzer"] == "korean"

    def test_metadata_enabled_false(self) -> None:
        """case 5.1.6 — metadata mapping enabled:false (dynamic shape 허용)."""
        md_map = BLOCK_INDEX_MAPPING["properties"]["metadata"]
        assert md_map.get("enabled") is False

    def test_keywords_keyword_type(self) -> None:
        """case 5.1.7 — D31c §4 keywords mapping = keyword."""
        assert BLOCK_INDEX_MAPPING["properties"]["keywords"]["type"] == "keyword"

    def test_entities_keyword_type(self) -> None:
        """case 5.1.8 — D31c §4 entities mapping = keyword."""
        assert BLOCK_INDEX_MAPPING["properties"]["entities"]["type"] == "keyword"

    def test_source_location_object(self) -> None:
        """case 5.1.9 — source_location object enabled."""
        sl = BLOCK_INDEX_MAPPING["properties"]["source_location"]
        assert sl["type"] == "object"
        assert sl.get("enabled") is True

    def test_ontology_fields_keyword_type(self) -> None:
        """case 5.1.10 — D31c §4 nature/validity_status/entities_people/orgs/speakers."""
        for field in ["nature", "validity_status", "entities_people", "entities_orgs", "speakers"]:
            assert BLOCK_INDEX_MAPPING["properties"][field]["type"] == "keyword", (
                f"{field} not keyword"
            )


# ────────────────────────────────────────────────────────────────────────
# §5.2 — es_index() 호출 시 doc 캡처 + mapping 정합 e2e 검증
# ────────────────────────────────────────────────────────────────────────


class TestESIndexDocCapture:
    """§5.2 — es_index() 호출 → mock 으로 doc 캡처 → mapping 정합 검증."""

    @pytest.mark.asyncio
    async def test_es_index_calls_index_blocks_with_full_doc(self) -> None:
        """case 5.2.1 — es_index() 가 BLOCK_INDEX_MAPPING 정합 doc 으로 호출."""
        from scripts.seed.reseed_5_agents_kms_pipeline import es_index

        captured_docs: list[dict] = []

        async def fake_index_blocks(self, idx_name, docs):
            captured_docs.extend(docs)
            return len(docs)

        async def fake_ensure_block_index(self, idx_name):
            return None

        with patch(
            "src.search.hybrid.es_keyword.ESKeywordSearcher.index_blocks",
            new=fake_index_blocks,
        ), patch(
            "src.search.hybrid.es_keyword.ESKeywordSearcher.ensure_block_index",
            new=fake_ensure_block_index,
        ):
            chunks_with_vectors = [
                {
                    "id": "cid-1",
                    "content": "hello",
                    "document_id": "did",
                    "repository_id": "rid",
                    "block_type": "paragraph",
                    "block_index": 0,
                    "document_title": "title",
                    "repository_name": "repo",
                    "metadata": {
                        "keywords": ["k1"],
                        "entities": ["e1"],
                        "source_locations": [{"page": 2}],
                        "nature": "fact",
                        "validity_status": "active",
                        "entities_people": ["p"],
                        "entities_orgs": ["o"],
                        "speakers": ["s"],
                    },
                }
            ]
            n = await es_index("ricky", chunks_with_vectors)

        assert n == 1
        assert captured_docs

        doc = captured_docs[0]
        mapping_keys = set(BLOCK_INDEX_MAPPING["properties"].keys())
        doc_keys = set(doc.keys())
        missing = doc_keys - mapping_keys
        assert not missing, f"es_index doc has keys not in mapping: {missing}"

        # D31c §4 — keywords/entities propagate
        assert doc["keywords"] == ["k1"]
        assert doc["entities"] == ["e1"]
        assert doc["source_location"] == {"page": 2}
        assert doc["nature"] == "fact"
        assert doc["validity_status"] == "active"
        assert doc["entities_people"] == ["p"]
        assert doc["entities_orgs"] == ["o"]
        assert doc["speakers"] == ["s"]

    @pytest.mark.asyncio
    async def test_es_index_empty_metadata_safe(self) -> None:
        """case 5.2.2 — metadata 가 비어도 안전 (default 채움)."""
        from scripts.seed.reseed_5_agents_kms_pipeline import es_index

        captured_docs: list[dict] = []

        async def fake_index_blocks(self, idx_name, docs):
            captured_docs.extend(docs)
            return len(docs)

        async def fake_ensure_block_index(self, idx_name):
            return None

        with patch(
            "src.search.hybrid.es_keyword.ESKeywordSearcher.index_blocks",
            new=fake_index_blocks,
        ), patch(
            "src.search.hybrid.es_keyword.ESKeywordSearcher.ensure_block_index",
            new=fake_ensure_block_index,
        ):
            await es_index(
                "ricky",
                [
                    {
                        "id": "cid",
                        "content": "x",
                        "document_id": "did",
                        "repository_id": "rid",
                        "block_type": "paragraph",
                        "block_index": 0,
                        "metadata": {},
                    }
                ],
            )

        doc = captured_docs[0]
        assert doc["keywords"] == []
        assert doc["entities"] == []
        assert doc["source_location"] == {}
        assert doc["nature"] == ""
        assert doc["validity_status"] == "active"

    @pytest.mark.asyncio
    async def test_es_index_skip_empty_content(self) -> None:
        """case 5.2.3 — content 비면 skip."""
        from scripts.seed.reseed_5_agents_kms_pipeline import es_index

        captured_docs: list[dict] = []

        async def fake_index_blocks(self, idx_name, docs):
            captured_docs.extend(docs)
            return len(docs)

        async def fake_ensure_block_index(self, idx_name):
            return None

        with patch(
            "src.search.hybrid.es_keyword.ESKeywordSearcher.index_blocks",
            new=fake_index_blocks,
        ), patch(
            "src.search.hybrid.es_keyword.ESKeywordSearcher.ensure_block_index",
            new=fake_ensure_block_index,
        ):
            await es_index(
                "ricky",
                [{"id": "x", "content": "", "metadata": {}}],
            )

        assert not captured_docs
