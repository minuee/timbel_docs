"""검색 결과, LLM 응답 Redis 캐싱 및 캐시 워밍업/무효화.

주요 기능:
- SearchCache: 검색 결과 캐시 (repository 단위 무효화 + document 단위 무효화)
- LLMResponseCache: LLM 응답 캐시 (prompt_hash + model + max_tokens + temperature)
- cache_warmup: 인기 쿼리 기반 캐시 사전 적재
- 테넌트별 hit rate 추적
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis key prefixes
# ---------------------------------------------------------------------------
_TENANT_STATS_PREFIX = "aicm:cache_stats"  # 테넌트별 hit/miss 카운터
_DOC_CACHE_MAP_PREFIX = "aicm:search_cache:doc"  # doc_id -> {cache_keys} 매핑
_REPO_VERSION_PREFIX = "aicm:repo_version"  # repository 데이터 버전 카운터 (캐시 키에 포함)


class CacheStats(BaseModel):
    """캐시 통계."""

    hit_count: int = 0
    miss_count: int = 0

    @property
    def hit_rate(self) -> float:
        """캐시 적중률 (0.0 ~ 1.0)."""
        total = self.hit_count + self.miss_count
        if total == 0:
            return 0.0
        return self.hit_count / total


class SearchCache:
    """
    검색 결과 Redis 캐시.

    캐시 키: hash(query + repository_id + category_ids + weights + search_mode)
    TTL: 설정 가능 (기본 5분)
    무효화: 문서 인덱스/업데이트/삭제 시 해당 저장소 캐시 삭제
    """

    KEY_PREFIX = "aicm:search_cache"
    REPO_KEY_PREFIX = "aicm:search_cache:repo"

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        default_ttl: int = 300,
    ) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl
        self._stats = CacheStats()

    async def _get_redis(self) -> aioredis.Redis:
        """지연 초기화된 Redis 클라이언트 반환."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        return self._redis

    @staticmethod
    def _build_cache_key(
        query: str,
        repository_id: UUID,
        category_ids: list[UUID] | None = None,
        weights: dict[str, float] | None = None,
        search_mode: str = "hybrid",
        top_k: int = 5,
        rerank: bool = True,
        repo_version: int = 0,
        context_key: str = "",
    ) -> str:
        """캐시 키 생성. 검색 파라미터를 해싱하여 고유 키 생성.

        repo_version 을 키에 포함시켜 데이터 변경 시 자연스러운 무효화를 달성한다.
        repo_version 이 INCR 되면 같은 쿼리도 새 키가 생성되어 stale cache 가 도달 불가가 됨.
        """
        key_data = {
            "query": query,
            "repository_id": str(repository_id),
            "category_ids": sorted([str(c) for c in category_ids]) if category_ids else [],
            "weights": weights or {},
            "search_mode": search_mode,
            "top_k": top_k,
            "rerank": rerank,
            "v": repo_version,
            "ctx": context_key,
        }
        key_json = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        key_hash = hashlib.sha256(key_json.encode("utf-8")).hexdigest()
        return f"{SearchCache.KEY_PREFIX}:{key_hash}"

    @staticmethod
    def _build_repo_version_key(repository_id: UUID) -> str:
        return f"{_REPO_VERSION_PREFIX}:{repository_id}"

    async def get_repo_version(self, repository_id: UUID) -> int:
        """저장소의 현재 데이터 버전을 반환. 없으면 0."""
        try:
            redis = await self._get_redis()
            v = await redis.get(self._build_repo_version_key(repository_id))
            return int(v) if v is not None else 0
        except Exception:
            log.warning("repo_version_read_failed", exc_info=True)
            return 0

    async def bump_repo_version(self, repository_id: UUID) -> int:
        """저장소의 데이터 버전을 증가시켜 모든 기존 캐시를 자연 무효화한다.

        문서/블럭 추가·수정·삭제·재인덱스 시 호출. 비용은 INCR 한 번 (수 us).
        """
        try:
            redis = await self._get_redis()
            new_v = await redis.incr(self._build_repo_version_key(repository_id))
            log.info("repo_version_bumped", repository_id=str(repository_id), new_version=new_v)
            return int(new_v)
        except Exception:
            log.warning("repo_version_bump_failed", exc_info=True)
            return 0

    @staticmethod
    def _build_repo_set_key(repository_id: UUID) -> str:
        """저장소별 캐시 키 집합의 키 생성."""
        return f"{SearchCache.REPO_KEY_PREFIX}:{repository_id}"

    async def get(
        self,
        query: str,
        repository_id: UUID,
        category_ids: list[UUID] | None = None,
        weights: dict[str, float] | None = None,
        search_mode: str = "hybrid",
        top_k: int = 5,
        rerank: bool = True,
        tenant_id: UUID | None = None,
        context_key: str = "",
    ) -> dict[str, Any] | None:
        """캐시에서 검색 결과 조회. 캐시 히트 시 dict, 미스 시 None."""
        redis = await self._get_redis()
        repo_version = await self.get_repo_version(repository_id)
        cache_key = self._build_cache_key(
            query, repository_id, category_ids, weights, search_mode, top_k, rerank,
            repo_version=repo_version,
            context_key=context_key,
        )

        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                self._stats.hit_count += 1
                if tenant_id:
                    await self._track_tenant_hit(redis, tenant_id, hit=True)
                log.info("search_cache_hit", cache_key=cache_key[:32])
                return json.loads(cached)
            self._stats.miss_count += 1
            if tenant_id:
                await self._track_tenant_hit(redis, tenant_id, hit=False)
            log.debug("search_cache_miss", cache_key=cache_key[:32])
            return None
        except Exception:
            log.warning("search_cache_get_failed", exc_info=True)
            self._stats.miss_count += 1
            return None

    async def set(
        self,
        query: str,
        repository_id: UUID,
        data: dict[str, Any],
        category_ids: list[UUID] | None = None,
        weights: dict[str, float] | None = None,
        search_mode: str = "hybrid",
        top_k: int = 5,
        rerank: bool = True,
        ttl: int | None = None,
        context_key: str = "",
    ) -> None:
        """검색 결과를 캐시에 저장.

        결과에 포함된 document_id를 추출하여 역인덱스(doc -> cache_key)도 관리한다.
        """
        redis = await self._get_redis()
        repo_version = await self.get_repo_version(repository_id)
        cache_key = self._build_cache_key(
            query, repository_id, category_ids, weights, search_mode, top_k, rerank,
            repo_version=repo_version,
            context_key=context_key,
        )
        effective_ttl = ttl if ttl is not None else self._default_ttl

        try:
            serialized = json.dumps(data, ensure_ascii=False, default=str)
            await redis.set(cache_key, serialized, ex=effective_ttl)

            # 저장소별 캐시 키 집합에 추가 (무효화용)
            repo_set_key = self._build_repo_set_key(repository_id)
            await redis.sadd(repo_set_key, cache_key)
            # 집합 자체도 TTL 설정 (최대 1시간)
            await redis.expire(repo_set_key, max(effective_ttl, 3600))

            # 문서 ID 별 역인덱스 관리 (invalidate_for_document 지원)
            doc_ids = self._extract_document_ids(data)
            for doc_id in doc_ids:
                doc_set_key = f"{_DOC_CACHE_MAP_PREFIX}:{doc_id}"
                await redis.sadd(doc_set_key, cache_key)
                await redis.expire(doc_set_key, max(effective_ttl, 3600))

            log.debug("search_cache_set", cache_key=cache_key[:32], ttl=effective_ttl)
        except Exception:
            log.warning("search_cache_set_failed", exc_info=True)

    async def invalidate_repository(self, repository_id: UUID) -> int:
        """
        특정 저장소의 모든 검색 캐시 무효화.

        문서 인덱스/업데이트/삭제 시 호출.
        반환: 삭제된 캐시 키 수.
        """
        redis = await self._get_redis()
        repo_set_key = self._build_repo_set_key(repository_id)

        try:
            cache_keys = await redis.smembers(repo_set_key)
            if not cache_keys:
                return 0

            deleted = 0
            # 파이프라인으로 일괄 삭제
            pipe = redis.pipeline()
            for key in cache_keys:
                pipe.delete(key)
            pipe.delete(repo_set_key)
            results = await pipe.execute()
            deleted = sum(1 for r in results[:-1] if r)

            log.info(
                "search_cache_invalidated",
                repository_id=str(repository_id),
                deleted_keys=deleted,
            )
            return deleted
        except Exception:
            log.warning("search_cache_invalidation_failed", exc_info=True)
            return 0

    @property
    def stats(self) -> CacheStats:
        """현재 캐시 통계 반환."""
        return self._stats

    def reset_stats(self) -> None:
        """캐시 통계 초기화."""
        self._stats = CacheStats()

    # ------------------------------------------------------------------
    # 문서 단위 무효화
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_document_ids(data: dict[str, Any]) -> set[str]:
        """캐시 데이터에서 document_id 목록을 추출한다."""
        doc_ids: set[str] = set()
        results = data.get("results", [])
        for item in results:
            doc_id = item.get("document_id")
            if doc_id:
                doc_ids.add(str(doc_id))
        return doc_ids

    async def invalidate_for_document(self, document_id: UUID) -> int:
        """특정 문서가 포함된 모든 검색 캐시를 무효화한다.

        문서 업데이트/삭제 시 호출하여 stale 캐시를 제거한다.
        반환: 삭제된 캐시 키 수.
        """
        redis = await self._get_redis()
        doc_set_key = f"{_DOC_CACHE_MAP_PREFIX}:{document_id}"

        try:
            cache_keys = await redis.smembers(doc_set_key)
            if not cache_keys:
                return 0

            pipe = redis.pipeline()
            for key in cache_keys:
                pipe.delete(key)
            pipe.delete(doc_set_key)
            results = await pipe.execute()
            deleted = sum(1 for r in results[:-1] if r)

            log.info(
                "search_cache_doc_invalidated",
                document_id=str(document_id),
                deleted_keys=deleted,
            )
            return deleted
        except Exception:
            log.warning("search_cache_doc_invalidation_failed", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # 테넌트별 hit rate 추적 (Redis 카운터)
    # ------------------------------------------------------------------

    @staticmethod
    async def _track_tenant_hit(
        redis: aioredis.Redis, tenant_id: UUID, *, hit: bool
    ) -> None:
        """테넌트별 hit/miss 카운터를 Redis에 증가. 24시간 TTL."""
        suffix = "hit" if hit else "miss"
        key = f"{_TENANT_STATS_PREFIX}:search:{tenant_id}:{suffix}"
        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, 86400)  # 24h
            await pipe.execute()
        except Exception:
            pass  # 메트릭 실패는 조용히 무시

    async def get_tenant_hit_rate(self, tenant_id: UUID) -> dict[str, Any]:
        """특정 테넌트의 검색 캐시 hit rate 조회."""
        redis = await self._get_redis()
        try:
            hit_key = f"{_TENANT_STATS_PREFIX}:search:{tenant_id}:hit"
            miss_key = f"{_TENANT_STATS_PREFIX}:search:{tenant_id}:miss"
            hits = int(await redis.get(hit_key) or 0)
            misses = int(await redis.get(miss_key) or 0)
            total = hits + misses
            return {
                "tenant_id": str(tenant_id),
                "hits": hits,
                "misses": misses,
                "hit_rate": hits / total if total > 0 else 0.0,
            }
        except Exception:
            return {"tenant_id": str(tenant_id), "hits": 0, "misses": 0, "hit_rate": 0.0}

    # ------------------------------------------------------------------
    # 캐시 워밍업
    # ------------------------------------------------------------------

    async def cache_warmup(
        self,
        tenant_id: UUID,
        top_n: int = 50,
        search_fn: Any = None,
    ) -> int:
        """인기 쿼리 기반 캐시 사전 적재.

        search_logs 테이블에서 최근 30일간 빈도 상위 top_n 쿼리를 추출하고,
        search_fn을 호출하여 캐시를 채운다.

        Args:
            tenant_id: 대상 테넌트 ID
            top_n: 워밍업할 쿼리 수 (기본 50)
            search_fn: ``async def(query, tenant_id) -> None`` 형태의 검색 실행 함수.
                       None이면 쿼리 목록만 반환한다.

        Returns:
            워밍업된 쿼리 수
        """
        log.info("cache_warmup_started", tenant_id=str(tenant_id), top_n=top_n)

        try:
            from sqlalchemy import func, select

            from src.core.database import async_session_factory
            from src.core.models.search_log import SearchLog

            async with async_session_factory() as session:
                stmt = (
                    select(SearchLog.query, func.count(SearchLog.id).label("cnt"))
                    .where(
                        SearchLog.tenant_id == tenant_id,
                        SearchLog.created_at
                        >= func.now() - func.cast("30 days", func.literal_column("interval")),
                    )
                    .group_by(SearchLog.query)
                    .order_by(func.count(SearchLog.id).desc())
                    .limit(top_n)
                )
                result = await session.execute(stmt)
                top_queries = [(row[0], row[1]) for row in result.all()]

            warmed = 0
            for query_text, freq in top_queries:
                if search_fn:
                    try:
                        await search_fn(query_text, tenant_id)
                        warmed += 1
                    except Exception:
                        log.warning(
                            "cache_warmup_query_failed",
                            query=query_text[:80],
                            exc_info=True,
                        )
                else:
                    warmed += 1

            log.info(
                "cache_warmup_completed",
                tenant_id=str(tenant_id),
                total_queries=len(top_queries),
                warmed=warmed,
            )
            return warmed
        except Exception:
            log.warning("cache_warmup_failed", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # 전체 캐시 삭제 (관리용)
    # ------------------------------------------------------------------

    async def clear_all(self) -> int:
        """모든 검색 캐시 삭제. 관리자 전용."""
        redis = await self._get_redis()
        try:
            cursor = "0"
            deleted = 0
            while cursor:
                cursor, keys = await redis.scan(
                    cursor=cursor,
                    match=f"{self.KEY_PREFIX}:*",
                    count=200,
                )
                if keys:
                    deleted += await redis.delete(*keys)
                if cursor == b"0" or cursor == "0":
                    break
            log.info("search_cache_cleared", deleted=deleted)
            return deleted
        except Exception:
            log.warning("search_cache_clear_failed", exc_info=True)
            return 0


class LLMResponseCache:
    """
    LLM 응답 캐시.

    동일 RAG 컨텍스트에 대한 LLM 응답을 재사용.
    캐시 키: hash(prompt + model + max_tokens + temperature)
    TTL: 기본 7일 (604800초)
    temperature > 0인 경우 캐시 스킵 (비결정적 응답).
    """

    KEY_PREFIX = "aicm:llm_cache"
    DEFAULT_TTL = 7 * 24 * 3600  # 7일

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        default_ttl: int = 7 * 24 * 3600,
    ) -> None:
        self._redis = redis_client
        self._default_ttl = default_ttl
        self._stats = CacheStats()

    async def _get_redis(self) -> aioredis.Redis:
        """지연 초기화된 Redis 클라이언트 반환."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        return self._redis

    @staticmethod
    def _build_cache_key(
        prompt: str,
        model: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        """캐시 키 생성. prompt_hash + model + max_tokens + temperature 조합."""
        key_data: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
        }
        if max_tokens is not None:
            key_data["max_tokens"] = max_tokens
        if temperature != 0.0:
            key_data["temperature"] = temperature
        key_json = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        key_hash = hashlib.sha256(key_json.encode("utf-8")).hexdigest()
        return f"{LLMResponseCache.KEY_PREFIX}:{key_hash}"

    async def get(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """
        캐시에서 LLM 응답 조회.

        temperature > 0이면 항상 None 반환 (비결정적 응답은 캐시하지 않음).
        """
        if temperature > 0:
            self._stats.miss_count += 1
            log.debug("llm_cache_skip_non_deterministic", temperature=temperature)
            return None

        redis = await self._get_redis()
        cache_key = self._build_cache_key(prompt, model, max_tokens, temperature)

        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                self._stats.hit_count += 1
                log.info("llm_cache_hit", cache_key=cache_key[:32])
                return json.loads(cached)
            self._stats.miss_count += 1
            log.debug("llm_cache_miss", cache_key=cache_key[:32])
            return None
        except Exception:
            log.warning("llm_cache_get_failed", exc_info=True)
            self._stats.miss_count += 1
            return None

    async def set(
        self,
        prompt: str,
        model: str,
        response_data: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        ttl: int | None = None,
    ) -> None:
        """
        LLM 응답을 캐시에 저장.

        temperature > 0이면 저장하지 않음.
        """
        if temperature > 0:
            log.debug("llm_cache_skip_store_non_deterministic", temperature=temperature)
            return

        redis = await self._get_redis()
        cache_key = self._build_cache_key(prompt, model, max_tokens, temperature)
        effective_ttl = ttl if ttl is not None else self._default_ttl

        try:
            serialized = json.dumps(response_data, ensure_ascii=False, default=str)
            await redis.set(cache_key, serialized, ex=effective_ttl)
            log.debug("llm_cache_set", cache_key=cache_key[:32], ttl=effective_ttl)
        except Exception:
            log.warning("llm_cache_set_failed", exc_info=True)

    async def clear_all(self) -> int:
        """모든 LLM 응답 캐시 삭제. 관리자 전용."""
        redis = await self._get_redis()
        try:
            cursor = "0"
            deleted = 0
            while cursor:
                cursor, keys = await redis.scan(
                    cursor=cursor,
                    match=f"{self.KEY_PREFIX}:*",
                    count=200,
                )
                if keys:
                    deleted += await redis.delete(*keys)
                if cursor == b"0" or cursor == "0":
                    break
            log.info("llm_cache_cleared", deleted=deleted)
            return deleted
        except Exception:
            log.warning("llm_cache_clear_failed", exc_info=True)
            return 0

    @property
    def stats(self) -> CacheStats:
        """현재 캐시 통계 반환."""
        return self._stats

    def reset_stats(self) -> None:
        """캐시 통계 초기화."""
        self._stats = CacheStats()


# ---------------------------------------------------------------------------
# EmbeddingCache 통계 조회 헬퍼 (platform_admin 에서 사용)
# ---------------------------------------------------------------------------


async def get_embedding_cache_stats() -> dict[str, Any]:
    """임베딩 캐시의 Redis 키 카운트 등 통계를 반환한다."""
    try:
        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        cursor = "0"
        count = 0
        while cursor:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match="aicm:embed:bge-m3:*",
                count=500,
            )
            count += len(keys)
            if cursor == b"0" or cursor == "0":
                break
        await redis.aclose()
        return {"cached_embeddings": count}
    except Exception:
        return {"cached_embeddings": 0, "error": "Redis 연결 실패"}


async def clear_embedding_cache() -> int:
    """모든 임베딩 캐시를 삭제한다."""
    try:
        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
        cursor = b"0"
        deleted = 0
        while cursor:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=b"aicm:embed:bge-m3:*",
                count=500,
            )
            if keys:
                deleted += await redis.delete(*keys)
            if cursor == b"0":
                break
        await redis.aclose()
        log.info("embedding_cache_cleared", deleted=deleted)
        return deleted
    except Exception:
        log.warning("embedding_cache_clear_failed", exc_info=True)
        return 0
