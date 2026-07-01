"""D33 §2 — SearchService 가 4 search 호출 site 모두에 caller_tenant_slug /
rls_scope / allow_cross_namespace 를 정확히 propagate 하는지 단위 검증.

사전 GPT-5 §2 강력 권고 — 누락 site 0 보장. 운영 경로 (RLS_ENFORCE=true) 에서
caller_slug 누락은 즉시 fail-closed (CrossTenantSearchError) — 그 동작도 검증.

Mocking 전략:
- SearchService 의 4 searcher 인스턴스를 ArgCapturingSearcher 로 교체.
- 임베딩 / 전처리 / decomposer / fusion / reranker / context_builder 등 헤비
  의존성은 stub 으로 주입.
- 실제 pipeline 실행이 필요하지 않은 부분은 mock 으로 차단 — 4 search 호출
  site 의 인자 capture 만 검증.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.search.models import (
    SearchHit,
    SearchRequest,
    SearchTraceStep,
)
from src.search.service import SearchService
from src.search.tenant_isolation import CrossTenantSearchError


@dataclass
class _CapturedCall:
    backend: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class _ArgCapturingSearcher:
    """search() 호출 시 kwargs 캡처 + 빈 결과 반환."""

    def __init__(self, backend: str, captured: list[_CapturedCall]) -> None:
        self._backend = backend
        self._captured = captured

    async def search(self, **kwargs: Any) -> tuple[list[SearchHit], SearchTraceStep]:
        self._captured.append(_CapturedCall(backend=self._backend, kwargs=dict(kwargs)))
        # 빈 결과 + 더미 trace.
        return [], SearchTraceStep(
            step_name=self._backend,
            latency_ms=0,
            candidate_count=0,
            details={},
        )


class _StubPreprocessor:
    """QueryPreprocessor stub — for_dense / for_keyword 만 채워서 반환."""

    async def preprocess(
        self, query: str, *, tenant_id: Any = None
    ) -> tuple[Any, SearchTraceStep]:
        processed = MagicMock()
        processed.for_dense = query
        processed.for_keyword = [query]
        processed.dense_query = query
        processed.original_query = query
        return processed, SearchTraceStep(
            step_name="preprocess",
            latency_ms=0,
            candidate_count=0,
            details={},
        )


@pytest.fixture
def service() -> tuple[SearchService, list[_CapturedCall]]:
    """SearchService + capture buffer."""
    captured: list[_CapturedCall] = []

    svc = SearchService(
        preprocessor=_StubPreprocessor(),
        dense_searcher=_ArgCapturingSearcher("dense", captured),  # type: ignore[arg-type]
        sparse_searcher=_ArgCapturingSearcher("sparse", captured),  # type: ignore[arg-type]
        keyword_searcher=_ArgCapturingSearcher("keyword", captured),  # type: ignore[arg-type]
        fusion=MagicMock(fuse=MagicMock(return_value=([], SearchTraceStep(
            step_name="fusion", latency_ms=0, candidate_count=0, details={},
        )))),
        reranker=MagicMock(rerank=AsyncMock(return_value=([], SearchTraceStep(
            step_name="rerank", latency_ms=0, candidate_count=0, details={},
        )))),
        embedding_fn=AsyncMock(return_value=([0.1, 0.2, 0.3], {1: 0.5})),
    )
    return svc, captured


@pytest.mark.asyncio
async def test_propagation_to_all_4_sites(
    service: tuple[SearchService, list[_CapturedCall]],
) -> None:
    """hybrid mode (dense + sparse + keyword) 호출 → 3+ 호출 site 모두 caller_slug propagate."""
    svc, captured = service

    request = SearchRequest(
        query="환불 정책",
        tenant_id=UUID("67d157c3-5084-49f9-bc15-92ad1bcd8ac7"),
        search_mode="hybrid",
        use_hyde=False,
    )

    await svc._execute_pipeline(
        request=request,
        tenant_slug="locus",
        tenant_config=None,
        repo_config=None,
    )

    assert len(captured) >= 3, f"expected >=3 captured calls, got {len(captured)}"

    backends = [c.backend for c in captured]
    assert "dense" in backends, f"dense site not called — got {backends}"
    assert "sparse" in backends, f"sparse site not called — got {backends}"
    assert "keyword" in backends, f"keyword site not called — got {backends}"

    # 모든 호출 site 가 caller_tenant_slug 전달 (D33 §2).
    for call in captured:
        assert call.kwargs.get("caller_tenant_slug") == "locus", (
            f"{call.backend}: caller_tenant_slug != 'locus' "
            f"(got {call.kwargs.get('caller_tenant_slug')!r})"
        )
        # rls_scope 는 contextvar 가 set 안 된 환경 → 빈 문자열 (사전 GPT-5 §2 patch).
        assert call.kwargs.get("rls_scope") == "", (
            f"{call.backend}: rls_scope expected '' got {call.kwargs.get('rls_scope')!r}"
        )
        assert call.kwargs.get("allow_cross_namespace") is False, (
            f"{call.backend}: allow_cross_namespace must be False"
        )


@pytest.mark.asyncio
async def test_propagation_includes_hyde_dense_path() -> None:
    """use_hyde=True 시 hyde_dense (4 번째) 호출 site 도 caller_slug propagate.

    사후 GPT-5 §2 GO_WITH_CHANGES 보완 — hyde 경로를 테스트로 보장하지 못하면
    4 site 누락 0 를 검증 못 함.
    """
    captured: list[_CapturedCall] = []

    # query_expander stub — non-empty hyde_document → hyde_dense 경로 활성.
    class _StubExpander:
        async def expand(self, query: str) -> Any:
            from src.search.query_expander import ExpandedQuery
            return ExpandedQuery(
                original=query,
                hyde_document="가상 답변 본문 — hyde stub",
                expanded_keywords=["hyde"],
            )

    svc = SearchService(
        preprocessor=_StubPreprocessor(),
        dense_searcher=_ArgCapturingSearcher("dense", captured),  # type: ignore[arg-type]
        sparse_searcher=_ArgCapturingSearcher("sparse", captured),  # type: ignore[arg-type]
        keyword_searcher=_ArgCapturingSearcher("keyword", captured),  # type: ignore[arg-type]
        fusion=MagicMock(fuse=MagicMock(return_value=([], SearchTraceStep(
            step_name="fusion", latency_ms=0, candidate_count=0, details={},
        )))),
        reranker=MagicMock(rerank=AsyncMock(return_value=([], SearchTraceStep(
            step_name="rerank", latency_ms=0, candidate_count=0, details={},
        )))),
        embedding_fn=AsyncMock(return_value=([0.1, 0.2, 0.3], {1: 0.5})),
        query_expander=_StubExpander(),
    )

    request = SearchRequest(
        query="환불 정책",
        tenant_id=UUID("67d157c3-5084-49f9-bc15-92ad1bcd8ac7"),
        search_mode="hybrid",
        use_hyde=True,
    )

    await svc._execute_pipeline(
        request=request,
        tenant_slug="locus",
        tenant_config=None,
        repo_config=None,
    )

    # 4 호출 site == dense + hyde_dense + sparse + keyword (모두 _dense_searcher /
    # _sparse_searcher / _keyword_searcher 의 capturing wrapper). _dense_searcher
    # 는 두 번 호출됨 (정상 dense + hyde_dense).
    dense_calls = [c for c in captured if c.backend == "dense"]
    sparse_calls = [c for c in captured if c.backend == "sparse"]
    keyword_calls = [c for c in captured if c.backend == "keyword"]

    assert len(dense_calls) == 2, (
        f"expected 2 dense calls (정상 + hyde), got {len(dense_calls)}"
    )
    assert len(sparse_calls) == 1, f"expected 1 sparse call, got {len(sparse_calls)}"
    assert len(keyword_calls) == 1, f"expected 1 keyword call, got {len(keyword_calls)}"

    # 4 호출 모두 caller_tenant_slug propagate 검증.
    for call in captured:
        assert call.kwargs.get("caller_tenant_slug") == "locus", (
            f"{call.backend}: caller_tenant_slug missing"
        )
        assert call.kwargs.get("rls_scope") == "", (
            f"{call.backend}: rls_scope wrong"
        )
        assert call.kwargs.get("allow_cross_namespace") is False, (
            f"{call.backend}: allow_cross_namespace wrong"
        )


@pytest.mark.asyncio
async def test_dense_search_fail_closed_when_rls_enforce_and_no_caller_slug() -> None:
    """qdrant_dense.search() 가 RLS_ENFORCE=true + caller_slug 누락 시 즉시 raise."""
    from src.search.hybrid.qdrant_dense import QdrantDenseSearcher

    searcher = QdrantDenseSearcher()

    with patch("src.search.hybrid.qdrant_dense.settings") as _s:
        _s.RLS_ENFORCE = True
        _s.QDRANT_URL = "http://qdrant:6333"
        _s.QDRANT_API_KEY = ""
        with pytest.raises(CrossTenantSearchError):
            await searcher.search(
                query_vector=[0.1, 0.2, 0.3],
                collection_name="aicm_locus_blocks",
                # caller_tenant_slug 누락 — fail-closed.
            )


@pytest.mark.asyncio
async def test_sparse_search_fail_closed_when_rls_enforce_and_no_caller_slug() -> None:
    """qdrant_sparse.search() 동일한 fail-closed."""
    from src.search.hybrid.qdrant_sparse import QdrantSparseSearcher

    searcher = QdrantSparseSearcher()

    with patch("src.search.hybrid.qdrant_sparse.settings") as _s:
        _s.RLS_ENFORCE = True
        _s.QDRANT_URL = "http://qdrant:6333"
        _s.QDRANT_API_KEY = ""
        with pytest.raises(CrossTenantSearchError):
            await searcher.search(
                sparse_vector={1: 0.5},
                collection_name="aicm_locus_blocks",
            )


@pytest.mark.asyncio
async def test_es_search_fail_closed_when_rls_enforce_and_no_caller_slug() -> None:
    """es_keyword.search() 동일한 fail-closed."""
    from src.search.hybrid.es_keyword import ESKeywordSearcher

    searcher = ESKeywordSearcher()

    with patch("src.search.hybrid.es_keyword.settings") as _s:
        _s.RLS_ENFORCE = True
        _s.ELASTICSEARCH_URL = "http://elasticsearch:9200"
        with pytest.raises(CrossTenantSearchError):
            await searcher.search(
                keywords=["환불"],
                index_name="aicm_locus_blocks",
            )


@pytest.mark.asyncio
async def test_dev_mode_legacy_skip() -> None:
    """RLS_ENFORCE=false (dev) 에서는 caller_slug 누락도 silent skip — legacy 호환."""
    from src.search.hybrid.qdrant_dense import QdrantDenseSearcher

    searcher = QdrantDenseSearcher()

    # 실제 client 호출은 mock — settings.RLS_ENFORCE=False 면 fail-closed 우회.
    with patch("src.search.hybrid.qdrant_dense.settings") as _s:
        _s.RLS_ENFORCE = False
        _s.QDRANT_URL = "http://qdrant:6333"
        _s.QDRANT_API_KEY = ""
        # client._get_client 호출은 fail (qdrant 부재) 하지만 그 *전* 의 fail-closed
        # 가드는 통과해야 함. 통과 후 client 호출 단계에서 다른 예외가 나는 건 OK
        # (본 test 는 fail-closed 경로 검증만).
        try:
            await searcher.search(
                query_vector=[0.1, 0.2, 0.3],
                collection_name="aicm_locus_blocks",
            )
        except CrossTenantSearchError:
            pytest.fail("RLS_ENFORCE=false 인데 fail-closed 가 발동")
        except Exception:
            # qdrant client 가 없어서 다른 예외 → 무시 (fail-closed 이외 단계).
            pass
