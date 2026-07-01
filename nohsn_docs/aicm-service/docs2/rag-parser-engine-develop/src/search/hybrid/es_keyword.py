"""Elasticsearch 키워드 검색 클라이언트."""

from __future__ import annotations

import time
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from src.common.config import settings
from src.common.constants import QDRANT_COLLECTION_PREFIX
from src.common.logging import get_logger
from src.search.models import SearchHit, SearchTraceStep, SourceLocation

log = get_logger(__name__)

# nori 한국어 분석기 인덱스 설정
INDEX_SETTINGS: dict = {
    "analysis": {
        "analyzer": {
            "korean": {
                "type": "custom",
                "tokenizer": "nori_tokenizer",
                "filter": ["nori_readingform", "lowercase"],
            }
        }
    }
}

INDEX_MAPPING: dict = {
    "properties": {
        "content": {"type": "text", "analyzer": "korean"},
        "document_title": {"type": "text", "analyzer": "korean"},
        "section_title": {"type": "text", "analyzer": "korean"},
        "category_ids": {"type": "keyword"},
        "document_type": {"type": "keyword"},
        "document_id": {"type": "keyword"},
        "chunk_id": {"type": "keyword"},
        "source_location": {"type": "object", "enabled": True},
        "block_type": {"type": "keyword"},
        "category_names": {"type": "keyword"},
        "metadata": {"type": "object", "enabled": False},
    }
}

BLOCK_INDEX_MAPPING: dict = {
    "properties": {
        # Lucas-KMS Phase 2 T2.6 — payload-level tenant isolation 이중 안전망.
        # index naming (aicm_{tenant_slug}_blocks) 만으로 부족 — search/update/delete
        # 에서 must filter tenant_id 와 짝. T2.5 (Qdrant) 의 payload tenant_id 와 동일.
        "tenant_id": {"type": "keyword"},
        "block_id": {"type": "keyword"},
        "document_id": {"type": "keyword"},
        "repository_id": {"type": "keyword"},
        "document_title": {"type": "text", "analyzer": "korean", "fields": {"keyword": {"type": "keyword"}}},
        "repository_name": {"type": "keyword"},
        "block_type": {"type": "keyword"},
        "content": {"type": "text", "analyzer": "korean"},
        "block_index": {"type": "integer"},
        "keywords": {"type": "keyword"},
        "entities": {"type": "keyword"},
        "category_ids": {"type": "keyword"},
        "source_location": {"type": "object", "enabled": True},
        "metadata": {"type": "object", "enabled": False},
        # 문서함 active/deactive 필터용 (Document.status)
        # multi-field: 기존 인덱스가 동적 매핑으로 text 가 된 경우에도 .keyword 서브필드로 동일하게 필터.
        "document_status": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 64}},
        },
        # Ontology fields (Phase B)
        "nature": {"type": "keyword"},
        "validity_status": {"type": "keyword"},
        "entities_people": {"type": "keyword"},
        "entities_orgs": {"type": "keyword"},
        "speakers": {"type": "keyword"},
    }
}


def build_es_index_name(tenant_slug: str, repository_id: UUID | None = None) -> str:
    """Elasticsearch 인덱스 이름 생성.

    블럭 파이프라인 (현재 표준): 항상 aicm_{tenant_slug}_blocks 단일 인덱스 사용.
    repository_id 는 ES query filter (term) 로 격리 (인덱스를 나누지 않음).
    """
    return build_block_es_index_name(tenant_slug)


def build_block_es_index_name(tenant_slug: str) -> str:
    """블럭 파이프라인용 ES 인덱스 이름 생성: aicm_{tenant_slug}_blocks."""
    return f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"


