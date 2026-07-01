"""Lucas-KMS Phase 2 T2.5 — Qdrant tenant isolation 이중 안전망 단위 test.

검증 대상:
1. ``QdrantDenseSearcher.search`` 가 ``tenant_id`` 인자 전달 시 ``must`` filter 에
   ``tenant_id`` 조건을 추가한다.
2. ``QdrantSparseSearcher.search`` 도 동일.
3. ``qdrant_wrapper.tenant_aware_upsert`` 가 payload tenant_id 누락 시 raise.
4. ``qdrant_wrapper.build_tenant_must_filter`` 가 tenant_id 미명시 시 raise.
5. ``qdrant_wrapper.assert_payload_has_tenant_id`` 가 누락 payload 차단.
6. cross-tenant 검색 시뮬레이션 — tenant A search call 의 query_filter 에
   tenant A 의 tenant_id 가 must 로 들어가, tenant B 의 chunk (다른 payload
   tenant_id) 는 절대 매치 안 됨 (mock 으로 query_filter 검증).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.search.hybrid.qdrant_dense import QdrantDenseSearcher
from src.search.hybrid.qdrant_sparse import QdrantSparseSearcher
from src.search.qdrant_wrapper import (
    TenantPayloadError,
    assert_payload_has_tenant_id,
    build_tenant_must_filter,
    tenant_aware_upsert,
)


# ---------------------------------------------------------------------------
# qdrant_wrapper helpers
# ---------------------------------------------------------------------------


class TestAssertPayloadHasTenantId:
    def test_present_passes(self) -> None:
        assert_payload_has_tenant_id({"tenant_id": "abc-123", "content": "x"})

    def test_missing_raises(self) -> None:
        with pytest.raises(TenantPayloadError):
            assert_payload_has_tenant_id({"content": "x"})

    def test_empty_raises(self) -> None:
        with pytest.raises(TenantPayloadError):
            assert_payload_has_tenant_id({"tenant_id": "", "content": "x"})


class TestBuildTenantMustFilter:
    def test_tenant_id_included(self) -> None:
        flt = build_tenant_must_filter("tenant-a")
        # must 에 tenant_id 조건이 첫 번째.
        assert flt.must is not None
        first = flt.must[0]
        assert first.key == "tenant_id"
        assert first.match.value == "tenant-a"

    def test_extra_conditions_appended(self) -> None:
        from qdrant_client.http.models import FieldCondition, MatchValue
        extra = FieldCondition(
            key="document_status", match=MatchValue(value="active")
        )
        flt = build_tenant_must_filter("tenant-a", extra_conditions=[extra])
        assert len(flt.must) == 2
        assert flt.must[0].key == "tenant_id"
        assert flt.must[1].key == "document_status"

    def test_missing_tenant_id_raises(self) -> None:
        with pytest.raises(TenantPayloadError):
            build_tenant_must_filter("")


# ---------------------------------------------------------------------------
# tenant_aware_upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTenantAwareUpsert:
    async def test_payload_missing_tenant_id_filled(self) -> None:
        # payload tenant_id 없음 → wrapper 가 자동 보강.
        point = SimpleNamespace(id="p1", payload={"content": "x"})
        client = MagicMock()
        client.upsert = MagicMock()
        n = await tenant_aware_upsert(
            client=client,
            collection_name="aicm_tenant_a_blocks",
            tenant_id="tenant-a",
            points=[point],
        )
        assert n == 1
        assert point.payload["tenant_id"] == "tenant-a"
        client.upsert.assert_called_once()

    async def test_payload_mismatch_raises(self) -> None:
        # payload tenant_id 가 호출자 tenant_id 와 다름 → 즉시 raise.
        point = SimpleNamespace(
            id="p1", payload={"tenant_id": "tenant-b", "content": "x"}
        )
        client = MagicMock()
        client.upsert = MagicMock()
        with pytest.raises(TenantPayloadError):
            await tenant_aware_upsert(
                client=client,
                collection_name="aicm_tenant_a_blocks",
                tenant_id="tenant-a",
                points=[point],
            )
        # upsert 호출 안 됨.
        client.upsert.assert_not_called()

    async def test_caller_tenant_id_missing_raises(self) -> None:
        point = SimpleNamespace(id="p1", payload={"content": "x"})
        client = MagicMock()
        with pytest.raises(TenantPayloadError):
            await tenant_aware_upsert(
                client=client,
                collection_name="aicm_tenant_a_blocks",
                tenant_id="",
                points=[point],
            )


# ---------------------------------------------------------------------------
# Searcher: query_filter must 에 tenant_id 추가
# ---------------------------------------------------------------------------


def _make_response() -> object:
    return SimpleNamespace(points=[])


@pytest.mark.asyncio
class TestDenseSearcherTenantFilter:
    async def test_tenant_id_in_must_filter(self, monkeypatch) -> None:
        mock_client = MagicMock()
        captured = {}

        async def fake_query_points(**kwargs):
            captured.update(kwargs)
            return _make_response()

        mock_client.query_points = fake_query_points
        searcher = QdrantDenseSearcher(client=mock_client)

        await searcher.search(
            query_vector=[0.1] * 8,
            collection_name="aicm_tenant_a_blocks",
            top_k=5,
            caller_tenant_slug="tenant_a",
            tenant_id="tenant-a",
            validity_filter="all",
            document_status_filter="all",
        )

        flt = captured["query_filter"]
        assert flt is not None
        keys = [c.key for c in flt.must]
        assert "tenant_id" in keys
        # tenant_id condition 가 정확히 caller tenant 값을 갖는다.
        ti_cond = next(c for c in flt.must if c.key == "tenant_id")
        assert ti_cond.match.value == "tenant-a"

    async def test_no_tenant_id_legacy_compat(self) -> None:
        # tenant_id 미명시 → must filter 에 tenant_id 조건 없음 (legacy 호환).
        mock_client = MagicMock()
        captured = {}

        async def fake_query_points(**kwargs):
            captured.update(kwargs)
            return _make_response()

        mock_client.query_points = fake_query_points
        searcher = QdrantDenseSearcher(client=mock_client)

        await searcher.search(
            query_vector=[0.1] * 8,
            collection_name="aicm_tenant_a_blocks",
            top_k=5,
            caller_tenant_slug="tenant_a",
            tenant_id=None,
            validity_filter="all",
            document_status_filter="all",
        )

        flt = captured["query_filter"]
        if flt is not None and flt.must:
            keys = [c.key for c in flt.must]
            assert "tenant_id" not in keys


@pytest.mark.asyncio
class TestSparseSearcherTenantFilter:
    async def test_tenant_id_in_must_filter(self) -> None:
        mock_client = MagicMock()
        captured = {}

        async def fake_query_points(**kwargs):
            captured.update(kwargs)
            return _make_response()

        mock_client.query_points = fake_query_points
        searcher = QdrantSparseSearcher(client=mock_client)

        await searcher.search(
            sparse_vector={1: 0.5, 2: 0.3},
            collection_name="aicm_tenant_a_blocks",
            top_k=5,
            caller_tenant_slug="tenant_a",
            tenant_id="tenant-a",
            validity_filter="all",
            document_status_filter="all",
        )

        flt = captured["query_filter"]
        assert flt is not None
        keys = [c.key for c in flt.must]
        assert "tenant_id" in keys
        ti_cond = next(c for c in flt.must if c.key == "tenant_id")
        assert ti_cond.match.value == "tenant-a"


# ---------------------------------------------------------------------------
# Cross-tenant simulation — payload 에 다른 tenant_id 가 있어도 must filter 로 0 hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCrossTenantZeroHit:
    """tenant A 호출 → must filter tenant_id=A. Qdrant 가 tenant_id=A 의 chunk 만
    매치. tenant B 의 chunk (payload tenant_id=B) 는 must filter 로 자동 제외.

    실제 Qdrant 가 없는 환경에서는 mock 으로 query_filter 가 올바르게 빌드되어
    Qdrant 로 전달되는지를 검증한다 (Qdrant 의 filter 의미론은 product 보증).
    """

    async def test_tenant_a_query_filter_excludes_b(self) -> None:
        mock_client = MagicMock()
        captured = {}

        async def fake_query_points(**kwargs):
            captured.update(kwargs)
            return _make_response()

        mock_client.query_points = fake_query_points
        searcher = QdrantDenseSearcher(client=mock_client)

        await searcher.search(
            query_vector=[0.1] * 8,
            collection_name="aicm_tenant_a_blocks",
            top_k=5,
            caller_tenant_slug="tenant_a",
            tenant_id="tenant-a",
            validity_filter="all",
            document_status_filter="all",
        )

        # query_filter must 에 tenant_id=tenant-a 가 있음 → tenant_id=tenant-b
        # payload 는 Qdrant 측에서 매치 안 됨 (must = AND).
        flt = captured["query_filter"]
        ti_cond = next(c for c in flt.must if c.key == "tenant_id")
        assert ti_cond.match.value == "tenant-a"
        assert ti_cond.match.value != "tenant-b"
