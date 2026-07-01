"""Redis 기반 External API 응답 캐시.

/ext/search 와 /ext/ask (context 모드만) 응답을 캐싱한다.
answer 모드는 LLM 비결정성 때문에 캐싱하지 않는다.

캐시 키: sha256(api_key_id + endpoint + request_body)
무효화: 영향받는 repository의 문서 변경 시
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from pydantic import BaseModel

from src.common.logging import get_logger
from src.integration.metrics import CACHE_HIT_TOTAL, CACHE_MISS_TOTAL

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

DEFAULT_SEARCH_TTL = 300  # 5분
DEFAULT_CONTEXT_TTL = 1800  # 30분
CACHE_KEY_PREFIX = "aicm:resp_cache"
REPO_INDEX_PREFIX = "aicm:resp_cache:repo"


class CacheTTLConfig(BaseModel):
    """API 키별 캐시 TTL 설정."""

    search_ttl: int = DEFAULT_SEARCH_TTL
    context_ttl: int = DEFAULT_CONTEXT_TTL


class CachedResponse(BaseModel):
    """캐시에 저장되는 응답 래퍼."""

    status_code: int = 200
    body: str
    ttl_remaining: int = 0


class ResponseCache:
    """Redis 기반 응답 캐시.

    Args:
        redis: aioredis 클라이언트 인스턴스
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # 캐시 조회
    # ------------------------------------------------------------------

    async def get(
        self,
        api_key_id: UUID,
        endpoint: str,
        request_body: str,
    ) -> CachedResponse | None:
        """캐시에서 응답을 조회한다.

        Args:
            api_key_id: API 키 ID
            endpoint: 엔드포인트 (예: "/ext/search")
            request_body: 요청 본문 JSON 문자열

        Returns:
            캐시된 응답 또는 None (미스).
        """
        cache_key = self._make_key(api_key_id, endpoint, request_body)
        raw = await self._redis.get(cache_key)

        if raw is None:
            CACHE_MISS_TOTAL.labels(cache_type=self._cache_type(endpoint)).inc()
            log.debug("cache_miss", endpoint=endpoint, key_id=str(api_key_id))
            return None

        CACHE_HIT_TOTAL.labels(cache_type=self._cache_type(endpoint)).inc()
        ttl = await self._redis.ttl(cache_key)

        log.debug(
            "cache_hit",
            endpoint=endpoint,
            key_id=str(api_key_id),
            ttl_remaining=ttl,
        )

        return CachedResponse(
            body=raw.decode("utf-8") if isinstance(raw, bytes) else raw,
            ttl_remaining=max(0, ttl),
        )

    # ------------------------------------------------------------------
    # 캐시 저장
    # ------------------------------------------------------------------

    async def put(
        self,
        api_key_id: UUID,
        endpoint: str,
        request_body: str,
        response_body: str,
        repository_id: UUID | None = None,
        ttl: int | None = None,
    ) -> None:
        """응답을 캐시에 저장한다.

        Args:
            api_key_id: API 키 ID
            endpoint: 엔드포인트
            request_body: 요청 본문
            response_body: 응답 본문 JSON
            repository_id: 관련 repository ID (무효화용 인덱스)
            ttl: TTL 초 (None이면 엔드포인트별 기본값)
        """
        if ttl is None:
            ttl = self._default_ttl(endpoint)

        cache_key = self._make_key(api_key_id, endpoint, request_body)

        pipe = self._redis.pipeline()
        pipe.setex(cache_key, ttl, response_body)

        # repository_id가 있으면 역인덱스에 등록 (무효화용)
        if repository_id:
            repo_key = f"{REPO_INDEX_PREFIX}:{repository_id}"
            pipe.sadd(repo_key, cache_key)
            pipe.expire(repo_key, max(ttl * 2, 3600))

        await pipe.execute()

        log.debug(
            "cache_put",
            endpoint=endpoint,
            key_id=str(api_key_id),
            ttl=ttl,
            repository_id=str(repository_id) if repository_id else None,
        )

    # ------------------------------------------------------------------
    # 캐시 무효화
    # ------------------------------------------------------------------

    async def invalidate_by_repository(self, repository_id: UUID) -> int:
        """특정 repository 관련 캐시를 모두 무효화한다.

        문서 변경(생성/수정/삭제) 시 호출한다.

        Returns:
            삭제된 캐시 키 수.
        """
        repo_key = f"{REPO_INDEX_PREFIX}:{repository_id}"
        cache_keys = await self._redis.smembers(repo_key)

        if not cache_keys:
            return 0

        # 캐시 키 + 인덱스 키 모두 삭제
        pipe = self._redis.pipeline()
        for key in cache_keys:
            pipe.delete(key)
        pipe.delete(repo_key)
        await pipe.execute()

        count = len(cache_keys)
        log.info(
            "cache_invalidated",
            repository_id=str(repository_id),
            deleted_keys=count,
        )
        return count

    # ------------------------------------------------------------------
    # 캐시 스킵 판단
    # ------------------------------------------------------------------

    @staticmethod
    def should_skip(
        request_body_dict: dict[str, Any],
        endpoint: str,
    ) -> bool:
        """캐시를 스킵해야 하는지 판단한다.

        스킵 조건:
        - request에 no_cache: true가 있을 때
        - /ext/ask에서 response_mode가 "answer"일 때 (LLM 비결정성)
        """
        if request_body_dict.get("no_cache", False):
            return True

        if endpoint == "/ext/ask":
            response_mode = request_body_dict.get("response_mode", "answer")
            if response_mode != "context":
                return True

        return False

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(api_key_id: UUID, endpoint: str, request_body: str) -> str:
        """캐시 키 생성: sha256(api_key_id + endpoint + request_body)."""
        raw = f"{api_key_id}:{endpoint}:{request_body}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{CACHE_KEY_PREFIX}:{digest}"

    @staticmethod
    def _default_ttl(endpoint: str) -> int:
        """엔드포인트별 기본 TTL."""
        if endpoint == "/ext/search":
            return DEFAULT_SEARCH_TTL
        if endpoint == "/ext/ask":
            return DEFAULT_CONTEXT_TTL
        return DEFAULT_SEARCH_TTL

    @staticmethod
    def _cache_type(endpoint: str) -> str:
        """메트릭 라벨용 캐시 타입."""
        if "search" in endpoint:
            return "search"
        if "ask" in endpoint:
            return "ask_context"
        return "other"
