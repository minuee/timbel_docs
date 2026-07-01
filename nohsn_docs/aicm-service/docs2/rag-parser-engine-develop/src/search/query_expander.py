"""쿼리 확장 -- HyDE + 키워드 추출.

사용자의 짧은 쿼리를 검색에 최적화된 형태로 확장한다.

전략:
1. HyDE: 가상 답변을 생성하여 답변의 임베딩으로 검색 (답변과 유사한 문서가 매칭)
2. 키워드 추출: 쿼리에서 한국어/영어 핵심 키워드를 분리

LLM 클라이언트가 없으면 HyDE는 건너뛰고 키워드 추출만 수행한다.
HyDE 결과는 Redis 에 query 해시 기준으로 캐싱한다 (TTL 1시간).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.common.logging import get_logger

log = get_logger(__name__)

_HYDE_CACHE_PREFIX = "search:hyde:"
_HYDE_CACHE_TTL_SEC = 3600  # 1 hour


class LLMClient(Protocol):
    """HyDE에 사용할 LLM 클라이언트 프로토콜."""

    async def generate(self, prompt: str) -> str:
        """프롬프트에 대한 텍스트 응답을 생성한다."""
        ...


class ExpandedQuery(BaseModel):
    """확장된 쿼리 결과."""

    original: str
    hyde_document: str = ""  # HyDE 가상 답변
    expanded_keywords: list[str] = Field(default_factory=list)
    rewritten_query: str = ""  # 확장된 쿼리


class QueryExpander:
    """쿼리를 확장하여 검색 품질을 높인다.

    HyDE (Hypothetical Document Embedding):
    - 쿼리에 대한 가상 답변을 생성한 뒤, 그 답변의 임베딩으로 검색
    - 답변 형태의 텍스트가 실제 문서와 더 유사하므로 매칭률 향상

    키워드 추출:
    - 불용어를 제거하고 핵심 단어만 추출
    - LLM 없이도 동작
    """

    # 한국어 질문 불용어
    _STOPWORDS_KO: set[str] = {
        "무엇", "어떻게", "얼마", "어디", "무슨", "어떤", "왜", "언제",
        "있나요", "인가요", "인지", "대해", "관해", "관련",
    }

    # 영어 질문 불용어
    _STOPWORDS_EN: set[str] = {
        "what", "how", "where", "when", "why", "which", "who",
        "the", "is", "are", "was", "were", "does", "did", "can",
    }

    def __init__(
        self,
        llm_client: Any | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._llm = llm_client
        self._redis = redis_client  # aioredis.Redis | None
        self._redis_init_failed = False

    async def _ensure_redis(self) -> Any | None:
        """Redis 클라이언트가 없으면 settings.REDIS_URL 로 지연 초기화."""
        if self._redis is not None or self._redis_init_failed:
            return self._redis
        try:
            from src.common.config import settings
            import redis.asyncio as aioredis

            redis_url = getattr(settings, "REDIS_URL", None)
            if not redis_url:
                self._redis_init_failed = True
                return None
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
        except Exception:
            log.warning("hyde_cache_redis_init_failed", exc_info=True)
            self._redis_init_failed = True
            return None
        return self._redis

    @staticmethod
    def _cache_key(query: str) -> str:
        h = hashlib.sha1(query.strip().encode("utf-8")).hexdigest()
        return f"{_HYDE_CACHE_PREFIX}{h}"

    async def _cached_hyde(self, query: str) -> str | None:
        r = await self._ensure_redis()
        if r is None:
            return None
        try:
            return await r.get(self._cache_key(query))
        except Exception:
            log.debug("hyde_cache_get_failed", exc_info=True)
            return None

    async def _store_hyde(self, query: str, hyde_doc: str) -> None:
        r = await self._ensure_redis()
        if r is None or not hyde_doc:
            return
        try:
            await r.setex(self._cache_key(query), _HYDE_CACHE_TTL_SEC, hyde_doc)
        except Exception:
            log.debug("hyde_cache_set_failed", exc_info=True)

    async def expand(self, query: str) -> ExpandedQuery:
        """쿼리를 확장한다.

        Args:
            query: 원본 사용자 쿼리

        Returns:
            확장된 쿼리 객체 (HyDE 문서, 키워드 등)
        """
        result = ExpandedQuery(original=query)

        # 1. HyDE -- Redis 캐시 조회 후 miss 시 LLM 호출
        if self._llm is not None:
            cached = await self._cached_hyde(query)
            if cached:
                result.hyde_document = cached
                log.debug("hyde_cache_hit", query_len=len(query))
            else:
                try:
                    hyde_doc = await self._generate_hypothetical_answer(query)
                    if hyde_doc:
                        result.hyde_document = hyde_doc
                        await self._store_hyde(query, hyde_doc)
                except Exception:
                    log.warning("hyde_generation_failed", exc_info=True)

        # 2. 키워드 확장 (LLM 없이도 동작)
        result.expanded_keywords = self._extract_search_keywords(query)

        return result

    async def _generate_hypothetical_answer(self, query: str) -> str:
        """HyDE: 질문에 대한 가상 답변을 생성한다.

        실제 데이터 없이도 일반적인 형태의 답변을 생성하여,
        답변과 유사한 문서를 검색할 수 있게 한다.
        """
        prompt = (
            "다음 질문에 대해 1-2문장으로 간결하게 답변하세요. "
            "실제 데이터가 없어도 일반적인 형태로 답변하면 됩니다.\n\n"
            f"질문: {query}\n"
            "답변:"
        )
        try:
            response = await self._llm.generate(prompt)
            return response.strip()
        except Exception:
            log.warning("hyde_llm_call_failed", exc_info=True)
            return ""

    @staticmethod
    def _extract_search_keywords(query: str) -> list[str]:
        """쿼리에서 검색 키워드를 추출한다.

        한국어 2글자 이상, 영어 3글자 이상 단어를 추출하고
        질문 불용어를 제거한다.
        """
        # Korean + English keywords
        words = re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}", query)
        # Remove common question words
        stopwords = QueryExpander._STOPWORDS_KO | QueryExpander._STOPWORDS_EN
        return [w for w in words if w.lower() not in stopwords]