class ESKeywordSearcher:
    """
    Elasticsearch 기반 전통적 키워드 검색.

    - nori 한국어 분석기 사용
    - BM25 스코어링
    - 하이라이팅 지원
    - 블럭 인덱스 지원 (테넌트 단일 _blocks 인덱스)
    """

    def __init__(self, client: AsyncElasticsearch | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncElasticsearch:
        """지연 초기화된 ES 클라이언트 반환."""
        if self._client is None:
            self._client = AsyncElasticsearch(
                hosts=[settings.ELASTICSEARCH_URL],
                request_timeout=15,
                max_retries=2,
                retry_on_timeout=True,
            )
        return self._client

    async def ensure_index(self, index_name: str) -> None:
        """청크 인덱스가 없으면 생성."""
        client = await self._get_client()
        exists = await client.indices.exists(index=index_name)
        if not exists:
            await client.indices.create(
                index=index_name,
                settings=INDEX_SETTINGS,
                mappings=INDEX_MAPPING,
            )
            log.info("es_index_created", index=index_name)

    async def ensure_block_index(self, index_name: str) -> None:
        """블럭 인덱스가 없으면 생성."""
        client = await self._get_client()
        exists = await client.indices.exists(index=index_name)
        if not exists:
            await client.indices.create(
                index=index_name,
                settings=INDEX_SETTINGS,
                mappings=BLOCK_INDEX_MAPPING,
            )
            log.info("es_block_index_created", index=index_name)

    async def index_blocks(
        self,
        index_name: str,
        blocks: list[dict],
        expected_tenant_id: str | None = None,
    ) -> int:
        """블럭 목록을 ES 에 벌크 인덱싱한다.

        Parameters
        ----------
        index_name : str
            블럭 ES 인덱스 이름 (e.g. aicm_{tenant}_blocks)
        blocks : list[dict]
            각 블럭의 ES 문서 딕셔너리. 필드:
            block_id, document_id, repository_id, tenant_id, block_type,
            content, block_index, keywords, entities, metadata
        expected_tenant_id : str | None
            Lucas-KMS Phase 2 T2.6 — caller 가 알고 있는 tenant_id. 명시되면
            모든 doc 의 ``tenant_id`` field 가 동일한지 검증 (fail-fast).
            누락 시 ``MissingTenantIdError``. ``RLS_ENFORCE=True`` 환경에서
            반드시 명시할 것.

        Returns
        -------
        int
            인덱싱된 문서 수
        """
        if not blocks:
            return 0

        # Lucas-KMS Phase 2 T2.6 — payload-level tenant_id 검증.
        # expected_tenant_id 가 명시되면 모든 doc 의 ``tenant_id`` field 가 동일한지
        # fail-fast. 미명시 시 (legacy seed/test 호환) skip — 상위 진입점
        # (``_es_index_blocks``) 가 fail-fast 책임 진다.
        if expected_tenant_id:
            from src.search.es_wrapper import ensure_tenant_id_field

            for doc in blocks:
                ensure_tenant_id_field(doc, expected_tenant_id)
        elif settings.RLS_ENFORCE:
            # RLS_ENFORCE 환경에서 expected_tenant_id 누락은 *권고 위반* 이지만
            # 본 메서드는 *thin wrapper* — 상위 진입점에서 강제하도록 위임.
            # 누락 시 로그만 남기고 진행 (회귀 방지).
            log.warning(
                "es_index_blocks_called_without_expected_tenant_id",
                index=index_name,
                doc_count=len(blocks),
            )

        client = await self._get_client()
        await self.ensure_block_index(index_name)

        # 벌크 액션 구성
        actions: list[dict] = []
        for doc in blocks:
            actions.append({"index": {"_index": index_name, "_id": doc.get("block_id")}})
            actions.append(doc)

        try:
            response = await client.bulk(operations=actions, refresh="wait_for")
            errors = response.get("errors", False)
            error_count = 0
            if errors:
                error_items = [
                    item
                    for item in response.get("items", [])
                    if "error" in item.get("index", {})
                ]
                error_count = len(error_items)
                log.warning(
                    "es_block_bulk_partial_errors",
                    index=index_name,
                    error_count=error_count,
                )
            indexed = len(blocks) - error_count
            log.info("es_block_index_complete", index=index_name, indexed=indexed)
            return indexed
        except Exception:
            log.exception("es_block_bulk_index_failed", index=index_name)
            return 0

    async def search(
        self,
        keywords: list[str],
        index_name: str,
        top_k: int = 20,
        category_ids: list[str] | None = None,
        document_type_ids: list[str] | None = None,
        block_types: list[str] | None = None,
        repository_ids: list[str] | None = None,
        nature_filter: list[str] | None = None,
        validity_filter: str = "active",
        entity_filter: dict | None = None,
        document_status_filter: str = "active",
        # D32 §3 — tenant isolation. caller_slug 미명시 시 legacy 호환.
        caller_tenant_slug: str | None = None,
        rls_scope: str | None = None,
        allow_cross_namespace: bool = False,
        # Lucas-KMS Phase 2 T2.6 — payload-level tenant_id must filter (이중 안전망).
        # index naming 만으로 부족 — payload tenant_id 가 있을 때 명시 강제.
        # 미명시 (None) 시 legacy chunk (payload 에 tenant_id 부재) 호환 — index
        # naming 만 의존 (silent compat). 새로 인덱싱된 chunk 부터 tenant_id 가 채워짐.
        tenant_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> tuple[list[SearchHit], SearchTraceStep]:
        """키워드 기반 BM25 검색 수행.

        블럭 인덱스(이름이 _blocks 로 끝남)인 경우:
        - repository_ids / block_types 필터를 적용한다.
        - 결과를 _to_block_hit 으로 변환한다.
        """
        start = time.monotonic()
        # D33 §2 — fail-closed guard (사전 GPT-5 강력 권고).
        if not caller_tenant_slug and settings.RLS_ENFORCE:
            from src.search.tenant_isolation import CrossTenantSearchError
            raise CrossTenantSearchError(
                caller_slug="(missing)",
                target_namespace=index_name,
                scope=rls_scope,
            )
        # D32 §3 — namespace mismatch 즉시 차단.
        if caller_tenant_slug:
            from src.search.tenant_isolation import assert_tenant_namespace
            assert_tenant_namespace(
                namespace=index_name,
                caller_slug=caller_tenant_slug,
                scope=rls_scope,
                allow_cross_namespace=allow_cross_namespace,
                backend="es",
            )
        client = await self._get_client()
        is_block_index = index_name.endswith("_blocks")

        keyword_text = " ".join(keywords)

        if is_block_index:
            # 블럭 인덱스: content + document_title 멀티필드 검색
            query: dict = {
                "bool": {
                    "should": [
                        {"match": {"content": {"query": keyword_text, "boost": 2.0}}},
                        {"match": {"document_title": {"query": keyword_text, "boost": 1.5}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
            filters: list[dict] = []
            # Lucas-KMS Phase 2 T2.6 — payload-level tenant_id must filter.
            # index naming 만으로 부족, must filter 도 (이중 안전망).
            if tenant_id:
                filters.append({"term": {"tenant_id": str(tenant_id)}})
            if repository_ids:
                filters.append({"terms": {"repository_id": repository_ids}})
            if document_ids:
                filters.append({"terms": {"document_id": document_ids}})
            if category_ids:
                filters.append({"terms": {"category_ids": category_ids}})
            if block_types:
                filters.append({"terms": {"block_type": block_types}})
            # Ontology filters (Phase B)
            if nature_filter:
                filters.append({"terms": {"nature": nature_filter}})
            if validity_filter == "active":
                filters.append({"term": {"validity_status": "active"}})
            elif validity_filter == "historical":
                filters.append({"terms": {"validity_status": ["active", "historical"]}})
            # 문서 상태(active/deactive) 필터 — 기본 "active"만, "all" 이면 필터 없음.
            # multi-field 매핑이므로 .keyword 서브필드로 term 쿼리 (기존/신규 인덱스 모두 호환).
            if document_status_filter == "active":
                filters.append({"term": {"document_status.keyword": "active"}})
                # 검색 제외 문서 필터 — must_not 으로 search_excluded=true 도큐먼트 제외.
                # 필드가 없는 구형 도큐먼트는 must_not 불일치 → 결과에 포함 (하위 호환).
                # ES must_not 은 filters 목록 외부 must_not 키로 별도 처리해야 하나,
                # bool/filter 안에서 must_not 을 사용할 수 없으므로 여기선 filters 에
                # must_not 감싼 bool 쿼리를 삽입 — ES 허용 패턴.
                filters.append({"bool": {"must_not": [{"term": {"search_excluded": True}}]}})
            if entity_filter:
                if entity_filter.get("people"):
                    filters.append({"terms": {"entities_people": entity_filter["people"]}})
                if entity_filter.get("orgs"):
                    filters.append({"terms": {"entities_orgs": entity_filter["orgs"]}})
                if entity_filter.get("speakers"):
                    filters.append({"terms": {"speakers": entity_filter["speakers"]}})
        else:
            # 레거시 청크 인덱스: 멀티필드 BM25 (부스트 가중치)
            query = {
                "bool": {
                    "should": [
                        {"match": {"content": {"query": keyword_text, "boost": 2.0}}},
                        {"match": {"document_title": {"query": keyword_text, "boost": 1.5}}},
                        {"match": {"section_title": {"query": keyword_text, "boost": 1.0}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
            filters = []
            # Lucas-KMS Phase 2 T2.6 — legacy chunk 인덱스도 tenant_id 강제 (있을 시).
            if tenant_id:
                filters.append({"term": {"tenant_id": str(tenant_id)}})
            if document_ids:
                filters.append({"terms": {"document_id": document_ids}})
            if category_ids:
                filters.append({"terms": {"category_ids": category_ids}})
            if document_type_ids:
                filters.append({"terms": {"document_type": document_type_ids}})
            if block_types:
                filters.append({"terms": {"block_type": block_types}})

        if filters:
            query["bool"]["filter"] = filters

        try:
            response = await client.search(
                index=index_name,
                query=query,
                size=top_k,
                highlight={"fields": {"content": {}}},
            )
            raw_hits = response["hits"]["hits"]
        except Exception:
            log.exception("es_keyword_search_failed", index=index_name)
            raw_hits = []

        if is_block_index:
            hits = [self._to_block_hit(h) for h in raw_hits]
        else:
            hits = [self._to_hit(h) for h in raw_hits]

        elapsed_ms = int((time.monotonic() - start) * 1000)

        trace = SearchTraceStep(
            step_name="keyword_search",
            latency_ms=elapsed_ms,
            candidate_count=len(hits),
            details={
                "index": index_name,
                "keywords": keywords,
                "block_mode": is_block_index,
                "top_scores": [round(h.keyword_score, 4) for h in hits[:5]] if hits else [],
            },
        )

        log.info(
            "keyword_search_completed",
            index=index_name,
            candidates=len(hits),
            latency_ms=elapsed_ms,
            block_mode=is_block_index,
        )
        return hits, trace

    async def resolve_documents_by_title(
        self,
        text: str,
        index_name: str,
        repository_ids: list[str] | None,
        tenant_id: str | None,
        top_n: int = 5,
    ) -> list[tuple[str, float]]:
        """text 를 document_title 에 match 하고 document_id 별 최고 스코어로 집계.

        IDF 가 공통 토큰(증권자투자신탁/주식 등)을 자동 강등하고 희소 브랜드 토큰
        (하나코리아 등)을 부각 — 별도 토큰선별 불요. 앵커 후보를 (doc_id, score)로 반환.
        """
        if not text.strip():
            return []
        client = await self._get_client()
        must: list[dict] = [{"match": {"document_title": text}}]
        flt: list[dict] = []
        if tenant_id:
            flt.append({"term": {"tenant_id": str(tenant_id)}})
        if repository_ids:
            flt.append({"terms": {"repository_id": repository_ids}})
        body = {
            "size": 0,
            "query": {"bool": {"must": must, "filter": flt}},
            "aggs": {"by_doc": {
                "terms": {"field": "document_id", "size": top_n, "order": {"max_score": "desc"}},
                "aggs": {"max_score": {"max": {"script": "_score"}}},
            }},
        }
        try:
            resp = await client.search(index=index_name, body=body)
        except Exception:
            log.warning("resolve_documents_by_title_failed", index=index_name, exc_info=True)
            return []
        buckets = (((resp or {}).get("aggregations") or {}).get("by_doc") or {}).get("buckets") or []
        return [(b["key"], float(b["max_score"]["value"])) for b in buckets]

    @staticmethod
    def _to_hit(es_hit: dict) -> SearchHit:
        """Elasticsearch hit를 SearchHit으로 변환 (레거시 청크 인덱스)."""
        source = es_hit.get("_source", {})
        source_loc_data = source.get("source_location", {})

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

        highlight = es_hit.get("highlight", {})

        chunk_id_str = source.get(
            "chunk_id", es_hit.get("_id", "00000000-0000-0000-0000-000000000000")
        )

        # D85c-잔존 (2026-05-13) — legacy chunk index 도 repository_id 노출.
        # block 인덱스 (`_to_block_hit`) 와 동일 path. 누락 시 cross-brand
        # post-filter 가 "missing-repo-id" 로 분류, citation full_url 누락.
        # GPT-5.5 D85c-잔존 P2 — dirty payload (UUID 아닌 string) 도 안전 처리.
        _repo_id_str = source.get("repository_id")
        _repo_id: UUID | None = None
        if _repo_id_str:
            try:
                _repo_id = UUID(str(_repo_id_str))
            except (TypeError, ValueError):
                _repo_id = None
        return SearchHit(
            chunk_id=UUID(chunk_id_str),
            document_id=UUID(
                source.get("document_id", "00000000-0000-0000-0000-000000000000")
            ),
            document_title=source.get("document_title", ""),
            section_title=source.get("section_title"),
            content=source.get("content", ""),
            document_type=source.get("document_type"),
            category_names=source.get("category_names", []),
            metadata={**source.get("metadata", {}), "highlight": highlight},
            keyword_score=float(es_hit.get("_score", 0.0)),
            repository_id=_repo_id,
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

    @staticmethod
    def _to_block_hit(es_hit: dict) -> SearchHit:
        """Elasticsearch hit를 SearchHit으로 변환 (블럭 인덱스)."""
        source = es_hit.get("_source", {})
        source_loc_data = source.get("source_location", {})

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

        highlight = es_hit.get("highlight", {})

        block_id_str = source.get(
            "block_id", es_hit.get("_id", "00000000-0000-0000-0000-000000000000")
        )
        doc_id_str = source.get("document_id", "00000000-0000-0000-0000-000000000000")
        repo_id_str = source.get("repository_id")
        # GPT-5.5 D85c-잔존 P2 — dirty payload (UUID 아닌 string) 도 안전 처리.
        _block_repo_id: UUID | None = None
        if repo_id_str:
            try:
                _block_repo_id = UUID(str(repo_id_str))
            except (TypeError, ValueError):
                _block_repo_id = None

        # 블럭 인덱스에서 document_title, repository_name 읽기
        _doc_title = source.get("document_title", "")
        _repo_name = source.get("repository_name", "")
        _meta = {**source.get("metadata", {}), "highlight": highlight}
        if _repo_name:
            _meta["repository_name"] = _repo_name

        # KMS-Plus 2026-05-07 — multimodal block 필드 surface (qdrant 와 대칭).
        # ES 블럭 인덱스에 indexed 된 table_markdown / image_description / ocr_text
        # 가 있으면 metadata 로 끌어올린다. 없으면 영향 0 (회귀 0).
        for _k in (
            "table_markdown",
            "table_headers",
            "image_description",
            "image_path",
            "ocr_text",
        ):
            _v = source.get(_k)
            if _v is not None and _k not in _meta:
                _meta[_k] = _v

        return SearchHit(
            chunk_id=UUID(block_id_str),  # 레거시 호환: chunk_id = block_id
            document_id=UUID(doc_id_str),
            document_title=_doc_title,
            section_title=None,
            content=source.get("content", ""),
            document_type=None,
            category_names=[],
            metadata=_meta,
            keyword_score=float(es_hit.get("_score", 0.0)),
            block_id=UUID(block_id_str),
            block_type=source.get("block_type"),
            block_index=source.get("block_index"),
            repository_id=_block_repo_id,
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
