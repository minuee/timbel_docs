"""SearchService 팩토리 — LLM 기반 쿼리 강화 기능 포함 초기화.

QueryExpander (HyDE), QueryDecomposer (2단계 쿼리 분해),
LLMQueryRewriter (오타교정/동의어/대화재구성),
LLMReranker (LLM 리랭킹), SufficiencyEvaluator (결과 충분성)를
LLM 클라이언트와 함께 초기화하여 SearchService에 주입한다.

profile="assist" 지정 시 ASSIST_* env 로 별도 B200 을 사용하는
SearchService 인스턴스를 생성한다 (GPU 부하 분리).
"""

from __future__ import annotations

import asyncio

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

_cached_services: dict[str, object] = {}
_init_lock = asyncio.Lock()


async def create_search_service(profile: str = "default") -> object:
    """LLM 강화 기능이 활성화된 SearchService를 생성한다.

    싱글턴 패턴: 프로파일별로 최초 호출 시 생성, 이후 캐시된 인스턴스 반환.
    profile="assist" 이고 ASSIST_* env 가 설정돼 있으면 별도 B200 URL 을 사용한다.
    """
    if profile in _cached_services:
        return _cached_services[profile]

    async with _init_lock:
        if profile in _cached_services:
            return _cached_services[profile]

        from src.search.embedding_proxy import EmbeddingProxyClient, create_embedding_fn
        from src.search.service import SearchService

        # --- URL 결정 (assist 프로파일이면 전용 env, 없으면 기본) ---
        _assist = profile == "assist"
        embed_url = (settings.ASSIST_EMBEDDING_PROXY_URL if _assist else "") or ""
        reranker_url = (settings.ASSIST_RERANKER_URL if _assist else "") or ""
        vllm_url = (settings.ASSIST_VLLM_URL if _assist else "") or settings.VLLM_URL

        if _assist and embed_url:
            log.info("assist_profile_embedding", url=embed_url)

        # --- Embedding ---
        if embed_url:
            _client = EmbeddingProxyClient(proxy_url=embed_url)

            async def _embed(text: str, *, _c=_client) -> tuple[list[float], dict[int, float]]:
                return await _c.embed(text)

            _embed._proxy_client = _client  # type: ignore[attr-defined]
            embedding_fn = _embed
        else:
            embedding_fn = create_embedding_fn()

        # --- LLM 클라이언트 초기화 ---
        llm_client = None
        try:
            if vllm_url:
                from openai import AsyncOpenAI

                llm_client = AsyncOpenAI(
                    base_url=vllm_url,
                    api_key=getattr(settings, "VLLM_API_KEY", "") or "not-needed",
                    timeout=120.0,
                )
                log.info("search_llm_initialized", provider="vllm", url=vllm_url, profile=profile)
        except Exception as exc:
            log.warning("search_llm_init_failed", error=str(exc))

        vllm_model = (
            (settings.ASSIST_VLLM_MODEL if _assist else "") or
            getattr(settings, "VLLM_MODEL", "gemma-4-31b")
        )

        # QueryExpander (HyDE)
        query_expander = None
        if llm_client is not None:
            try:
                from src.search.query_expander import QueryExpander

                class _LLMAdapter:
                    """AsyncOpenAI → QueryExpander.generate() 어댑터."""

                    def __init__(self, client: object) -> None:
                        self._client = client

                    async def generate(self, prompt: str) -> str:
                        resp = await self._client.chat.completions.create(  # type: ignore[union-attr]
                            model=vllm_model,
                            messages=[{"role": "user", "content": prompt}],
                            max_tokens=80,
                            temperature=0.3,
                        )
                        import re
                        text = resp.choices[0].message.content or ""
                        return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

                query_expander = QueryExpander(llm_client=_LLMAdapter(llm_client))
                log.info("query_expander_initialized", hyde=True)
            except Exception as exc:
                log.warning("query_expander_init_failed", error=str(exc))

        # QueryDecomposer (2단계 쿼리 분해)
        query_decomposer = None
        if llm_client is not None:
            try:
                from src.search.query_decomposer import QueryDecomposer

                query_decomposer = QueryDecomposer(llm_client=llm_client, model=vllm_model)
                log.info("query_decomposer_initialized")
            except Exception as exc:
                log.warning("query_decomposer_init_failed", error=str(exc))

        # QuerySplitter (복합 의도 분리 → 서브쿼리 fan-out)
        query_splitter = None
        if llm_client is not None:
            try:
                from src.search.query_splitter import QuerySplitter

                query_splitter = QuerySplitter(
                    llm_client=llm_client,
                    model=vllm_model,
                )
                log.info("query_splitter_initialized")
            except Exception as exc:
                log.warning("query_splitter_init_failed", error=str(exc))

        # LLMQueryRewriter (오타 교정 + 동의어 확장 + 대화형 재구성)
        llm_query_rewriter = None
        if llm_client is not None:
            try:
                from src.search.llm_query_rewriter import LLMQueryRewriter

                llm_query_rewriter = LLMQueryRewriter(llm_client=llm_client)
                log.info("llm_query_rewriter_initialized")
            except Exception as exc:
                log.warning("llm_query_rewriter_init_failed", error=str(exc))

        # LLMReranker (LLM 기반 정밀 리랭킹)
        llm_reranker = None
        if llm_client is not None:
            try:
                from src.search.llm_reranker import LLMReranker

                llm_reranker = LLMReranker(llm_client=llm_client)
                log.info("llm_reranker_initialized")
            except Exception as exc:
                log.warning("llm_reranker_init_failed", error=str(exc))

        # SufficiencyEvaluator (결과 충분성 평가)
        sufficiency_evaluator = None
        if llm_client is not None:
            try:
                from src.search.sufficiency_evaluator import SufficiencyEvaluator

                sufficiency_evaluator = SufficiencyEvaluator(llm_client=llm_client)
                log.info("sufficiency_evaluator_initialized")
            except Exception as exc:
                log.warning("sufficiency_evaluator_init_failed", error=str(exc))

        # SynonymNormalizer
        synonym_normalizer = None
        if llm_client is not None:
            try:
                from src.search.synonym_normalizer import SynonymNormalizer

                class _SynLLMAdapter:
                    def __init__(self, client):
                        self._client = client

                    async def generate(self, prompt: str) -> str:
                        resp = await self._client.chat.completions.create(
                            model=vllm_model,
                            messages=[{"role": "user", "content": prompt}],
                            max_tokens=300,
                            temperature=0.1,
                            response_format={"type": "json_object"},
                        )
                        return resp.choices[0].message.content or ""

                synonym_normalizer = SynonymNormalizer(llm_client=_SynLLMAdapter(llm_client))
                log.info("synonym_normalizer_initialized")
            except Exception as exc:
                log.warning("synonym_normalizer_init_failed", error=str(exc))

        # --- Reranker (assist 프로파일 전용 URL) ---
        reranker = None
        if reranker_url:
            from src.search.reranker.cross_encoder import CrossEncoderReranker
            reranker = CrossEncoderReranker(remote_url=reranker_url)

        service = SearchService(
            embedding_fn=embedding_fn,
            query_expander=query_expander,
            query_decomposer=query_decomposer,
            llm_query_rewriter=llm_query_rewriter,
            llm_reranker=llm_reranker,
            sufficiency_evaluator=sufficiency_evaluator,
            synonym_normalizer=synonym_normalizer,
            query_splitter=query_splitter,
            reranker=reranker,
        )
        _cached_services[profile] = service
        log.info("search_service_created", profile=profile)
        return service
