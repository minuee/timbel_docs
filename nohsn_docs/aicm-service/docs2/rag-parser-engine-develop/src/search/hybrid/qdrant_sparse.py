"""Qdrant Sparse 벡터 검색 클라이언트."""

from __future__ import annotations

import time
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    NamedSparseVector,
    SparseVector,
)

from src.common.config import settings
from src.common.logging import get_logger
from src.search.models import SearchHit, SearchTraceStep, SourceLocation

log = get_logger(__name__)


class QdrantSparseSearcher:
    """
    BGE-M3 sparse 벡터를 이용한 키워드 매칭 검색.

    - 고유명사, 상품코드, 법조문 번호 등 정확한 용어 매칭에 강함
    - Dense 검색이 놓치는 lexical 매칭 보완
    """

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncQdrantClient:
        """지연 초기화된 Qdrant 클라이언트 반환."""
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                prefer_grpc=False,
                timeout=15,
            )
        return self._client

    async def search(
        self,
        sparse_vector: dict[int, float],
        collection_name: str,
        top_k: int = 20,
        category_ids: list[str] | None = None,
        document_type_ids: list[str] | None = None,
        repository_ids: list[str] | None = None,
        block_types: list[str] | None = None,
        nature_filter: list[str] | None = None,
        validity_filter: str = "active",
        entity_filter: dict | None = None,
        document_status_filter: str = "active",
        # D32 §3 — tenant isolation. caller_slug 미명시 시 legacy 호환 (검증 skip).
        caller_tenant_slug: str | None = None,
        rls_scope: str | None = None,
        allow_cross_namespace: bool = False,
        # Lucas-KMS Phase 2 T2.5 — payload-level tenant_id must filter (이중 안전망).
        tenant_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> tuple[list[SearchHit], SearchTraceStep]:
        """Sparse 벡터 검색 수행."""
        start = time.monotonic()
        # D33 §2 — fail-closed guard (사전 GPT-5 강력 권고).
        if not caller_tenant_slug and settings.RLS_ENFORCE:
            from src.search.tenant_isolation import CrossTenantSearchError
            raise CrossTenantSearchError(
                caller_slug="(missing)",
                target_namespace=collection_name,
                scope=rls_scope,
            )
        # D32 §3 — namespace mismatch 즉시 차단.
        if caller_tenant_slug:
            from src.search.tenant_isolation import assert_tenant_namespace
            assert_tenant_namespace(
                namespace=collection_name,
                caller_slug=caller_tenant_slug,
                scope=rls_scope,
                allow_cross_namespace=allow_cross_namespace,
                backend="qdrant_sparse",
            )
        client = await self._get_client()

        # 필터 구성
        conditions: list[FieldCondition] = []
        # Lucas-KMS Phase 2 T2.5 — payload-level tenant_id must filter (이중 안전망).
        # 미명시 시 legacy chunk 호환 — collection naming 에 의존.
        if tenant_id:
            conditions.append(
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=str(tenant_id)),
                )
            )
        if repository_ids:
            conditions.append(
                FieldCondition(
                    key="repository_id",
                    match=MatchAny(any=repository_ids),
                )
            )
        if document_ids:
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchAny(any=document_ids),
                )
            )
        if category_ids:
            conditions.append(
                FieldCondition(
                    key="category_ids",
                    match=MatchAny(any=category_ids),
                )
            )
        if document_type_ids:
            conditions.append(
                FieldCondition(
                    key="document_type",
                    match=MatchAny(any=document_type_ids),
                )
            )
        if block_types:
            conditions.append(
                FieldCondition(
                    key="block_type",
                    match=MatchAny(any=block_types),
                )
            )

        # Nature 필터 (온톨로지)
        if nature_filter:
            conditions.append(
                FieldCondition(
                    key="nature",
                    match=MatchAny(any=nature_filter),
                )
            )

        # Validity 필터 (기본: active만 반환)
        if validity_filter == "active":
            conditions.append(
                FieldCondition(
                    key="validity_status",
                    match=MatchValue(value="active"),
                )
            )
        elif validity_filter == "historical":
            conditions.append(
                FieldCondition(
                    key="validity_status",
                    match=MatchAny(any=["active", "historical"]),
                )
            )
        # "all" = 필터 없음

        # 문서 상태(active/deactive) 필터 — 기본 active 만, "all" 이면 필터 없음
        if document_status_filter == "active":
            conditions.append(
                FieldCondition(
                    key="document_status",
                    match=MatchValue(value="active"),
                )
            )

        # Entity 필터 (people/orgs/speakers)
        if entity_filter:
            if entity_filter.get("people"):
                conditions.append(
                    FieldCondition(
                        key="entities_people",
                        match=MatchAny(any=entity_filter["people"]),
                    )
                )
            if entity_filter.get("orgs"):
                conditions.append(
                    FieldCondition(
                        key="entities_orgs",
                        match=MatchAny(any=entity_filter["orgs"]),
                    )
                )
            if entity_filter.get("speakers"):
                conditions.append(
                    FieldCondition(
                        key="speakers",
                        match=MatchAny(any=entity_filter["speakers"]),
                    )
                )

        query_filter = Filter(must=conditions) if conditions else None

        # sparse_vector를 indices/values로 분리
        indices = list(sparse_vector.keys())
        values = list(sparse_vector.values())

        try:
            response = await client.query_points(
                collection_name=collection_name,
                query=SparseVector(indices=indices, values=values),
                using="sparse",
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            results = response.points if hasattr(response, "points") else []
        except Exception:
            log.exception("qdrant_sparse_search_failed", collection=collection_name)
            results = []

        hits = [self._to_hit(r) for r in results]
        elapsed_ms = int((time.monotonic() - start) * 1000)

        trace = SearchTraceStep(
            step_name="sparse_search",
            latency_ms=elapsed_ms,
            candidate_count=len(hits),
            details={
                "collection": collection_name,
                "sparse_dim": len(indices),
                "top_scores": [round(h.sparse_score, 4) for h in hits[:5]] if hits else [],
            },
        )

        log.info(
            "sparse_search_completed",
            collection=collection_name,
            candidates=len(hits),
            latency_ms=elapsed_ms,
        )
        return hits, trace

    @staticmethod
    def _to_hit(point: object) -> SearchHit:
        """Qdrant ScoredPoint를 SearchHit으로 변환."""
        payload = point.payload or {}
        source_loc_data = payload.get("source_location", {})

        page_range = source_loc_data.get("page_range")
        if page_range and isinstance(page_range, (list, tuple)) and len(page_range) == 2:
            page_range = list(page_range)
        else:
            page_range = None

        bbox = source_loc_data.get("bbox")
        if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bbox = list(bbox)
        else:
            bbox = None

        point_id = UUID(str(point.id)) if not isinstance(point.id, UUID) else point.id
        repo_id_str = payload.get("repository_id")
        repo_id = UUID(repo_id_str) if repo_id_str else None

        _meta = payload.get("metadata", {})
        _repo_name = payload.get("repository_name", "")
        if _repo_name and isinstance(_meta, dict):
            _meta = {**_meta, "repository_name": _repo_name}

        # KMS-Plus 2026-05-07 — multimodal block 필드 surface.
        # embed_worker 가 qdrant payload 의 *최상위* 에 저장한 table/image 전용
        # 필드를 SearchHit.metadata 로 끌어올려 retrieve / response 단계가
        # 표 markdown / 이미지 caption 을 그대로 답변에 첨부할 수 있게 한다.
        # 사용자 절칙 (2026-05-07): "표나 그림도 보여줘야 답변할 수 있다".
        if isinstance(_meta, dict):
            _multimodal_keys = (
                "table_markdown",
                "table_headers",
                "image_description",
                "image_path",
                "ocr_text",
            )
            for _k in _multimodal_keys:
                _v = payload.get(_k)
                if _v is not None and _k not in _meta:
                    _meta = {**_meta, _k: _v}

        return SearchHit(
            chunk_id=point_id,
            document_id=UUID(payload.get("document_id", "00000000-0000-0000-0000-000000000000")),
            document_title=payload.get("document_title", ""),
            section_title=payload.get("section_title"),
            content=payload.get("content", ""),
            document_type=payload.get("document_type"),
            category_names=payload.get("category_names", []),
            metadata=_meta,
            sparse_score=float(point.score),
            block_id=point_id if payload.get("block_type") else None,
            block_type=payload.get("block_type"),
            block_index=payload.get("block_index"),
            repository_id=repo_id,
            source_location=SourceLocation(
                file_path=source_loc_data.get("file_path", ""),
                file_url=source_loc_data.get("file_url"),
                page_number=source_loc_data.get("page_number"),
                page_range=page_range,
                start_char_offset=source_loc_data.get("start_char_offset"),
                end_char_offset=source_loc_data.get("end_char_offset"),
                bbox=bbox,
                heading_path=source_loc_data.get("heading_path", []),
                sheet_name=source_loc_data.get("sheet_name"),
                table_index=source_loc_data.get("table_index"),
                paragraph_index=source_loc_data.get("paragraph_index"),
            ),
        )
