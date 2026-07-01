"""검색 오케스트레이터 — 전체 검색 파이프라인 통합."""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.common.logging import get_logger
from src.search.cache import LLMResponseCache, SearchCache
from src.search.context_weighting import (
    build_context_text,
    combine_dense_vectors,
    context_fingerprint,
)
from src.search.highlighter import SearchHighlighter
from src.search.hybrid.es_keyword import ESKeywordSearcher, build_es_index_name
from src.search.hybrid.fusion import RRFFusion
from src.search.hybrid.preprocessor import QueryPreprocessor
from src.search.hybrid.qdrant_dense import QdrantDenseSearcher, build_collection_name
from src.search.hybrid.qdrant_sparse import QdrantSparseSearcher
from src.search.metrics import (
    observe_search_duration,
    record_cache_hit,
    record_cache_miss,
    record_no_results,
    record_reranker_call,
    record_search_request,
)
from src.search.models import (
    QueryAnalysis,
    QueryMetadata,
    RAGContextRequest,
    RAGContextResponse,
    SearchConfig,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SearchTrace,
    SearchTraceStep,
    SearchWeights,
)
from src.search.query_decomposer import DecomposedQuery, QueryDecomposer
from src.search.query_expander import QueryExpander
from src.search.rag.context_builder import ContextBuilder
from src.search.reranker.cross_encoder import CrossEncoderReranker
from src.search.reranker.mmr import mmr_rerank
from src.search.search_log import SearchLogRecorder

log = get_logger(__name__)


def _get_webhook_dispatcher():
    """WebhookDispatcher를 지연 로딩한다. Agent E 미완성 시 None."""
    try:
        from src.integration.webhook.dispatcher import WebhookDispatcher

        return WebhookDispatcher
    except ImportError:
        return None


def _section_title_from_heading_path(source_location) -> str:
    """heading_path 를 섹션 제목 문자열로. 없으면 빈 문자열.

    검색된 블럭(표 등)이 자기 섹션 제목(예: "9. 환매수수료")을 갖고 반환되도록
    한다. 헤딩이 별도 빈 블럭으로 분리돼 표 블럭에 제목이 없던 문제를 결과 단계에서
    보강(재임베딩 불요). QNA 의 section_title(=질문)은 호출부에서 'or' 우선 보존.
    """
    try:
        hp = getattr(source_location, "heading_path", None) or []
    except Exception:
        return ""
    parts = [str(h).strip() for h in hp if h and str(h).strip()]
    return " > ".join(parts)


def _drop_empty_heading_hits(hits: list) -> list:
    """본문 없는 헤딩 블럭(제목 한 줄뿐)을 검색 후보에서 제외한다.

    heading_path 가 본문 블럭에 섹션 컨텍스트를 surface 하므로 standalone 헤딩 블럭
    (예: "### 9. 환매수수료" 만 있고 표는 별도 블럭)은 답변 가치 0 이고 top-k 슬롯만
    차지해 정답 본문 블럭을 밀어낸다. rerank/top_k 선별 *전* 후보 풀에 적용해 다음 본문
    블럭이 슬롯을 채우게 한다. 본문을 흡수한 헤딩(여러 줄)은 보존한다.
    """
    out = []
    for h in hits:
        bt = getattr(h, "block_type", None) or ""
        if bt.startswith("heading"):
            content = (getattr(h, "content", None) or "").strip()
            lines = [ln for ln in content.split("\n") if ln.strip()]
            if len(lines) <= 1:
                continue
        out.append(h)
    return out


