"""QueryDecomposer -- 2단계 쿼리 분해기.

단순 쿼리(70%): 임베딩 기반 카테고리 필터만 -> 즉시 검색
복합 쿼리(30%): LLM이 시간/성격/엔터티/도메인 분해 -> 구조화 필터

GC-Doc/gap_analysis.md GAP-SEARCH-01 참조.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import BaseModel, Field

from src.common.logging import get_logger

log = get_logger(__name__)


class DecomposedQuery(BaseModel):
    """분해된 쿼리 -- 검색 필터로 변환."""

    original_query: str
    is_complex: bool = False  # LLM 분해 여부

    # Category filter (Stage 1 -- embedding)
    category_ids: list[str] = Field(default_factory=list)
    category_names: list[str] = Field(default_factory=list)
    category_confidence: float = 0.0

    # Ontology filters (Stage 2 -- LLM, complex queries only)
    nature_filter: list[str] = Field(default_factory=list)  # ["fact", "schedule"]
    time_filter: dict[str, str] = Field(default_factory=dict)  # {"from": "2026-04-01", "to": "..."}
    entity_filter: dict[str, list[str]] = Field(
        default_factory=dict
    )  # {"people": ["김팀장"], "orgs": ["KB금융"]}
    domain_hint: str = ""  # "work", "personal/health"

    # Search parameters
    extract_type: str = ""  # "action_items", "summary", "comparison"
    fallback_level: int = 1  # 1=tight, 4=wide


class QueryDecomposer:
    """2단계 쿼리 분해기.

    Stage 1 (임베딩 필터, ~1ms):
        쿼리 임베딩과 카테고리 임베딩의 코사인 유사도로 상위 3개 카테고리를 선택.
        단순 쿼리(70%)는 이 필터만으로 검색에 진입한다.

    Stage 2 (LLM 분해, ~500ms, 복합 쿼리만):
        시간 범위, nature, 엔터티, 도메인 등을 LLM으로 추출하여 구조화 필터를 생성.
    """

    # 카테고리 임베딩 유사도 임계값
    CATEGORY_THRESHOLD: float = 0.3

    def __init__(
        self,
        llm_client: Any | None = None,
        category_embeddings: list[dict[str, Any]] | None = None,
        embedding_fn: Any | None = None,
        model: str = "",
    ) -> None:
        """QueryDecomposer를 초기화한다.

        Args:
            llm_client: OpenAI-compatible LLM 클라이언트 (vLLM/Gemma 4).
                        None이면 Stage 2를 건너뛴다.
            category_embeddings: 카테고리 목록.
                [{"id": "uuid", "name": "카테고리명", "embedding": [0.1, ...]}]
                None이거나 비어 있으면 Stage 1을 건너뛴다.
            embedding_fn: 쿼리 임베딩 함수.
                async (str) -> (list[float], dict[int, float]) 형태.
                None이면 BGEM3Embedder를 지연 로딩한다.
            model: vLLM 모델명. 비어 있으면 settings.VLLM_MODEL 사용.
        """
        self._llm = llm_client
        self._categories = category_embeddings or []
        self._embedding_fn = embedding_fn
        if not model:
            from src.common.config import settings
            model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
        self._model = model

    async def decompose(self, query: str) -> DecomposedQuery:
        """쿼리를 분해한다.

        Args:
            query: 사용자 검색 쿼리

        Returns:
            DecomposedQuery: 분해 결과 (카테고리 필터 + 온톨로지 필터)
        """
        result = DecomposedQuery(original_query=query)

        # Stage 1: Embedding filter (always runs if categories exist)
        if self._categories:
            await self._embedding_filter(query, result)

        # Complexity check: LLM 필요한지 판단
        if self._is_complex(query):
            result.is_complex = True
            if self._llm:
                await self._llm_decompose(query, result)

        log.debug(
            "query_decomposed",
            query=query[:100],
            is_complex=result.is_complex,
            category_count=len(result.category_ids),
            category_confidence=round(result.category_confidence, 3),
            nature_filter=result.nature_filter,
            has_time_filter=bool(result.time_filter),
            has_entity_filter=bool(result.entity_filter),
        )

        return result

    async def _embedding_filter(self, query: str, result: DecomposedQuery) -> None:
        """Stage 1: 쿼리 임베딩과 카테고리 임베딩 코사인 유사도로 필터.

        ~1ms (임베딩 생성 시간 제외). LLM 호출 없음.
        """
        try:
            query_vec = await self._get_query_embedding(query)
            if not query_vec:
                return

            # Cosine similarity with each category
            scored: list[tuple[float, dict[str, Any]]] = []
            for cat in self._categories:
                cat_vec = cat.get("embedding")
                if not cat_vec or not isinstance(cat_vec, list):
                    continue
                sim = _cosine_sim(query_vec, cat_vec)
                scored.append((sim, cat))

            scored.sort(key=lambda x: x[0], reverse=True)
            top3 = scored[:3]

            for score, cat in top3:
                if score > self.CATEGORY_THRESHOLD:
                    result.category_ids.append(str(cat["id"]))
                    result.category_names.append(cat.get("name", ""))

            if result.category_ids and top3:
                result.category_confidence = top3[0][0]

        except Exception:
            log.debug("embedding_filter_failed", exc_info=True)

    async def _get_query_embedding(self, query: str) -> list[float]:
        """쿼리의 dense 임베딩 벡터를 생성한다.

        embedding_fn이 주입되었으면 사용하고, 없으면 BGEM3Embedder를 지연 로딩한다.
        """
        if self._embedding_fn is not None:
            dense_vec, _ = await self._embedding_fn(query)
            return dense_vec

        # Fallback: BGEM3Embedder 직접 사용
        try:
            from src.pipeline.embedders.bge_m3 import BGEM3Embedder

            embedder = BGEM3Embedder()
            embed_result = await embedder.embed_single(query)
            return embed_result.dense
        except Exception:
            log.debug("query_embedding_fallback_failed", exc_info=True)
            return []

    @staticmethod
    def _is_complex(query: str) -> bool:
        """쿼리가 복합인지 판단 (LLM 분해 필요 여부).

        아래 4가지 신호 중 2개 이상이면 복합 쿼리로 판단:
        - 시간 표현
        - 복합 조건 (접속사/조합)
        - 엔터티 참조 (사람명, 조직명)
        - 추출/집계 의도 (요약, 비교, 목록)
        """
        # Time expressions
        has_time = bool(
            re.search(
                r"저번주|지난주|이번주|다음주|어제|오늘|내일|"
                r"지난달|이번달|다음달|"
                r"20[0-9]{2}년|[0-9]{1,2}월|"
                r"최근|요즘|그때|당시",
                query,
            )
        )
        # Multiple conditions (conjunction)
        has_conjunction = bool(
            re.search(r"에서.*나온|에서.*찾아|중에.*관련|관련.*정리", query)
        )
        # Entity references (Korean names with titles, or uppercase acronyms)
        has_entity = bool(
            re.search(r"[가-힣]{1,3}(팀장|대리|과장|부장|님|씨)|[A-Z]{2,}", query)
        )
        # Extract/aggregate intent
        has_extract = bool(
            re.search(r"정리|요약|비교|목록|리스트|몇|얼마", query)
        )

        return sum([has_time, has_conjunction, has_entity, has_extract]) >= 2

    async def _llm_decompose(self, query: str, result: DecomposedQuery) -> None:
        """Stage 2: LLM으로 복합 쿼리를 구조화 필터로 분해.

        vLLM (Gemma 4) 사용. ~500ms.
        실패 시 Stage 1 결과만 유지하고 검색을 계속한다.
        """
        from datetime import date

        today = date.today().isoformat()

        prompt = f"""사용자 검색 쿼리를 분석하여 구조화된 검색 필터로 분해하세요.

