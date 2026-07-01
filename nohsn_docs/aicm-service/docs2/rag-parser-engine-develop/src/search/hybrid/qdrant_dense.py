"""Qdrant Dense 벡터 검색 클라이언트."""

from __future__ import annotations

import time
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    NamedVector,
    SearchParams,
)

from src.common.config import settings
from src.common.constants import QDRANT_COLLECTION_PREFIX
from src.common.logging import get_logger
from src.search.models import SearchHit, SearchTraceStep, SourceLocation

log = get_logger(__name__)


def build_collection_name(tenant_slug: str, repository_id: UUID | None = None) -> str:
    """Qdrant 컬렉션 이름 생성.

    블럭 파이프라인 (현재 표준): 항상 aicm_{tenant_slug}_blocks 단일 컬렉션 사용.
    repository_id 는 payload filter 로 격리한다 (컬렉션을 나누지 않음).
    """
    return build_tenant_collection_name(tenant_slug)


def build_tenant_collection_name(tenant_slug: str) -> str:
    """테넌트 단일 Qdrant 컬렉션 이름 생성. 형식: aicm_{tenant_slug}_blocks."""
    return f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"


class QdrantDenseSearcher:
    """
    BGE-M3 dense 벡터를 이용한 의미 기반 검색.

    - 질의 임베딩 -> Qdrant cosine similarity 검색
    - 저장소 격리: collection_name으로 물리 격리
    - 카테고리/문서타입 필터: Qdrant payload filter
    """

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncQdrantClient:
        """지연 초기화된 Qdrant 클라이언트 반환."""
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                prefer_grpc=False,  # gRPC 버전 불일치 이슈로 HTTP 사용
                timeout=15,
            )
        return self._client

    def _build_conditions(
        self,
        *,
        tenant_id: str | None,
        repository_ids: list[str] | None,
        category_ids: list[str] | None,
        document_type_ids: list[str] | None,
        block_types: list[str] | None,
        nature_filter: list[str] | None,
        validity_filter: str,
        entity_filter: dict | None,
        document_status_filter: str,
        time_filter: str = "",
        document_type_hint: str = "",
        document_ids: list[str] | None = None,
    ) -> tuple[list[FieldCondition], bool]:
        """payload 필터 조건 목록 빌드. (exclude_search_excluded 플래그도 반환)"""
        conditions: list[FieldCondition] = []
        # Lucas-KMS Phase 2 T2.5 — payload-level tenant_id must filter (이중 안전망).
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
        exclude_search_excluded = False
        if document_status_filter == "active":
            conditions.append(
                FieldCondition(
                    key="document_status",
                    match=MatchValue(value="active"),
                )
            )
            exclude_search_excluded = True

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

        # 시간 범위 필터 (created_at payload 기준)
        if time_filter:
            try:
                from datetime import datetime, timedelta

                from qdrant_client.http.models import Range

                now = datetime.utcnow()
                cutoff: datetime | None = None
                if time_filter == "recent":
                    cutoff = now - timedelta(days=7)
                elif time_filter == "last_month":
                    cutoff = now - timedelta(days=30)
                elif time_filter.isdigit() and len(time_filter) == 4:
                    cutoff = datetime(int(time_filter), 1, 1)

                if cutoff:
                    conditions.append(
                        FieldCondition(
                            key="created_at",
                            range=Range(gte=cutoff.isoformat()),
                        )
                    )
                    log.debug(
                        "time_filter_applied",
                        time_filter=time_filter,
                        cutoff=cutoff.isoformat(),
                    )
            except Exception:
                log.debug("time_filter_parse_failed", time_filter=time_filter, exc_info=True)

        # 문서 유형 힌트 필터 (metadata.document_type 기준)
        if document_type_hint:
            try:
                conditions.append(
                    FieldCondition(
                        key="metadata.document_type",
                        match=MatchValue(value=document_type_hint),
                    )
                )
                log.debug("document_type_hint_applied", hint=document_type_hint)
            except Exception:
                log.debug(
                    "document_type_hint_filter_failed",
                    hint=document_type_hint,
                    exc_info=True,
                )

        return conditions, exclude_search_excluded

    async def search(
        self,
        query_vector: list[float],
        collection_name: str,
        top_k: int = 20,
        category_ids: list[str] | None = None,
        document_type_ids: list[str] | None = None,
        score_threshold: float = 0.3,
        repository_ids: list[str] | None = None,
        block_types: list[str] | None = None,
        time_filter: str = "",
        document_type_hint: str = "",
        nature_filter: list[str] | None = None,
        validity_filter: str = "active",
        entity_filter: dict | None = None,
        document_status_filter: str = "active",
        # D32 §3 — tenant isolation instrumentation. caller_slug 가 명시되면
        # collection_name 의 namespace 와 일치하는지 검증. 미명시 시 legacy 호환
        # (검증 skip — 기존 호출자 무영향).
        caller_tenant_slug: str | None = None,
        rls_scope: str | None = None,
        allow_cross_namespace: bool = False,
        # Lucas-KMS Phase 2 T2.5 — payload-level tenant isolation 이중 안전망.
        # collection naming 만으로 부족 — payload tenant_id 까지 must filter 강제.
        tenant_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> tuple[list[SearchHit], SearchTraceStep]:
        """Dense 벡터 검색 수행.

        Args:
            query_vector: 질의 dense 임베딩 벡터
            collection_name: Qdrant 컬렉션명
            top_k: 반환할 최대 결과 수
            category_ids: 카테고리 ID 필터
            document_type_ids: 문서 타입 ID 필터
            score_threshold: 최소 유사도 임계값
            repository_ids: 저장소 ID 필터
            block_types: 블럭 타입 필터 (paragraph, table 등)
            time_filter: 시간 범위 필터 ("recent", "last_month", "2024" 등)
            document_type_hint: 문서 유형 힌트 ("매뉴얼", "단가표" 등)
            nature_filter: 온톨로지 nature 필터 (["fact", "schedule"] 등)
            validity_filter: 유효성 필터 ("active", "all", "historical")
            entity_filter: 엔티티 필터 ({"people": [...], "orgs": [...], "speakers": [...]})
        """
        start = time.monotonic()
        # D33 §2 — fail-closed guard (사전 GPT-5 강력 권고). 운영 환경
        # (RLS_ENFORCE=true) 에서 caller_tenant_slug 누락은 cross-tenant 누수
        # 위험 — 즉시 CrossTenantSearchError. dev (RLS_ENFORCE=false) 는 legacy
        # 호환 위해 silent skip.
        if not caller_tenant_slug and settings.RLS_ENFORCE:
            from src.search.tenant_isolation import CrossTenantSearchError
            raise CrossTenantSearchError(
                caller_slug="(missing)",
                target_namespace=collection_name,
                scope=rls_scope,
            )
        # D32 §3 — namespace mismatch 즉시 차단 (silent drop 0).
        if caller_tenant_slug:
            from src.search.tenant_isolation import assert_tenant_namespace
            assert_tenant_namespace(
                namespace=collection_name,
                caller_slug=caller_tenant_slug,
                scope=rls_scope,
                allow_cross_namespace=allow_cross_namespace,
                backend="qdrant_dense",
            )
        client = await self._get_client()

        # 필터 구성
        conditions, exclude_search_excluded = self._build_conditions(
            tenant_id=tenant_id,
            repository_ids=repository_ids,
            category_ids=category_ids,
            document_type_ids=document_type_ids,
            block_types=block_types,
            nature_filter=nature_filter,
            validity_filter=validity_filter,
            entity_filter=entity_filter,
            document_status_filter=document_status_filter,
            time_filter=time_filter,
            document_type_hint=document_type_hint,
            document_ids=document_ids,
        )

        must_not: list[FieldCondition] = []
        if exclude_search_excluded:
            must_not.append(
                FieldCondition(
                    key="search_excluded",
                    match=MatchValue(value=True),
                )
            )
        query_filter = (
            Filter(must=conditions or None, must_not=must_not or None)
            if (conditions or must_not)
            else None
        )

        try:
            from qdrant_client.models import QueryResponse

            response = await client.query_points(
                collection_name=collection_name,
                query=query_vector,
                using="dense",
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                score_threshold=score_threshold,
                search_params=SearchParams(hnsw_ef=128, exact=False),
            )
            results = response.points if hasattr(response, "points") else []
        except Exception:
            log.exception("qdrant_dense_search_failed", collection=collection_name)
            results = []

        hits = [self._to_hit(r) for r in results]
        elapsed_ms = int((time.monotonic() - start) * 1000)

        trace = SearchTraceStep(
            step_name="dense_search",
            latency_ms=elapsed_ms,
            candidate_count=len(hits),
            details={
                "collection": collection_name,
                "score_threshold": score_threshold,
                "top_scores": [round(h.dense_score, 4) for h in hits[:5]] if hits else [],
            },
        )

        log.info(
            "dense_search_completed",
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

        # page_range와 bbox는 tuple 변환
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

        # metadata에 repository_name 주입 (프론트에서 metadata.repository_name으로 읽음)
        _meta = payload.get("metadata", {})
        _repo_name = payload.get("repository_name", "")
        if _repo_name and isinstance(_meta, dict):
            _meta = {**_meta, "repository_name": _repo_name}

        # KMS-Plus 2026-05-07 — multimodal block 필드 surface (qdrant_sparse._to_hit
        # 와 대칭). embed_worker 가 payload 최상위에 저장한 table/image 전용 필드를
        # SearchHit.metadata 로 끌어올린다. retrieve / response 단계가 본 필드로
        # ImageBlock / TableBlock 응답을 빌드.
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
            dense_score=float(point.score),
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