class SearchService:
    """
    검색 오케스트레이터.

    전체 파이프라인을 통합하여 단일 인터페이스로 제공:
    1. 질의 전처리
    2. 병렬 Dense + Sparse + Keyword 검색
    3. RRF Fusion
    4. Cross-encoder Reranking
    5. RAG 컨텍스트 빌딩 (선택적)
    """

    def __init__(
        self,
        preprocessor: QueryPreprocessor | None = None,
        dense_searcher: QdrantDenseSearcher | None = None,
        sparse_searcher: QdrantSparseSearcher | None = None,
        keyword_searcher: ESKeywordSearcher | None = None,
        fusion: RRFFusion | None = None,
        reranker: CrossEncoderReranker | None = None,
        context_builder: ContextBuilder | None = None,
        log_recorder: SearchLogRecorder | None = None,
        embedding_fn: object | None = None,
        highlighter: SearchHighlighter | None = None,
        webhook_session: object | None = None,
        search_cache: SearchCache | None = None,
        llm_cache: LLMResponseCache | None = None,
        query_rewriter: object | None = None,
        query_expander: QueryExpander | None = None,
        query_decomposer: QueryDecomposer | None = None,
        llm_query_rewriter: object | None = None,
        llm_reranker: object | None = None,
        sufficiency_evaluator: object | None = None,
        synonym_normalizer: object | None = None,
        query_splitter: object | None = None,
    ) -> None:
        self._preprocessor = preprocessor or QueryPreprocessor()
        self._dense_searcher = dense_searcher or QdrantDenseSearcher()
        self._sparse_searcher = sparse_searcher or QdrantSparseSearcher()
        self._keyword_searcher = keyword_searcher or ESKeywordSearcher()
        self._fusion = fusion or RRFFusion()
        self._reranker = reranker or CrossEncoderReranker()
        self._context_builder = context_builder or ContextBuilder()
        self._log_recorder = log_recorder or SearchLogRecorder()
        self._embedding_fn = embedding_fn
        self._highlighter = highlighter or SearchHighlighter()
        self._webhook_session = webhook_session
        self._search_cache = search_cache or SearchCache()
        self._llm_cache = llm_cache or LLMResponseCache()
        self._query_rewriter = query_rewriter  # QueryRewriter 인스턴스 (선택적)
        self._query_expander = query_expander  # HyDE 쿼리 확장기 (선택적)
        self._query_decomposer = query_decomposer  # QueryDecomposer (선택적, Phase B)
        self._llm_query_rewriter = llm_query_rewriter  # LLMQueryRewriter (오타/동의어/재구성)
        self._llm_reranker = llm_reranker  # LLMReranker (LLM 기반 리랭킹)
        self._sufficiency_evaluator = sufficiency_evaluator  # SufficiencyEvaluator (충분성 평가)
        # Wave Wire-up Final — SynonymNormalizer (선택). 검색 query 의 도메인 동의어 확장.
        self._synonym_normalizer = synonym_normalizer
        self._query_splitter = query_splitter  # QuerySplitter (선택적, #2 분해→멀티검색)
        import os
        self._decomp_enabled = os.getenv("SEARCH_QUERY_DECOMPOSITION_ENABLED", "true").lower() == "true"
        self._decomp_max = int(os.getenv("SEARCH_DECOMPOSITION_MAX_SUBQUERIES", "4"))
        self._decomp_timeout = float(os.getenv("SEARCH_DECOMPOSITION_TIMEOUT_S", "2.0"))
        self._decomp_concurrency = 2
        log.info("search_service_initialized")

    def _resolve_config(
        self,
        weights: SearchWeights | None = None,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> SearchConfig:
        """
        검색 설정 결정.

        우선순위: API 요청 weights > repo config > tenant config > 기본값
        """
        config = SearchConfig()

        # 테넌트 config 오버라이드
        if tenant_config:
            search_cfg = tenant_config.get("search", {})
            if "dense_weight" in search_cfg:
                config.dense_weight = search_cfg["dense_weight"]
            if "sparse_weight" in search_cfg:
                config.sparse_weight = search_cfg["sparse_weight"]
            if "keyword_weight" in search_cfg:
                config.keyword_weight = search_cfg["keyword_weight"]
            if "rrf_k" in search_cfg:
                config.rrf_k = search_cfg["rrf_k"]
            if "rerank_enabled" in search_cfg:
                config.rerank_enabled = search_cfg["rerank_enabled"]
            if "min_score_threshold" in search_cfg:
                config.min_score_threshold = search_cfg["min_score_threshold"]

        # 저장소 config 오버라이드
        if repo_config:
            search_cfg = repo_config.get("search", {})
            if "dense_weight" in search_cfg:
                config.dense_weight = search_cfg["dense_weight"]
            if "sparse_weight" in search_cfg:
                config.sparse_weight = search_cfg["sparse_weight"]
            if "keyword_weight" in search_cfg:
                config.keyword_weight = search_cfg["keyword_weight"]
            if "rrf_k" in search_cfg:
                config.rrf_k = search_cfg["rrf_k"]
            if "rerank_enabled" in search_cfg:
                config.rerank_enabled = search_cfg["rerank_enabled"]

        return config

    async def _get_embeddings(self, text: str) -> tuple[list[float], dict[int, float]]:
        """임베딩 함수를 통해 dense + sparse 벡터 생성."""
        if self._embedding_fn is None:
            raise RuntimeError(
                "embedding_fn이 설정되지 않았습니다. "
                "SearchService 생성 시 embedding_fn을 주입하세요."
            )
        return await self._embedding_fn(text)

    # D17 (2026-05-08): IMAGE block 노이즈 결정은 ingest 시 LLM is_decorative
    # 가 함. 본 frozenset 은 *defense in depth* 안전망 (인덱스 stale / DB
    # is_noise sync gap 시 metadata.image_type 으로 한 번 더 차단).
    _NOISE_IMAGE_TYPES_FALLBACK: frozenset[str] = frozenset({
        "logo", "header", "footer", "watermark", "decorative",
    })

    async def _filter_noise_hits(self, hits: list[SearchHit]) -> list[SearchHit]:
        """DB 의 is_noise=True 또는 metadata.image_type ∈ NOISE 블럭을 결과에서 제거한다.

        인덱스(Qdrant/ES)는 initial 인덱싱 시점에서 노이즈를 제외하고,
        demote 시 포인트를 삭제한다. 그러나 demote 시 Qdrant/ES 순간 불통 등의
        이유로 인덱스에 노이즈가 남아있을 수 있으므로, DB 를 신뢰 소스로 삼아
        최종 결과를 후필터링한다.

        D17 강화: image_type ∈ {logo, header, footer, watermark, decorative}
        도 함께 차단 (LLM 분석 후 노이즈 마킹 못 한 stale 블럭 방어).
        """
        if not hits:
            return hits

        block_ids: list[str] = []
        for h in hits:
            bid = h.block_id or h.chunk_id
            if bid is not None:
                block_ids.append(str(bid))
        if not block_ids:
            return hits

        try:
            from sqlalchemy import or_, select
            from src.core.database import async_session_factory
            from src.core.models.block import Block

            async with async_session_factory() as session:
                # D17: is_noise=True OR metadata->>'image_type' IN noise enum
                # ORM 속성 = Block.meta_info (실 컬럼명 = 'metadata')
                noise_image_types = list(self._NOISE_IMAGE_TYPES_FALLBACK)
                stmt = select(Block.id).where(
                    Block.id.in_(block_ids),
                    or_(
                        Block.is_noise == True,  # noqa: E712
                        Block.meta_info["image_type"].astext.in_(noise_image_types),
                        Block.meta_info["is_decorative"].astext == "true",
                    ),
                )
                result = await session.execute(stmt)
                noise_ids = {str(row[0]) for row in result.all()}
        except Exception as exc:
            log.warning("noise_filter_db_lookup_failed", error=str(exc))
            return hits

        if not noise_ids:
            return hits

        filtered = [
            h for h in hits if str(h.block_id or h.chunk_id or "") not in noise_ids
        ]
        log.info(
            "noise_hits_filtered",
            removed=len(hits) - len(filtered),
            total=len(hits),
            noise_ids=list(noise_ids)[:5],
        )
        return filtered

    async def search(
        self,
        request: SearchRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> SearchResponse:
        """
        검색 수행 (트레이스 없이).

        간단한 검색 결과만 필요한 경우 사용.
        캐시 확인 -> 캐시 히트 시 즉시 반환, 미스 시 파이프라인 실행 후 캐시 저장.
        """
        # 캐시 키 생성용 weights dict
        weights_dict = None
        if request.weights:
            weights_dict = {}
            if request.weights.dense is not None:
                weights_dict["dense"] = request.weights.dense
            if request.weights.sparse is not None:
                weights_dict["sparse"] = request.weights.sparse
            if request.weights.keyword is not None:
                weights_dict["keyword"] = request.weights.keyword

        # 캐시 확인 — 대화이력 지문을 캐시 키에 포함한다. 게이트를 context_weighted 가 아니라
        # conversation_history 로 둔다: 컨텍스트 앵커(resolve-then-scope)가 conversation_history
        # 로 발화해 결과(앵커 스코프)를 좌우하는데, 라우터가 context_weighted 를 매핑하지 않아
        # 기본 False 다. 이력 유무로 결과가 달라지므로 이력을 키에 반영하지 않으면 앵커 결과가
        # 비앵커(콜드) 질의에 누출된다(앵커/비앵커 캐시 분리).
        _ctx_fp = (
            context_fingerprint(request.conversation_history, request.w_c, request.w_p)
            if request.conversation_history
            and (settings.CONTEXT_ANCHOR_ENABLED or request.context_weighted)
            else ""
        )
        cached = await self._search_cache.get(
            query=request.query,
            repository_id=request.repository_id,
            category_ids=request.category_ids,
            weights=weights_dict,
            search_mode=request.search_mode,
            top_k=request.top_k,
            rerank=request.rerank,
            context_key=_ctx_fp,
        )
        if cached is not None:
            record_search_request(mode=request.search_mode, cached=True)
            record_cache_hit()
            log.info("search_served_from_cache", query=request.query[:100])
            return SearchResponse(**cached)

        record_cache_miss()
        record_search_request(mode=request.search_mode, cached=False)

        fallback_level = 1
        decomposed_dict: dict | None = None
        analysis: QueryAnalysis = {"rewritten_query": request.query, "keywords": []}
        if request.use_fallback:
            results, _, total_latency, fallback_level, decomposed_dict, analysis = (
                await self._search_with_fallback(
                    request=request,
                    tenant_slug=tenant_slug,
                    tenant_config=tenant_config,
                    repo_config=repo_config,
                )
            )
        else:
            results, _, total_latency, decomposed_dict, analysis = await self._execute_with_split(
                request=request,
                tenant_slug=tenant_slug,
                tenant_config=tenant_config,
                repo_config=repo_config,
            )

        # 하이라이팅 적용
        if request.highlight and results:
            processed, _ = await self._preprocessor.preprocess(request.query)
            self._highlighter.highlight_hits(results, processed.keywords)

        # min_score 기반 결과 필터링 (관련도 낮은 결과 제거)
        effective_min = request.min_score if request.min_score > 0 else 0.0
        if effective_min > 0 and results:
            before = len(results)
            results = [h for h in results if h.score >= effective_min]
            if len(results) < before:
                log.debug(
                    "min_score_filtered",
                    threshold=effective_min,
                    before=before,
                    after=len(results),
                )

        # 응답 조립
        items = self._to_result_items(results, request.include_content)

        strategy = request.search_mode
        if fallback_level > 1:
            strategy = f"{request.search_mode}+fallback_L{fallback_level}"

        response = SearchResponse(
            results=items,
            query_metadata=QueryMetadata(
                latency_ms=total_latency,
                total_candidates=len(results),
                strategy_used=strategy,
            ),
            decomposed=decomposed_dict,
            keywords=analysis["keywords"],
            rewritten_query=(
                analysis["rewritten_query"]
                if analysis["rewritten_query"].strip() != request.query.strip()
                else None
            ),
        )

        # 결과 없음 메트릭
        if not items:
            record_no_results()

        # 캐시 저장 (비동기, fire-and-forget)
        try:
            await self._search_cache.set(
                query=request.query,
                repository_id=request.repository_id,
                data=response.model_dump(mode="json"),
                category_ids=request.category_ids,
                weights=weights_dict,
                search_mode=request.search_mode,
                top_k=request.top_k,
                rerank=request.rerank,
                context_key=_ctx_fp,
            )
        except Exception:
            log.warning("search_cache_store_failed", exc_info=True)

        # 비동기 검색 로그 기록
        self._log_recorder.record_fire_and_forget(
            tenant_id=request.tenant_id,
            repository_id=request.repository_id,
            query=request.query,
            query_source=None,
            result_count=len(items),
            top_chunk_ids=[item.chunk_id for item in items[:10]],
            top_scores=[item.score for item in items[:10]],
            latency_ms=total_latency,
        )

        # Webhook 이벤트 발행 (fire-and-forget)
        self._fire_search_webhook_events(
            tenant_id=request.tenant_id,
            query=request.query,
            result_count=len(items),
            top_score=items[0].score if items else 0.0,
        )

        return response

    async def search_with_cross_tenant(
        self,
        request: SearchRequest,
        tenant_slug: str,
        user_id: UUID | None = None,
        db: AsyncSession | None = None,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> SearchResponse:
        """검색 수행 + TenantLink 기반 교차 테넌트 검색.

        활성 TenantLink가 존재하면 상대방 테넌트도 검색하고 결과를 병합한다.
        link_config 제한 사항이 적용되어 허용된 nature만 교차 검색된다.

        Args:
            request: 검색 요청
            tenant_slug: 현재 테넌트 slug
            user_id: 현재 사용자 ID (None이면 교차 검색 스킵)
            db: DB 세션 (교차 검색 시 필요)
            tenant_config: 테넌트 설정
            repo_config: 저장소 설정

        Returns:
            교차 검색 결과가 병합된 SearchResponse
        """
        # 1단계: 주 테넌트 검색
        primary_response = await self.search(
            request=request,
            tenant_slug=tenant_slug,
            tenant_config=tenant_config,
            repo_config=repo_config,
        )

        # 교차 검색 조건 미충족 시 그대로 반환
        if not user_id or not db:
            return primary_response

        # 2단계: TenantLink 조회
        try:
            from src.search.cross_tenant import (
                apply_link_config,
                get_active_link,
                get_other_tenant_id,
                get_tenant_slug,
                merge_results,
                tag_cross_tenant_hits,
            )

            link = await get_active_link(db, user_id, request.tenant_id)
            if not link:
                return primary_response

            other_tenant_id = get_other_tenant_id(link, request.tenant_id)
            other_slug = await get_tenant_slug(db, other_tenant_id)
            if not other_slug:
                log.warning(
                    "cross_tenant_slug_not_found",
                    other_tenant_id=str(other_tenant_id),
                )
                return primary_response

            # 3단계: link_config 적용 후 교차 검색
            cross_request = apply_link_config(
                request, link.link_config, other_tenant_id
            )

            cross_start = time.monotonic()
            cross_results, _, cross_latency, _, _ = await self._execute_pipeline(
                request=cross_request,
                tenant_slug=other_slug,
                tenant_config=None,
                repo_config=None,
            )

            # 소스 태그 추가
            is_corporate = link.corporate_tenant_id == other_tenant_id
            source_type = "corporate" if is_corporate else "personal"
            tag_cross_tenant_hits(cross_results, other_tenant_id, source_type)

            # 4단계: 주 결과와 병합
            # primary_response의 결과를 SearchHit으로 재구성하기 어려우므로
            # cross_results를 ResultItem으로 변환하여 추가
            cross_items = self._to_result_items(cross_results, request.include_content)
            for item in cross_items:
                item.metadata["cross_tenant"] = True
                item.metadata["source_tenant"] = source_type

            # 결과 병합 (스코어 기반)
            all_items = primary_response.results + cross_items
            all_items.sort(key=lambda x: x.score, reverse=True)

            # 교차 결과 비율 제한 (최대 40%)
            max_cross = max(1, int(len(all_items) * 0.4))
            cross_count = sum(
                1 for item in all_items if item.metadata.get("cross_tenant")
            )
            if cross_count > max_cross:
                # 교차 결과 초과 시 스코어 낮은 것부터 제거
                kept = []
                cross_kept = 0
                for item in all_items:
                    if item.metadata.get("cross_tenant"):
                        if cross_kept < max_cross:
                            kept.append(item)
                            cross_kept += 1
                    else:
                        kept.append(item)
                all_items = sorted(kept, key=lambda x: x.score, reverse=True)

            total_latency = primary_response.query_metadata.latency_ms + cross_latency
            primary_response.results = all_items
            primary_response.query_metadata.latency_ms = total_latency
            primary_response.query_metadata.strategy_used += "+cross_tenant"
            primary_response.query_metadata.total_candidates += len(cross_results)

            log.info(
                "cross_tenant_search_completed",
                primary_count=len(primary_response.results) - len(cross_items),
                cross_count=len(cross_items),
                total_latency_ms=total_latency,
            )

        except Exception as e:
            log.warning(
                "cross_tenant_search_failed",
                error=str(e),
                user_id=str(user_id),
            )
            # 교차 검색 실패 시 주 결과만 반환 (graceful degradation)

        return primary_response

    async def search_with_trace(
        self,
        request: SearchRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> tuple[SearchResponse, SearchTrace]:
        """
        검색 수행 + 트레이스 데이터 반환 (Playground용).

        각 단계의 레이턴시, 후보 수, 스코어를 상세히 기록.
        """
        results, trace, total_latency, decomposed_dict, analysis = await self._execute_pipeline(
            request=request,
            tenant_slug=tenant_slug,
            tenant_config=tenant_config,
            repo_config=repo_config,
        )

        items = self._to_result_items(results, request.include_content)

        response = SearchResponse(
            results=items,
            query_metadata=QueryMetadata(
                latency_ms=total_latency,
                total_candidates=len(results),
                strategy_used=request.search_mode,
            ),
            decomposed=decomposed_dict,
            keywords=analysis["keywords"],
            rewritten_query=(
                analysis["rewritten_query"]
                if analysis["rewritten_query"].strip() != request.query.strip()
                else None
            ),
        )

        # 비동기 검색 로그 기록
        self._log_recorder.record_fire_and_forget(
            tenant_id=request.tenant_id,
            repository_id=request.repository_id,
            query=request.query,
            query_source="playground",
            result_count=len(items),
            top_chunk_ids=[item.chunk_id for item in items[:10]],
            top_scores=[item.score for item in items[:10]],
            latency_ms=total_latency,
        )

        return response, trace

    async def rag_retrieve(
        self,
        request: SearchRequest,
        tenant_slug: str,
        max_context_tokens: int = 2000,
        compress: bool = False,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> tuple[list[SearchHit], int]:
        """RAG 전용 검색 — 토큰 예산 기반 결과 반환.

        Knowledge Search (self.search)와 분리된 RAG 전용 메서드.
        - 결과 수: 3-5건 (top_k로 제어, 일반 검색보다 적음)
        - 토큰 예산: max_context_tokens 이내만 반환
        - 리랭킹 우선: 정밀도 극대화

        Args:
            request: 검색 요청 (top_k는 3-5 권장)
            tenant_slug: 테넌트 슬러그
            max_context_tokens: 컨텍스트 토큰 예산
            compress: 긴 청크 압축 여부 (라우터에서 처리)
            tenant_config: 테넌트 설정
            repo_config: 저장소 설정

        Returns:
            (hits, total_tokens) — 예산 내 검색 결과와 사용된 토큰 수
        """
        # 검색 파이프라인 실행 (일반 검색과 동일)
        results, _, _, _, _ = await self._execute_pipeline(
            request=request,
            tenant_slug=tenant_slug,
            tenant_config=tenant_config,
            repo_config=repo_config,
        )

        # 인접 블럭 확장: 검색된 블럭의 전후 블럭을 자동 포함 (교차 참조 대응)
        results = await self._expand_adjacent_blocks(results, tenant_slug)
        # 인접 확장 과정에서 재유입될 수 있는 노이즈 블럭 재방어.
        results = await self._filter_noise_hits(results)

        # 토큰 예산 기반 필터링
        from src.search.rag.context_builder import _count_tokens

        filtered: list[SearchHit] = []
        total_tokens = 0

        for hit in results:
            tokens = _count_tokens(hit.content)
            if total_tokens + tokens > max_context_tokens:
                break
            filtered.append(hit)
            total_tokens += tokens

        log.info(
            "rag_retrieve_completed",
            query=request.query[:100],
            input_hits=len(results),
            output_hits=len(filtered),
            total_tokens=total_tokens,
            max_context_tokens=max_context_tokens,
        )

        return filtered, total_tokens

    async def build_rag_context(
        self,
        request: RAGContextRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> RAGContextResponse:
        """RAG 컨텍스트 빌딩. 내부적으로 검색 수행 후 컨텍스트 조립."""
        # 검색 수행
        search_request = SearchRequest(
            query=request.query,
            repository_id=request.repository_id,
            tenant_id=request.tenant_id,
            top_k=request.top_k,
            search_mode="hybrid",
            rerank=True,
            include_content=True,
            weights=request.weights,
        )

        results, _, _, _, _ = await self._execute_pipeline(
            request=search_request,
            tenant_slug=tenant_slug,
            tenant_config=tenant_config,
            repo_config=repo_config,
        )

        # 표 청크 컨텍스트 보강 (TableAwareContextBuilder)
        collection_name = build_collection_name(tenant_slug, request.repository_id)
        results = await self._context_builder.enrich_with_table_context(
            hits=results,
            collection_name=collection_name,
            max_context_tokens=request.max_context_tokens,
        )
        # 표 보강 과정에서 재유입될 수 있는 노이즈 블럭 재방어.
        results = await self._filter_noise_hits(results)

        # 모드 결정: auto → top-1 score 기반, 명시적 → 그대로
        org_type = request.organization_type or "고객서비스센터"
        if tenant_config and "organization_type" in tenant_config:
            org_type = tenant_config["organization_type"]

        mode = request.mode or "auto"
        if mode == "auto":
            mode = self._context_builder.auto_select_mode(results)
            log.info("rag_auto_mode_selected", mode=mode,
                     top_score=round(results[0].score, 3) if results else 0.0)

        if mode == "direct":
            return self._context_builder.build_direct(results)
        else:
            return self._context_builder.build_generation(
                query=request.query,
                hits=results,
                max_context_tokens=request.max_context_tokens,
                organization_type=org_type,
            )

    async def _execute_with_split(
        self,
        request: SearchRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> tuple[list[SearchHit], SearchTrace, int, dict | None, QueryAnalysis]:
        """분해→서브쿼리별 _execute_pipeline(동시제한)→라운드로빈 병합.

        _execute_pipeline 와 동일 5-tuple 반환. 플래그 off/splitter 없음/N<=1 이면 단일 위임(회귀 0).
        서브쿼리 request 는 model_copy 로 격리(in-place 변이 금지), 콜봇 명시 category_ids 보존.
        """
        if not self._decomp_enabled or self._query_splitter is None:
            return await self._execute_pipeline(request, tenant_slug, tenant_config, repo_config)

        sub_queries = await self._query_splitter.split(
            request.query,
            getattr(request, "conversation_history", None),
            max_subqueries=self._decomp_max,
            timeout_s=self._decomp_timeout,
        )
        if len(sub_queries) <= 1:
            return await self._execute_pipeline(request, tenant_slug, tenant_config, repo_config)

        from src.search.merge import round_robin_merge
        import asyncio

        sem = asyncio.Semaphore(self._decomp_concurrency)

        async def _one(sub_q: str):
            sub_req = request.model_copy(update={"query": sub_q, "enable_llm_rewrite": False})  # F6
            async with sem:
                try:
                    return await self._execute_pipeline(sub_req, tenant_slug, tenant_config, repo_config)
                except Exception as exc:
                    log.warning("split_subquery_failed", sub_query=sub_q[:80], error=str(exc))
                    return None

        results = await asyncio.gather(*[_one(q) for q in sub_queries])
        ok = [r for r in results if r is not None]
        if not ok:
            # 전부 실패 → 원본 단일검색 fallback
            return await self._execute_pipeline(request, tenant_slug, tenant_config, repo_config)

        hit_lists = [r[0] for r in ok]
        merged = round_robin_merge(hit_lists, request.top_k)
        merged.sort(key=lambda h: (h.score if getattr(h, "score", None) is not None else 0.0), reverse=True)  # F1
        # trace/analysis 는 첫 서브쿼리 것, latency 는 병렬 최대값, decomposed 는 첫 서브쿼리 것.
        first_trace = ok[0][1]
        total_latency = max(r[2] for r in ok)  # F5
        analysis = dict(ok[0][4])
        analysis["rewritten_query"] = request.query  # F2
        return merged, first_trace, total_latency, ok[0][3], analysis  # F4

    async def _resolve_anchor_doc_ids(
        self,
        request: SearchRequest,
        es_index_name: str,
        repo_ids_str: list[str] | None,
        tenant_id_str: str | None,
    ) -> list[str]:
        """대화-컨텍스트 상품 앵커 해석 — *현재 발화 우선*.

        멀티턴에서 직전 턴의 상품명이 현재 질문의 상품을 덮어써(lag-by-one) 엉뚱한
        문서로 스코프되는 문제를 막는다. 1) 현재 발화만으로 앵커를 시도하고, 2) 현재
        발화가 앵커를 못 잡은 경우(상품명 없는 발화)에만 이력을 포함해 재시도한다.
        이렇게 하면 앵커는 *현재 질문에 등장한 상품(또는 없음)*으로만 해석되어, 이력에만
        있는 상품으로는 절대 스코프되지 않는다.
        """
        from src.search.context_weighting import (
            build_anchor_query_text,
            select_anchors,
        )

        # 1) 현재 발화만으로 앵커 시도
        cur = (request.query or "").strip()
        ranked = await self._keyword_searcher.resolve_documents_by_title(
            cur, es_index_name, repo_ids_str, tenant_id_str
        )
        anchor_doc_ids = select_anchors(
            ranked, settings.ANCHOR_ABS_MIN, settings.ANCHOR_REL_RATIO
        )

        # 2) 현재 발화로 못 잡았고 이력이 있으면, 이력 포함해 폴백(상품명 없는 멀티턴 대응)
        if not anchor_doc_ids and request.conversation_history:
            anchor_text = build_anchor_query_text(
                request.query, request.conversation_history
            )
            ranked = await self._keyword_searcher.resolve_documents_by_title(
                anchor_text, es_index_name, repo_ids_str, tenant_id_str
            )
            anchor_doc_ids = select_anchors(
                ranked, settings.ANCHOR_ABS_MIN, settings.ANCHOR_REL_RATIO
            )
            # 폴백 경로로 앵커가 잡힌 경우만 관측 로그(현재 발화엔 상품명이 없어 이력으로 해석됨).
            if anchor_doc_ids:
                log.info(
                    "context_anchor_history_fallback",
                    doc_ids=anchor_doc_ids,
                    anchor_text=anchor_text[:120],
                )

        return anchor_doc_ids

    async def _execute_pipeline(
        self,
        request: SearchRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
        _disable_anchor: bool = False,
    ) -> tuple[list[SearchHit], SearchTrace, int, dict | None, QueryAnalysis]:
        """검색 파이프라인 실행. (results, trace, total_latency_ms, decomposed_dict, analysis) 반환.

        analysis: 리라이팅 후 effective_query + preprocessor 형태소 키워드.
        _disable_anchor: 컨텍스트 앵커 스코프를 강제 해제(0건 폴백 재실행 전용 내부 플래그).
        """
        pipeline_start = time.monotonic()
        trace = SearchTrace()
        config = self._resolve_config(request.weights, tenant_config, repo_config)

        # 프론트 min_score 슬라이더 연동
        if request.min_score > 0:
            config.min_score_threshold = request.min_score

        collection_name = build_collection_name(tenant_slug, request.repository_id)
        es_index_name = build_es_index_name(tenant_slug, request.repository_id)

        # Step 0-pre: LLM 쿼리 리라이팅 (오타 교정 + 대화형 재구성)
        effective_query = request.query
        if request.enable_llm_rewrite and self._llm_query_rewriter is not None:
            try:
                from src.search.llm_query_rewriter import LLMQueryRewriter

                if isinstance(self._llm_query_rewriter, LLMQueryRewriter):
                    rewrite_start = time.monotonic()

                    # 대화 이력 유무에 따라 LLM 1회 호출로 단일화:
                    #   - history 있음  → reformulate_for_search (대명사/생략 복원).
                    #     LLM 이 자연스런 정문을 생성하므로 오타 교정은 거의 불필요.
                    #   - history 없음  → correct_typos (오타/반말만 정규화).
                    # 이전 구현은 history 있을 때도 typo 를 한 번 더 호출해 LLM 왕복
                    # 2회 (~600ms) 발생. 대부분의 케이스에서 중복이라 1회 호출로 축소.
                    if request.conversation_history:
                        effective_query, _ = (
                            await self._llm_query_rewriter.reformulate_for_search(
                                effective_query,
                                conversation_history=request.conversation_history,
                            )
                        )
                    else:
                        effective_query = await self._llm_query_rewriter.correct_typos(
                            effective_query
                        )

                    rewrite_ms = int((time.monotonic() - rewrite_start) * 1000)
                    trace.steps.append(
                        SearchTraceStep(
                            step_name="llm_query_rewrite",
                            latency_ms=rewrite_ms,
                            candidate_count=0,
                            details={
                                "original": request.query[:200],
                                "rewritten": effective_query[:200],
                                "had_conversation": bool(request.conversation_history),
                            },
                        )
                    )

                    if effective_query != request.query:
                        log.info(
                            "llm_query_rewritten",
                            original=request.query[:100],
                            rewritten=effective_query[:100],
                            latency_ms=rewrite_ms,
                        )
                        # 파이프라인 나머지에서 rewritten 쿼리 사용
                        request = request.model_copy(update={"query": effective_query})
            except Exception:
                log.warning("llm_query_rewrite_step_failed", exc_info=True)

        # Step 0-syn: Wave Wire-up Final (KMS-Plus, 2026-04-25) — SynonymNormalizer.
        # env flag KMS_SYNONYM_NORMALIZE_ENABLED=true 시 query 의 도메인 동의어 확장.
        # 호출자 0건이던 모듈을 검색 경로에 wire — Phase 12 검색 품질 P0.
        # 기본값 false → 기존 검색 흐름 회귀 0. 실패 시 silent skip.
        import os as _os

        if (
            _os.environ.get("KMS_SYNONYM_NORMALIZE_ENABLED", "false").lower() == "true"
            and self._synonym_normalizer is not None
        ):
            try:
                syn_start = time.monotonic()
                norm_result = await self._synonym_normalizer.normalize(
                    query=request.query, domain_hint=None
                )
                syn_ms = int((time.monotonic() - syn_start) * 1000)
                variants = list(norm_result.variants or ())
                if variants:
                    expanded = f"{request.query} " + " ".join(variants)
                    request = request.model_copy(update={"query": expanded})
                trace.steps.append(
                    SearchTraceStep(
                        step_name="synonym_normalize",
                        latency_ms=syn_ms,
                        candidate_count=len(variants),
                        details={
                            "canonical": norm_result.canonical[:80],
                            "domain": norm_result.domain,
                            "variants_count": len(variants),
                        },
                    )
                )
                log.info(
                    "synonym_normalized",
                    canonical=norm_result.canonical[:80],
                    variant_count=len(variants),
                    latency_ms=syn_ms,
                )
            except Exception:
                log.warning("synonym_normalize_step_failed", exc_info=True)

        # Step 0a: QueryDecomposer (Phase B -- 2단계 쿼리 분해)
        decomposed: DecomposedQuery | None = None
        if self._query_decomposer is not None:
            try:
                decompose_start = time.monotonic()
                decomposed = await self._query_decomposer.decompose(request.query)
                decompose_ms = int((time.monotonic() - decompose_start) * 1000)

                trace.steps.append(
                    SearchTraceStep(
                        step_name="query_decompose",
                        latency_ms=decompose_ms,
                        candidate_count=len(decomposed.category_ids),
                        details={
                            "is_complex": decomposed.is_complex,
                            "category_ids": decomposed.category_ids[:3],
                            "category_names": decomposed.category_names[:3],
                            "category_confidence": round(decomposed.category_confidence, 3),
                            "nature_filter": decomposed.nature_filter,
                            "has_time_filter": bool(decomposed.time_filter),
                            "has_entity_filter": bool(decomposed.entity_filter),
                            "domain_hint": decomposed.domain_hint,
                            "extract_type": decomposed.extract_type,
                        },
                    )
                )

                # Apply decomposed category_ids if request doesn't already have them
                if decomposed.category_ids and not request.category_ids:
                    request.category_ids = [UUID(cid) for cid in decomposed.category_ids]

                log.info(
                    "query_decomposed",
                    is_complex=decomposed.is_complex,
                    category_count=len(decomposed.category_ids),
                    confidence=round(decomposed.category_confidence, 3),
                    latency_ms=decompose_ms,
                )
            except Exception:
                log.debug("query_decompose_skipped", exc_info=True)

        # Step 0b: 쿼리 의도 분석 (auto_intent=True일 때)
        if request.auto_intent:
            try:
                from src.search.intent_analyzer import IntentAnalyzer

                analyzer = IntentAnalyzer(
                    repositories=await self._get_repo_list(tenant_slug),
                )
                intent_start = time.monotonic()
                intent = await analyzer.analyze(request.query)
                intent_ms = int((time.monotonic() - intent_start) * 1000)

                trace.steps.append(
                    SearchTraceStep(
                        step_name="intent_analysis",
                        latency_ms=intent_ms,
                        candidate_count=0,
                        details={
                            "domain": intent.domain,
                            "answer_type": intent.answer_type,
                            "time_filter": intent.time_filter,
                            "document_hint": intent.document_hint,
                            "confidence": intent.confidence,
                            "suggested_repos": len(intent.suggested_repository_ids),
                        },
                    )
                )

                # 의도에 따라 검색 파라미터 자동 조정
                if intent.suggested_block_types and not request.block_types:
                    request.block_types = intent.suggested_block_types
                if intent.suggested_repository_ids and not request.repository_ids:
                    request.repository_ids = [
                        UUID(rid) for rid in intent.suggested_repository_ids
                    ]
                if intent.time_filter and not request.time_filter:
                    request.time_filter = intent.time_filter
                if intent.document_hint and not request.document_type_hint:
                    request.document_type_hint = intent.document_hint

                log.info(
                    "intent_applied",
                    confidence=intent.confidence,
                    domain=intent.domain,
                    answer_type=intent.answer_type,
                    latency_ms=intent_ms,
                )
            except Exception:
                log.debug("intent_analysis_skipped", exc_info=True)

        # UUID 리스트를 문자열로 변환 (필터용)
        category_ids_str = [str(c) for c in request.category_ids] if request.category_ids else None
        doc_type_ids_str = (
            [str(d) for d in request.document_type_ids] if request.document_type_ids else None
        )

        # 1. 질의 전처리 (tenant_id가 있으면 동의어 확장 적용)
        processed, preprocess_trace = await self._preprocessor.preprocess(
            request.query, tenant_id=request.tenant_id
        )
        trace.steps.append(preprocess_trace)

        # 1.5 LLM 쿼리 리라이팅 (활성화된 경우)
        if self._query_rewriter is not None:
            try:
                from src.search.query_rewriter import QueryRewriter

                if isinstance(self._query_rewriter, QueryRewriter):
                    processed, rewrite_trace = await self._query_rewriter.rewrite(
                        request.query, processed
                    )
                    trace.steps.append(rewrite_trace)
            except Exception:
                log.warning("query_rewrite_step_failed", exc_info=True)

        # 1.7 + 2. HyDE 쿼리 확장 + 쿼리 임베딩 병렬 실행
        #   HyDE (vLLM HTTP) 와 쿼리 임베딩 (BGE-M3) 은 서로 독립이라
        #   asyncio.gather 로 동시에 시작해 HyDE 의 LLM latency 를 숨긴다.
        hyde_start = time.monotonic()
        embed_start = hyde_start

        hyde_task: asyncio.Task | None = None
        if request.use_hyde and self._query_expander is not None:
            hyde_task = asyncio.create_task(
                self._query_expander.expand(request.query)
            )

        query_embed_task = asyncio.create_task(
            self._get_embeddings(processed.for_dense)
        )

        expanded_query = None
        if hyde_task is not None:
            try:
                expanded_query = await hyde_task
                hyde_ms = int((time.monotonic() - hyde_start) * 1000)
                trace.steps.append(
                    SearchTraceStep(
                        step_name="hyde_expansion",
                        latency_ms=hyde_ms,
                        candidate_count=0,
                        details={
                            "hyde_doc_len": len(expanded_query.hyde_document),
                            "keyword_count": len(expanded_query.expanded_keywords),
                        },
                    )
                )
            except Exception:
                log.warning("hyde_expansion_failed", exc_info=True)

        dense_vector, sparse_vector = await query_embed_task

        # 가중 컨텍스트 융합 (2026-06-16) — 현재 발화 dense 벡터에 이전 맥락 벡터 저가중 결합.
        # sparse_vector 는 현재 발화 그대로(이전 어휘 오염 차단). reformulate 미사용 경로 전용.
        if request.context_weighted and request.conversation_history:
            ctx_text = build_context_text(request.conversation_history)
            if ctx_text:
                try:
                    ctx_dense, _ = await self._get_embeddings(ctx_text)
                    dense_vector = combine_dense_vectors(
                        dense_vector, ctx_dense, request.w_c, request.w_p
                    )
                except Exception:  # noqa: BLE001 — 컨텍스트 임베딩 실패는 현재발화 단독으로 진행
                    log.warning("context_embed_failed_primary_only")

        # HyDE 임베딩은 HyDE 결과가 준비된 뒤에야 가능 (의존성 존재)
        hyde_dense_vector = None
        if expanded_query and expanded_query.hyde_document:
            try:
                hyde_dense_vector, _ = await self._get_embeddings(
                    expanded_query.hyde_document
                )
            except Exception:
                log.warning("hyde_embedding_failed", exc_info=True)

        embed_ms = int((time.monotonic() - embed_start) * 1000)
        trace.steps.append(
            SearchTraceStep(
                step_name="embedding",
                latency_ms=embed_ms,
                candidate_count=0,
                details={
                    "dense_dim": len(dense_vector),
                    "sparse_dim": len(sparse_vector),
                    "hyde_embedding": hyde_dense_vector is not None,
                },
            )
        )

        candidate_pool_size = config.candidate_pool_size

        # 3. 병렬 검색 실행 (모드에 따라 선택)
        # 온톨로지 필터 병합: request-level + decomposed (QueryDecomposer에서 추출)
        effective_nature = request.nature_filter
        effective_entity = request.entity_filter
        effective_validity = request.validity_filter
        effective_document_status = request.document_status_filter
        if decomposed is not None:
            if decomposed.nature_filter and not effective_nature:
                effective_nature = decomposed.nature_filter
            if decomposed.entity_filter and not effective_entity:
                effective_entity = decomposed.entity_filter

        search_results: dict[str, list[SearchHit]] = {}
        search_traces: list[SearchTraceStep] = []

        # cross-industry leak fix (KMS-Plus, 2026-05-07) — dense/sparse 도 ES와
        # 동일한 repository_ids 필터를 적용. 이전엔 keyword 만 적용해 dense 경로로
        # 다른 산업(repo) chunk 가 누출됨. role agent 의 knowledge_isolation=strict
        # 동작 보장.
        repo_ids_str: list[str] | None = (
            [str(r) for r in request.repository_ids] if request.repository_ids else None
        )

        # D33 §2 — caller_tenant_slug / rls_scope / allow_cross_namespace inject.
        # 사전 GPT-5 §2 patch: scope 미존재 시 빈 문자열 (default-deny). "agent"
        # 위장 차단. allow_cross_namespace=False — 운영 path 는 cross-tenant 차단.
        # 호출 site 0 누락 보장 (4 site 모두 동일 인자 propagate).
        from src.api.middleware.rls_context import get_rls_context as _get_rls_ctx
        _rls_ctx = _get_rls_ctx()
        _rls_scope_str = (_rls_ctx.scope if _rls_ctx else "") or ""
        _caller_slug = tenant_slug

        # Lucas-KMS Phase 2 T2.5 — payload-level tenant_id filter (이중 안전망).
        # request.tenant_id 가 있으면 must filter 에 추가. 없을 시 None (legacy 호환).
        _tenant_id_str = str(request.tenant_id) if request.tenant_id else None

        # 대화-컨텍스트 상품 앵커링 (resolve-then-scope, 2026-06-23) — USER턴 이력을
        # ES document_title 매칭으로 앵커 문서로 해석해 3개 searcher 에 document_ids 스코프.
        # conversation_history 없음 / 비활성 / 해석실패 / 앵커없음 → anchor_doc_ids=[] (무회귀).
        # _disable_anchor 는 0건 폴백 재실행에서만 True (unscoped 재시도, 중복해석 방지).
        anchor_doc_ids: list[str] = []
        # 부정 패턴 안전망: reformulate가 "X 말고/아니고/아니라/빼고"를 처리했으면
        # 해당 토큰이 쿼리에 남아있지 않다. 남아있다면 제외 대상이 ES title match로
        # 앵커되는 것을 방지하기 위해 앵커링을 건너뛴다(unscoped 검색이 오스코프보다 안전).
        _neg_tokens = ("말고", "아니고", "아니라", "빼고")
        _q = request.query or ""
        if not _disable_anchor and any(t in _q for t in _neg_tokens):
            _disable_anchor = True
            log.info("anchor_skipped_negation_unresolved", query=_q[:120])
        if (
            not _disable_anchor
            and settings.CONTEXT_ANCHOR_ENABLED
            and request.conversation_history
        ):
            try:
                anchor_doc_ids = await self._resolve_anchor_doc_ids(
                    request, es_index_name, repo_ids_str, _tenant_id_str
                )
            except Exception:  # noqa: BLE001 — 앵커 해석 실패는 unscoped 로 진행(무회귀)
                log.warning("context_anchor_resolve_failed", exc_info=True)
                anchor_doc_ids = []
            if anchor_doc_ids:
                log.info(
                    "context_anchor_resolved",
                    doc_ids=anchor_doc_ids,
                    query=(request.query or "")[:120],
                )

        if request.search_mode in ("hybrid", "dense"):
            dense_task = self._dense_searcher.search(
                query_vector=dense_vector,
                collection_name=collection_name,
                top_k=candidate_pool_size,
                category_ids=category_ids_str,
                document_type_ids=doc_type_ids_str,
                score_threshold=config.min_score_threshold,
                repository_ids=repo_ids_str,
                block_types=request.block_types,
                time_filter=request.time_filter,
                document_type_hint=request.document_type_hint,
                nature_filter=effective_nature,
                validity_filter=effective_validity,
                entity_filter=effective_entity,
                document_status_filter=effective_document_status,
                caller_tenant_slug=_caller_slug,
                rls_scope=_rls_scope_str,
                allow_cross_namespace=False,
                tenant_id=_tenant_id_str,
                document_ids=anchor_doc_ids or None,
            )
        else:
            dense_task = None

        # HyDE dense 검색 (가상 답변 임베딩으로 추가 검색)
        if hyde_dense_vector is not None and request.search_mode in ("hybrid", "dense"):
            hyde_dense_task = self._dense_searcher.search(
                query_vector=hyde_dense_vector,
                collection_name=collection_name,
                top_k=candidate_pool_size,
                category_ids=category_ids_str,
                document_type_ids=doc_type_ids_str,
                score_threshold=config.min_score_threshold,
                repository_ids=repo_ids_str,
                block_types=request.block_types,
                time_filter=request.time_filter,
                document_type_hint=request.document_type_hint,
                nature_filter=effective_nature,
                validity_filter=effective_validity,
                entity_filter=effective_entity,
                document_status_filter=effective_document_status,
                caller_tenant_slug=_caller_slug,
                rls_scope=_rls_scope_str,
                allow_cross_namespace=False,
                tenant_id=_tenant_id_str,
                document_ids=anchor_doc_ids or None,
            )
        else:
            hyde_dense_task = None

        if request.search_mode in ("hybrid", "sparse"):
            sparse_task = self._sparse_searcher.search(
                sparse_vector=sparse_vector,
                collection_name=collection_name,
                top_k=candidate_pool_size,
                category_ids=category_ids_str,
                document_type_ids=doc_type_ids_str,
                repository_ids=repo_ids_str,
                block_types=request.block_types,
                nature_filter=effective_nature,
                validity_filter=effective_validity,
                entity_filter=effective_entity,
                document_status_filter=effective_document_status,
                caller_tenant_slug=_caller_slug,
                rls_scope=_rls_scope_str,
                allow_cross_namespace=False,
                tenant_id=_tenant_id_str,
                document_ids=anchor_doc_ids or None,
            )
        else:
            sparse_task = None

        if request.search_mode in ("hybrid", "keyword"):
            keyword_task = self._keyword_searcher.search(
                keywords=processed.for_keyword,
                index_name=es_index_name,
                top_k=candidate_pool_size,
                category_ids=category_ids_str,
                document_type_ids=doc_type_ids_str,
                block_types=request.block_types,
                repository_ids=repo_ids_str,
                nature_filter=effective_nature,
                validity_filter=effective_validity,
                entity_filter=effective_entity,
                document_status_filter=effective_document_status,
                caller_tenant_slug=_caller_slug,
                rls_scope=_rls_scope_str,
                allow_cross_namespace=False,
                # Lucas-KMS Phase 2 T2.6 — ES payload tenant_id must filter (이중 안전망).
                tenant_id=_tenant_id_str,
                document_ids=anchor_doc_ids or None,
            )
        else:
            keyword_task = None

        # 병렬 실행
        tasks = [
            t for t in [dense_task, sparse_task, keyword_task, hyde_dense_task] if t is not None
        ]
        task_labels = []
        if dense_task:
            task_labels.append("dense")
        if sparse_task:
            task_labels.append("sparse")
        if keyword_task:
            task_labels.append("keyword")
        if hyde_dense_task:
            task_labels.append("hyde_dense")

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for label, result in zip(task_labels, results_list):
            if isinstance(result, Exception):
                log.warning("search_source_failed", source=label, error=str(result))
                search_results[label] = []
                search_traces.append(
                    SearchTraceStep(
                        step_name=f"{label}_search",
                        latency_ms=0,
                        candidate_count=0,
                        details={"error": str(result)},
                    )
                )
            else:
                hits, step_trace = result
                search_results[label] = hits
                search_traces.append(step_trace)
                # 단계별 레이턴시 Prometheus 메트릭 기록
                observe_search_duration(label, step_trace.latency_ms / 1000.0)

        for st in search_traces:
            trace.steps.append(st)

        # 3.5 HyDE 결과를 dense 결과에 병합 (중복 제거)
        if "hyde_dense" in search_results and "dense" in search_results:
            existing_ids = {h.chunk_id for h in search_results["dense"]}
            for hit in search_results["hyde_dense"]:
                if hit.chunk_id not in existing_ids:
                    search_results["dense"].append(hit)
                    existing_ids.add(hit.chunk_id)
            del search_results["hyde_dense"]
        elif "hyde_dense" in search_results:
            # dense 결과가 없으면 hyde 결과를 dense로 사용
            search_results["dense"] = search_results.pop("hyde_dense")

        # 4. 스코어 통합
        if request.search_mode == "hybrid" and len(search_results) > 1:
            # RRF Fusion
            api_weights = None
            if request.weights:
                api_weights = {}
                if request.weights.dense is not None:
                    api_weights["dense"] = request.weights.dense
                if request.weights.sparse is not None:
                    api_weights["sparse"] = request.weights.sparse
                if request.weights.keyword is not None:
                    api_weights["keyword"] = request.weights.keyword

            fusion_start = time.monotonic()
            fused, fusion_trace = self._fusion.fuse(
                search_results=search_results,
                weights=api_weights if api_weights else None,
                config=config,
            )
            observe_search_duration("fusion", time.monotonic() - fusion_start)
            trace.steps.append(fusion_trace)
        elif len(search_results) == 1:
            # 단일 소스
            fused = list(search_results.values())[0]
        else:
            fused = []

        # 빈 헤딩 블럭(제목만, 본문 없음) 제외 — rerank/top_k 선별 전 후보 풀에서 제거해
        # 다음 본문 블럭이 슬롯을 채우게 한다(정답 표가 빈 헤딩에 밀려 top-k 밖으로 나가던 문제).
        if fused:
            fused = _drop_empty_heading_hits(fused)

        # 5. Reranking
        if request.rerank and config.rerank_enabled and fused:
            rerank_start = time.monotonic()
            reranked, rerank_trace = await self._reranker.rerank(
                query=processed.cleaned,
                candidates=fused[:candidate_pool_size],
                top_k=request.top_k,
            )
            rerank_elapsed = time.monotonic() - rerank_start
            observe_search_duration("rerank", rerank_elapsed)
            record_reranker_call()
            trace.steps.append(rerank_trace)
            final_results = reranked
        else:
            final_results = fused[: request.top_k]

        # 6. MMR 다양성 리랭킹 (선택적)
        if request.use_mmr and final_results:
            mmr_start = time.monotonic()
            final_results = mmr_rerank(
                results=final_results,
                lambda_param=request.mmr_lambda,
                top_k=request.top_k,
                max_per_document=request.mmr_max_per_document,
            )
            mmr_ms = int((time.monotonic() - mmr_start) * 1000)
            trace.steps.append(
                SearchTraceStep(
                    step_name="mmr_rerank",
                    latency_ms=mmr_ms,
                    candidate_count=len(final_results),
                    details={
                        "lambda": request.mmr_lambda,
                        "max_per_document": request.mmr_max_per_document,
                    },
                )
            )

        # 7. LLM 리랭킹 (BGE 이후 정밀 재평가, 선택적)
        if request.enable_llm_rerank and self._llm_reranker is not None and final_results:
            try:
                from src.search.llm_reranker import LLMReranker

                if isinstance(self._llm_reranker, LLMReranker):
                    final_results, llm_rerank_trace = await self._llm_reranker.rerank(
                        query=processed.cleaned,
                        candidates=final_results,
                        top_k=request.top_k,
                    )
                    trace.steps.append(llm_rerank_trace)
            except Exception:
                log.warning("llm_rerank_step_failed", exc_info=True)

        # 8. 저장소별 Top-N 그룹핑 (선택적)
        if request.group_by_repository and final_results:
            final_results = self._group_by_repository(
                final_results, request.results_per_repository
            )

        # 9. 결과 충분성 평가 + 재검색 (선택적, max 1 retry)
        if (
            request.enable_sufficiency_check
            and self._sufficiency_evaluator is not None
            and final_results
        ):
            try:
                from src.search.sufficiency_evaluator import SufficiencyEvaluator

                if isinstance(self._sufficiency_evaluator, SufficiencyEvaluator):
                    suff_result = await self._sufficiency_evaluator.evaluate(
                        query=request.query,
                        results=final_results,
                    )
                    trace.steps.append(
                        SearchTraceStep(
                            step_name="sufficiency_check",
                            latency_ms=suff_result.latency_ms,
                            candidate_count=len(final_results),
                            details={
                                "sufficient": suff_result.sufficient,
                                "confidence": round(suff_result.confidence, 3),
                                "missing": suff_result.missing[:200],
                                "suggested_query": suff_result.suggested_query[:200],
                            },
                        )
                    )

                    # 불충분 + 재검색 쿼리가 있으면 1회 재시도
                    if (
                        not suff_result.sufficient
                        and suff_result.suggested_query
                        and suff_result.suggested_query != request.query
                    ):
                        log.info(
                            "sufficiency_retry",
                            original_query=request.query[:100],
                            suggested_query=suff_result.suggested_query[:100],
                        )
                        import copy

                        retry_request = copy.deepcopy(request)
                        retry_request.query = suff_result.suggested_query
                        retry_request.enable_sufficiency_check = False  # 재귀 방지

                        retry_results, retry_trace, retry_latency, _, _ = (
                            await self._execute_pipeline(
                                request=retry_request,
                                tenant_slug=tenant_slug,
                                tenant_config=tenant_config,
                                repo_config=repo_config,
                            )
                        )

                        if retry_results:
                            # 원본 + 재검색 결과 병합 (중복 제거)
                            existing_ids = {h.chunk_id for h in final_results}
                            for hit in retry_results:
                                if hit.chunk_id not in existing_ids:
                                    final_results.append(hit)
                                    existing_ids.add(hit.chunk_id)

                            # 스코어 기준 재정렬 + top_k 자르기
                            final_results.sort(
                                key=lambda x: x.rerank_score or x.fused_score or 0.0,
                                reverse=True,
                            )
                            final_results = final_results[: request.top_k]

                            trace.steps.append(
                                SearchTraceStep(
                                    step_name="sufficiency_retry",
                                    latency_ms=retry_latency,
                                    candidate_count=len(retry_results),
                                    details={
                                        "retry_query": suff_result.suggested_query[:200],
                                        "new_results_merged": len(retry_results),
                                    },
                                )
                            )
            except Exception:
                log.warning("sufficiency_check_step_failed", exc_info=True)

        # 노이즈 블럭 방어선 — demote 시 인덱스에서 빠지지 않은 경우 최종 후필터.
        final_results = await self._filter_noise_hits(final_results)

        # 컨텍스트 앵커 폴백 (오앵커 방어) — 앵커 스코프를 적용했는데 결과가
        # ANCHOR_FALLBACK_MIN 미만이면 동일 검색을 앵커 없이(unscoped) 1회 재실행.
        # _disable_anchor=True 로 resolve 블럭을 건너뛰므로 중복 해석/무한 재귀 없음.
        # 앵커 미적용 경로는 이 분기에 진입하지 않아 기존 동작과 동일(무회귀).
        if anchor_doc_ids and len(final_results) < settings.ANCHOR_FALLBACK_MIN:
            log.info("context_anchor_fallback_unscoped", anchor=anchor_doc_ids)
            return await self._execute_pipeline(
                request=request,
                tenant_slug=tenant_slug,
                tenant_config=tenant_config,
                repo_config=repo_config,
                _disable_anchor=True,
            )

        total_latency = int((time.monotonic() - pipeline_start) * 1000)
        trace.total_latency_ms = total_latency

        log.info(
            "search_pipeline_completed",
            query=request.query[:100],
            mode=request.search_mode,
            result_count=len(final_results),
            total_latency_ms=total_latency,
        )

        # Build decomposed dict for API response
        decomposed_dict: dict | None = None
        if decomposed is not None:
            decomposed_dict = {
                "is_complex": decomposed.is_complex,
                "category_names": decomposed.category_names,
                "nature_filter": decomposed.nature_filter,
                "time_filter": decomposed.time_filter if decomposed.time_filter else None,
                "entity_filter": decomposed.entity_filter if decomposed.entity_filter else None,
                "domain_hint": decomposed.domain_hint or None,
            }

        analysis: QueryAnalysis = {
            "rewritten_query": effective_query,
            "keywords": list(processed.keywords) if processed else [],
        }
        return final_results, trace, total_latency, decomposed_dict, analysis

    async def _search_with_fallback(
        self,
        request: SearchRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> tuple[list[SearchHit], SearchTrace, int, int, dict | None, QueryAnalysis]:
        """4단계 폴백 전략으로 검색한다.

        Level 1: 모든 필터 적용 (category + nature + time + entity + validity)
        Level 2: category만 유지 (nature/time/entity 제거)
        Level 3: Repository 전체 (category도 제거)
        Level 4: Tenant 전체 (repository 제한도 제거)

        Returns:
            (results, trace, total_latency_ms, fallback_level, decomposed_dict)
        """
        min_score = 0.005  # RRF 정규화 스코어 기준 (0.01 이상이면 유의미)
        min_results = 1

        results: list[SearchHit] = []
        trace = SearchTrace()
        total_latency = 0
        decomposed_dict: dict | None = None
        analysis: QueryAnalysis = {"rewritten_query": request.query, "keywords": []}

        for level in range(1, 5):
            req = self._relax_filters(request, level)

            results, trace, total_latency, decomposed_dict, analysis = await self._execute_with_split(
                request=req,
                tenant_slug=tenant_slug,
                tenant_config=tenant_config,
                repo_config=repo_config,
            )

            # 결과 품질 평가
            if len(results) >= min_results:
                top_n = min(5, len(results))
                avg_score = sum(h.fused_score or 0 for h in results[:top_n]) / top_n
                if avg_score >= min_score:
                    if level > 1:
                        for hit in results:
                            hit.metadata = hit.metadata or {}
                            hit.metadata["fallback_level"] = level
                    return results, trace, total_latency, level, decomposed_dict, analysis

            log.info(
                "search_fallback",
                level=level,
                results=len(results),
                query=request.query[:100],
            )

        return results, trace, total_latency, 4, decomposed_dict, analysis

    @staticmethod
    def _relax_filters(request: SearchRequest, level: int) -> SearchRequest:
        """폴백 레벨에 따라 필터를 완화한다."""
        import copy

        req = copy.deepcopy(request)

        if level >= 2:
            # nature, time, entity 제거
            req.nature_filter = None
            req.time_filter = ""
            req.entity_filter = None
            req.validity_filter = "all"
        if level >= 3:
            # block_types 만 완화. category_ids 는 권한 스코프(AICM viewable 분류)일 수 있어
            # 폴백으로도 완화하지 않는다 — repository hard guard 와 동일 사유(비허가 분류 누출 방지).
            req.block_types = None
        if level >= 4:
            # repository 제한 제거
            # cross-industry isolation hard guard (2026-05-07) — strict role
            # agent 는 fallback 으로도 다른 산업 repo 를 절대 못 봐야 함.
            if not getattr(request, "enforce_repository_ids", False):
                req.repository_ids = None
                req.repository_id = None

        return req

    @staticmethod
    def _group_by_repository(
        results: list[SearchHit], per_repo: int
    ) -> list[SearchHit]:
        """저장소별 Top-N으로 그룹핑한다.

        교차 저장소 검색 시 특정 저장소가 결과를 독점하지 않도록
        저장소별 최대 per_repo개로 제한한다.
        """
        repo_counts: dict[str, int] = {}
        grouped: list[SearchHit] = []
        for hit in results:
            repo_id = str(hit.repository_id) if hit.repository_id else "unknown"
            count = repo_counts.get(repo_id, 0)
            if count < per_repo:
                grouped.append(hit)
                repo_counts[repo_id] = count + 1
        return grouped

    @staticmethod
    def _to_result_items(
        hits: list[SearchHit],
        include_content: bool = True,
    ) -> list[SearchResultItem]:
        """SearchHit 리스트를 SearchResultItem 리스트로 변환."""
        items: list[SearchResultItem] = []
        for hit in hits:
            items.append(
                SearchResultItem(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    document_title=hit.document_title,
                    section_title=hit.section_title or _section_title_from_heading_path(hit.source_location),
                    content=hit.content if include_content else None,
                    highlighted_content=hit.metadata.get("highlighted_content"),
                    score=hit.score,
                    category_names=hit.category_names,
                    document_type=hit.document_type,
                    source_location=hit.source_location,
                    metadata=hit.metadata,
                    block_id=hit.block_id,
                    block_type=hit.block_type,
                    block_index=hit.block_index,
                    repository_id=hit.repository_id,
                )
            )
        return items

    def _fire_search_webhook_events(
        self,
        tenant_id: UUID,
        query: str,
        result_count: int,
        top_score: float,
    ) -> None:
        """검색 결과에 따라 webhook 이벤트를 fire-and-forget으로 발행."""
        webhook_cls = _get_webhook_dispatcher()
        if webhook_cls is None or self._webhook_session is None:
            return

        events_to_fire: list[tuple[str, dict]] = []

        if result_count == 0:
            events_to_fire.append((
                "search.no_result",
                {"query": query, "result_count": 0},
            ))

        if result_count > 0 and top_score < 0.3:
            events_to_fire.append((
                "search.low_confidence",
                {"query": query, "top_score": round(top_score, 4), "result_count": result_count},
            ))

        if not events_to_fire:
            return

        try:
            dispatcher = webhook_cls(session=self._webhook_session)
            loop = asyncio.get_running_loop()
            for event_type, payload in events_to_fire:
                loop.create_task(
                    dispatcher.dispatch(
                        event_type=event_type,
                        tenant_id=tenant_id,
                        payload=payload,
                    )
                )
                log.info(
                    "search_webhook_fired",
                    event_type=event_type,
                    query=query[:100],
                )
        except RuntimeError:
            log.warning("search_webhook_no_event_loop")
        except Exception:
            log.warning("search_webhook_fire_failed", exc_info=True)

    # ------------------------------------------------------------------
    # 저장소 목록 조회 (의도 분석용)
    # ------------------------------------------------------------------
    async def _get_repo_list(self, tenant_slug: str) -> list[dict]:
        """테넌트의 저장소 목록을 조회한다 (의도 분석기에 전달용).

        DB 조회가 실패하면 빈 리스트를 반환하여 규칙 기반 분석만 수행한다.
        """
        try:
            from src.core.models.repository import Repository
            from src.core.models.tenant import Tenant
            from src.core.database import async_session_factory as get_async_session
            from sqlalchemy import select

            async with get_async_session() as session:  # noqa: E501 — async_session_factory
                # 테넌트 ID 조회
                tenant_result = await session.execute(
                    select(Tenant).where(Tenant.slug == tenant_slug)
                )
                tenant = tenant_result.scalar_one_or_none()
                if not tenant:
                    return []

                # 저장소 목록 조회
                repo_result = await session.execute(
                    select(Repository).where(Repository.tenant_id == tenant.id)
                )
                repos = repo_result.scalars().all()
                return [
                    {
                        "id": str(r.id),
                        "name": r.name,
                        "description": getattr(r, "description", "") or "",
                    }
                    for r in repos
                ]
        except Exception:
            log.debug("repo_list_fetch_for_intent_failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # 카테고리 임베딩 로드 (QueryDecomposer용)
    # ------------------------------------------------------------------
    async def _get_category_embeddings(self, tenant_slug: str) -> list[dict]:
        """테넌트의 카테고리 임베딩 목록을 조회한다 (QueryDecomposer Stage 1용).

        categories.embedding JSONB 컬럼에서 임베딩을 로드한다.
        DB 조회가 실패하면 빈 리스트를 반환하여 Stage 1을 건너뛴다.
        """
        try:
            from src.core.database import async_session_factory as get_async_session
            from src.core.models.category import Category
            from src.core.models.tenant import Tenant
            from sqlalchemy import select

            async with get_async_session() as session:  # noqa: E501 — async_session_factory
                tenant_result = await session.execute(
                    select(Tenant).where(Tenant.slug == tenant_slug)
                )
                tenant = tenant_result.scalar_one_or_none()
                if not tenant:
                    return []

                cat_result = await session.execute(
                    select(Category).where(Category.tenant_id == tenant.id)
                )
                categories = cat_result.scalars().all()
                result = []
                for cat in categories:
                    embedding = getattr(cat, "embedding", None)
                    if embedding and isinstance(embedding, list):
                        result.append({
                            "id": str(cat.id),
                            "name": cat.name,
                            "embedding": embedding,
                        })
                return result
        except Exception:
            log.debug("category_embeddings_fetch_failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # 인접 블럭 확장 (교차 참조 대응)
    # ------------------------------------------------------------------
    async def _expand_adjacent_blocks(
        self,
        hits: list[SearchHit],
        tenant_slug: str,
        expand_range: int = 2,
    ) -> list[SearchHit]:
        """검색된 블럭의 인접 블럭(전후 N개)을 자동 포함한다.

        하드웨어 매뉴얼처럼 p.23 구성표 + p.24~ 상세 설명이 분리된 경우,
        하나의 블럭만 검색되면 답변 불충분.
        → 같은 문서의 인접 블럭을 확장 포함하여 RAG 컨텍스트를 보강한다.
        """
        if not hits:
            return hits

        try:
            collection = build_collection_name(tenant_slug)
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import FieldCondition, Filter, MatchValue, Range

            client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=getattr(settings, "QDRANT_API_KEY", None) or None,
                timeout=5,
            )

            expanded: list[SearchHit] = []
            seen_ids: set[str] = set()

            for hit in hits:
                # 원본 블럭 추가
                hit_id = str(hit.block_id or hit.chunk_id or "")
                if hit_id not in seen_ids:
                    expanded.append(hit)
                    seen_ids.add(hit_id)

                # 인접 블럭 검색: 같은 document_id + block_index ±expand_range
                if not hit.document_id or hit.block_index is None:
                    continue

                try:
                    adjacent, _ = client.scroll(
                        collection_name=collection,
                        scroll_filter=Filter(
                            must=[
                                FieldCondition(
                                    key="document_id",
                                    match=MatchValue(value=str(hit.document_id)),
                                ),
                                FieldCondition(
                                    key="block_index",
                                    range=Range(
                                        gte=hit.block_index - expand_range,
                                        lte=hit.block_index + expand_range,
                                    ),
                                ),
                            ]
                        ),
                        limit=expand_range * 2 + 1,
                        with_payload=True,
                        with_vectors=False,
                    )

                    for point in adjacent:
                        pid = str(point.id)
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)

                        payload = point.payload or {}
                        adj_hit = SearchHit(
                            content=payload.get("content", ""),
                            document_id=payload.get("document_id"),
                            block_id=pid,
                            block_type=payload.get("block_type"),
                            block_index=payload.get("block_index"),
                            repository_id=payload.get("repository_id"),
                            dense_score=0.0,
                            fused_score=(hit.fused_score or 0) * 0.5,  # 인접 블럭은 원본의 50% 점수
                            metadata=payload.get("metadata", {}),
                        )
                        expanded.append(adj_hit)
                except Exception as adj_exc:
                    log.debug("adjacent_block_fetch_failed", error=str(adj_exc))

            # 점수순 재정렬
            expanded.sort(key=lambda h: h.fused_score or 0, reverse=True)

            if len(expanded) > len(hits):
                log.info(
                    "adjacent_blocks_expanded",
                    original=len(hits),
                    expanded=len(expanded),
                )

            return expanded

        except Exception as exc:
            log.warning("adjacent_expansion_failed", error=str(exc))
            return hits
