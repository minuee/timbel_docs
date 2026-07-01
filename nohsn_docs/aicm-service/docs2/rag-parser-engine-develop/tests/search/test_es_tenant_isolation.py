"""Lucas-KMS Phase 2 T2.6 — ES tenant isolation 단위 test.

검증:

- ``with_tenant_term`` 헬퍼: bool/leaf/None query 처리.
- ``ensure_tenant_id_field``: 누락 / 빈 값 / mismatch 시 ``MissingTenantIdError``.
- ``ESKeywordSearcher.search`` 에 ``tenant_id`` 가 주어지면 ES query 의
  ``bool/filter`` 에 term 이 들어간다 (mock client 로 query 캡쳐).
- ``ESKeywordSearcher.index_blocks`` 에 ``expected_tenant_id`` 미일치 doc
  들어오면 fail-fast.
- ``BLOCK_INDEX_MAPPING`` 에 ``tenant_id`` keyword field 존재.

설계 절칙: 하드코딩 X — tenant_id 는 변수, naming 은 기존 함수 의존.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.search.es_wrapper import (
    MissingTenantIdError,
    ensure_tenant_id_field,
    with_tenant_term,
)
from src.search.hybrid.es_keyword import (
    BLOCK_INDEX_MAPPING,
    ESKeywordSearcher,
    build_block_es_index_name,
)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


class TestBlockIndexMapping:
    def test_tenant_id_field_in_mapping(self) -> None:
        """T2.6 — BLOCK_INDEX_MAPPING 에 tenant_id keyword 필수."""
        assert "tenant_id" in BLOCK_INDEX_MAPPING["properties"]
        assert BLOCK_INDEX_MAPPING["properties"]["tenant_id"] == {"type": "keyword"}

    def test_index_naming_unchanged(self) -> None:
        """기존 build_block_es_index_name pattern 회귀 방지."""
        assert build_block_es_index_name("ricky-personal") == "aicm_ricky-personal_blocks"
        assert build_block_es_index_name("acme") == "aicm_acme_blocks"


# ---------------------------------------------------------------------------
# with_tenant_term
# ---------------------------------------------------------------------------


class TestWithTenantTerm:
    def test_none_tenant_returns_query_as_is(self) -> None:
        q = {"term": {"document_id": "doc-1"}}
        assert with_tenant_term(q, None) == q

    def test_empty_query_with_tenant(self) -> None:
        result = with_tenant_term(None, "tenant-1")
        assert result == {
            "bool": {"filter": [{"term": {"tenant_id": "tenant-1"}}]}
        }

    def test_leaf_query_wrapped_in_bool(self) -> None:
        q = {"term": {"document_id": "doc-1"}}
        result = with_tenant_term(q, "tenant-1")
        assert result == {
            "bool": {
                "must": [{"term": {"document_id": "doc-1"}}],
                "filter": [{"term": {"tenant_id": "tenant-1"}}],
            }
        }

    def test_bool_query_appends_to_filter(self) -> None:
        q = {
            "bool": {
                "must": [{"match": {"content": "hello"}}],
                "filter": [{"term": {"document_id": "doc-1"}}],
            }
        }
        result = with_tenant_term(q, "tenant-1")
        assert result["bool"]["filter"] == [
            {"term": {"document_id": "doc-1"}},
            {"term": {"tenant_id": "tenant-1"}},
        ]
        # must 보존.
        assert result["bool"]["must"] == [{"match": {"content": "hello"}}]

    def test_bool_query_without_filter_creates_one(self) -> None:
        q = {"bool": {"must": [{"match": {"content": "x"}}]}}
        result = with_tenant_term(q, "tenant-1")
        assert result["bool"]["filter"] == [{"term": {"tenant_id": "tenant-1"}}]

    def test_does_not_mutate_input(self) -> None:
        q = {"bool": {"filter": [{"term": {"document_id": "doc-1"}}]}}
        original_filter = list(q["bool"]["filter"])
        _ = with_tenant_term(q, "tenant-1")
        # 원본은 변하지 않음.
        assert q["bool"]["filter"] == original_filter


# ---------------------------------------------------------------------------
# ensure_tenant_id_field
# ---------------------------------------------------------------------------


class TestEnsureTenantIdField:
    def test_missing_field_raises(self) -> None:
        doc = {"block_id": "b1", "document_id": "d1"}
        with pytest.raises(MissingTenantIdError):
            ensure_tenant_id_field(doc, "tenant-1")

    def test_empty_field_raises(self) -> None:
        doc = {"block_id": "b1", "tenant_id": ""}
        with pytest.raises(MissingTenantIdError):
            ensure_tenant_id_field(doc, "tenant-1")

    def test_mismatch_raises(self) -> None:
        doc = {"block_id": "b1", "tenant_id": "tenant-evil"}
        with pytest.raises(MissingTenantIdError):
            ensure_tenant_id_field(doc, "tenant-1")

    def test_match_passes(self) -> None:
        doc = {"block_id": "b1", "tenant_id": "tenant-1"}
        # 예외 없으면 통과.
        ensure_tenant_id_field(doc, "tenant-1")

    def test_empty_expected_raises(self) -> None:
        doc = {"block_id": "b1", "tenant_id": "tenant-1"}
        with pytest.raises(MissingTenantIdError):
            ensure_tenant_id_field(doc, "")


# ---------------------------------------------------------------------------
# ESKeywordSearcher.search — query 에 tenant_id filter 주입 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_injects_tenant_id_filter_into_block_query() -> None:
    """search 호출에 tenant_id 가 주어지면 query/bool/filter 에 tenant_id term 이 들어간다."""
    mock_client = MagicMock()
    mock_client.search = AsyncMock(return_value={"hits": {"hits": []}})

    searcher = ESKeywordSearcher(client=mock_client)

    await searcher.search(
        keywords=["hello"],
        index_name="aicm_ricky-personal_blocks",
        top_k=5,
        caller_tenant_slug="ricky-personal",
        tenant_id="tenant-uuid-abc",
    )

    # mock client.search 호출 인자 캡쳐.
    call_kwargs = mock_client.search.await_args.kwargs
    sent_query = call_kwargs["query"]

    # block index 경로: query["bool"]["filter"] 에 tenant_id term 이 있어야 함.
    assert "bool" in sent_query
    filters = sent_query["bool"].get("filter", [])
    tenant_filter = [f for f in filters if f.get("term", {}).get("tenant_id") == "tenant-uuid-abc"]
    assert len(tenant_filter) == 1, f"tenant_id term 누락 또는 중복: {filters}"


@pytest.mark.asyncio
async def test_search_without_tenant_id_omits_filter() -> None:
    """tenant_id 미명시 시 (legacy 호환) tenant_id term 이 들어가지 않는다."""
    mock_client = MagicMock()
    mock_client.search = AsyncMock(return_value={"hits": {"hits": []}})

    searcher = ESKeywordSearcher(client=mock_client)

    await searcher.search(
        keywords=["hello"],
        index_name="aicm_ricky-personal_blocks",
        top_k=5,
        caller_tenant_slug="ricky-personal",
        tenant_id=None,
    )

    call_kwargs = mock_client.search.await_args.kwargs
    sent_query = call_kwargs["query"]
    filters = sent_query.get("bool", {}).get("filter", [])
    tenant_filter = [f for f in filters if "tenant_id" in f.get("term", {})]
    assert tenant_filter == []


@pytest.mark.asyncio
async def test_search_cross_tenant_namespace_blocked() -> None:
    """caller_tenant_slug 와 index_name 의 slug 가 다르면 차단 (기존 D32 §3 회귀)."""
    from src.search.tenant_isolation import CrossTenantSearchError

    mock_client = MagicMock()
    searcher = ESKeywordSearcher(client=mock_client)

    with pytest.raises(CrossTenantSearchError):
        await searcher.search(
            keywords=["hi"],
            index_name="aicm_evil_blocks",
            caller_tenant_slug="ricky-personal",
            tenant_id="tenant-uuid-abc",
        )


# ---------------------------------------------------------------------------
# ESKeywordSearcher.index_blocks — fail-fast 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_blocks_fail_fast_on_missing_tenant_id() -> None:
    """doc 에 tenant_id 누락 시 ensure_tenant_id_field 가 즉시 raise."""
    mock_client = MagicMock()
    mock_client.indices.exists = AsyncMock(return_value=True)
    mock_client.bulk = AsyncMock(return_value={"errors": False, "items": []})

    searcher = ESKeywordSearcher(client=mock_client)

    bad_docs = [
        {"block_id": "b1", "document_id": "d1", "content": "x"},  # tenant_id 누락
    ]

    with pytest.raises(MissingTenantIdError):
        await searcher.index_blocks(
            "aicm_ricky-personal_blocks",
            bad_docs,
            expected_tenant_id="tenant-uuid-abc",
        )

    # bulk 호출 전에 fail-fast — bulk 가 호출되지 않아야 한다.
    mock_client.bulk.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_blocks_fail_fast_on_mismatch() -> None:
    """doc tenant_id 가 expected 와 다르면 fail-fast."""
    mock_client = MagicMock()
    mock_client.indices.exists = AsyncMock(return_value=True)
    mock_client.bulk = AsyncMock(return_value={"errors": False, "items": []})

    searcher = ESKeywordSearcher(client=mock_client)

    docs = [
        {"block_id": "b1", "tenant_id": "tenant-evil", "content": "x"},
    ]

    with pytest.raises(MissingTenantIdError):
        await searcher.index_blocks(
            "aicm_ricky-personal_blocks",
            docs,
            expected_tenant_id="tenant-uuid-abc",
        )
    mock_client.bulk.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_blocks_passes_when_tenant_id_matches() -> None:
    """모든 doc 의 tenant_id 가 expected 와 일치하면 bulk 호출."""
    mock_client = MagicMock()
    mock_client.indices.exists = AsyncMock(return_value=True)
    mock_client.bulk = AsyncMock(return_value={"errors": False, "items": []})

    searcher = ESKeywordSearcher(client=mock_client)

    docs = [
        {"block_id": "b1", "tenant_id": "tenant-uuid-abc", "content": "x"},
        {"block_id": "b2", "tenant_id": "tenant-uuid-abc", "content": "y"},
    ]
    indexed = await searcher.index_blocks(
        "aicm_ricky-personal_blocks",
        docs,
        expected_tenant_id="tenant-uuid-abc",
    )
    assert indexed == 2
    mock_client.bulk.assert_awaited_once()


# ---------------------------------------------------------------------------
# Cross-tenant 결과 격리 (search level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_a_doc_not_visible_to_tenant_b_via_filter() -> None:
    """tenant B 검색 시 tenant_id=B filter 가 적용되어 tenant A doc 이 제외된다.

    mock client 에서 ES 가 정상적으로 filter 를 평가한다고 가정하고,
    searcher 가 query 에 tenant_id term 을 정확히 넣는지 확인.
    """
    mock_client = MagicMock()
    # ES 가 filter 를 평가했다고 시뮬레이션 — tenant B 만 받음 → 0 hits.
    mock_client.search = AsyncMock(return_value={"hits": {"hits": []}})
    searcher = ESKeywordSearcher(client=mock_client)

    hits, _trace = await searcher.search(
        keywords=["secret"],
        index_name="aicm_tenant-b_blocks",
        caller_tenant_slug="tenant-b",
        tenant_id="tenant-b-uuid",
    )

    # 0 hits — tenant A doc 노출 X.
    assert hits == []
    # query 에 tenant_id term 이 정확히 들어갔는지 검증.
    sent_query = mock_client.search.await_args.kwargs["query"]
    filters = sent_query["bool"]["filter"]
    assert {"term": {"tenant_id": "tenant-b-uuid"}} in filters


# ---------------------------------------------------------------------------
# payload_sync — update_by_query 에 tenant_id term 주입 회귀
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payload_sync_es_update_by_query_includes_tenant_term() -> None:
    """_es_set_document_status_once 가 update_by_query 호출 시 tenant_id term 을 포함."""
    from src.search import payload_sync

    captured: dict = {}

    class _StubResp(dict):
        pass

    class _StubClient:
        async def update_by_query(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _StubResp(updated=1)

        async def close(self) -> None:
            return None

    def _make_client(*_a, **_kw):
        return _StubClient()

    with patch("elasticsearch.AsyncElasticsearch", new=_make_client):
        n = await payload_sync._es_set_document_status_once(
            tenant_slug="ricky-personal",
            document_id="doc-1",
            new_status="active",
            tenant_id="tenant-uuid-abc",
        )

    assert n == 1
    sent_query = captured["query"]
    # bool/filter 구조 안에 tenant_id term 이 있어야 함.
    assert sent_query.get("bool", {}).get("filter") is not None
    filters = sent_query["bool"]["filter"]
    assert {"term": {"tenant_id": "tenant-uuid-abc"}} in filters