쿼리: "{query}"

JSON으로 반환:
{{
  "nature_filter": ["fact", "schedule" 등 해당하는 것만],
  "time_filter": {{"from": "ISO날짜", "to": "ISO날짜"}} 또는 {{}},
  "entity_filter": {{"people": ["이름"], "orgs": ["조직"]}},
  "domain_hint": "work/personal/health/finance/learning 또는 빈문자열",
  "extract_type": "action_items/summary/comparison/lookup 또는 빈문자열"
}}

nature 종류: fact(사실), opinion(의견), schedule(일정), record(기록), reference(참조), casual(잡담)
오늘 날짜: {today}"""

        try:
            if not hasattr(self._llm, "chat"):
                return

            resp = await self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.1,
            )
            text = resp.choices[0].message.content or ""

            # Strip HTML/thinking tags from response
            text = re.sub(r"<[^>]+>", "", text)

            # Extract JSON from response
            idx = text.find("{")
            if idx < 0:
                return
            end = text.rfind("}")
            if end <= idx:
                return

            data = json.loads(text[idx : end + 1])
            result.nature_filter = data.get("nature_filter", [])
            result.time_filter = data.get("time_filter", {})
            result.entity_filter = data.get("entity_filter", {})
            result.domain_hint = data.get("domain_hint", "")
            result.extract_type = data.get("extract_type", "")

        except Exception as exc:
            log.warning("llm_decompose_failed", error=str(exc))

    def update_categories(self, category_embeddings: list[dict[str, Any]]) -> None:
        """카테고리 임베딩 목록을 업데이트한다.

        런타임에 DB에서 카테고리를 다시 로드했을 때 호출.
        """
        self._categories = category_embeddings


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도를 계산한다."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
