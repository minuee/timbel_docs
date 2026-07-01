"""LLM 기반 쿼리 리라이터 — 오타 교정, 동의어 확장, 대화형 쿼리 재구성.

기존 QueryRewriter(query_rewriter.py)와 별도로 동작하며,
검색 파이프라인 진입 전 Step 0a에서 호출된다.

- correct_typos: 오타 교정 (Redis 7일 캐시)
- expand_synonyms: 동의어/유사 표현 2-3개 생성 (multi-query search + RRF 병합)
- reformulate_for_search: 대화형 쿼리 → 독립 검색 쿼리 변환
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

import redis.asyncio as aioredis

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

# -- Prompt templates ----------------------------------------------------------

TYPO_PROMPT = """사용자의 검색 쿼리를 **문서에서 관련 내용을 찾기 좋은 형태**로 다시 써라.

다음 2단계로 사고하라.

[1단계] 쿼리 의도 분류
   - 직접형: 질문 자체가 문서에 있을 법한 사실을 바로 찾는다.
     (예: "수수료 얼마?", "X 가 뭐야?" — 사실을 직접 묻는다)
   - 파생형: 질문의 답이 문서의 **다른 사실에 의존**해서 도출된다.
     (예: "오늘 X 했는데 내일 Y 가능?" — Y 가능성은 X 처리에 대한 '어떤 사실' 을 알아야 답할 수 있다.
     "3일 뒤에 출금 돼?" — 출금 가능 시점이 어떤 규정에 달려 있는지 그 규정 사실을 알아야 한다)

[2단계] 재작성
   - 직접형: 구어체·반말·오타를 격식체·문서 용어·정확한 철자로 정규화만 한다. 의미·구조 보존.
     변환 힌트: 반말 어미("해?", "되?", "와?", "야?") → 높임("하나요?", "되나요?"),
     축약 생활어("팔고", "사고", "돈", "통장") → 문서 용어("매도", "매수", "대금", "계좌").
   - 파생형: **질문에 답하기 위해 문서에서 확인해야 할 '의존 사실'** 을 찾는 검색 쿼리로 바꾼다.
     자문: "이 질문에 답하려면 문서의 무엇을 먼저 알아야 하나?" → 그 무엇이 곧 쿼리.
     원 질문의 조건(시간·금액·상태 등)은 버리고, 판단 근거가 되는 규정/사실의 이름을 쿼리에 담는다.

쿼리가 이미 격식체 직접형이고 오타도 없으면 had_changes=false.

원 쿼리: {query}

JSON만 출력:
{{"corrected": "재작성된 쿼리", "had_typos": true|false, "had_changes": true|false}}"""

SYNONYM_PROMPT = """다음 검색 쿼리에 대해 동의어/유사 표현을 2-3개 생성하라.
원래 의미를 유지하되 다른 용어나 표현을 사용하라.

쿼리: {query}
도메인 힌트: {domain_hint}

JSON만 출력 (다른 텍스트 없이):
{{"variants": ["변형1", "변형2", ...]}}"""

REFORMULATE_PROMPT = """대화 맥락을 참고하여 마지막 질문을 독립적인 검색 쿼리로 변환하라.
대명사, 생략된 주어/목적어를 대화 기록에서 복원하라.
'X 말고/아니고 ~' 처럼 특정 대상을 제외하는 표현이면, 제외 대상(X)을 검색어에서 빼고
실제 가리키는 대상을 대화 기록에서 복원하라.

has_specific_target 판정 기준:
- true: 대화 기록에서 구체적인 상품명·문서명·고유 명칭을 특정하여 복원한 경우
- false: 대화 기록에 구체적 대상이 없어 '펀드 상품', '금융상품' 같은 범주만 추측한 경우

대화 기록:
{conversation_history}

마지막 질문: {query}

JSON만 출력 (다른 텍스트 없이):
{{"reformulated": "독립적인 검색 쿼리", "resolved_references": ["복원된 참조1", ...], "has_specific_target": true|false}}"""

# Redis 캐시 설정
_TYPO_CACHE_PREFIX = "aicm:llm_rewrite:typo"
_SYNONYM_CACHE_PREFIX = "aicm:llm_rewrite:synonym"
_REFORMULATE_CACHE_PREFIX = "aicm:llm_rewrite:reformulate"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7일


def _cache_key(prefix: str, text: str) -> str:
    """텍스트를 SHA-256 해싱하여 Redis 캐시 키를 생성한다."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"


def _strip_think_tags(text: str) -> str:
    """<think>...</think> 태그를 제거한다."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _extract_json(raw: str) -> dict:
    """LLM 응답에서 JSON을 추출한다."""
    raw = _strip_think_tags(raw)
    # 코드 블럭 내 JSON 추출
    if "```" in raw:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("llm_rewrite_json_parse_failed", raw=raw[:200])
        return {}


class LLMQueryRewriter:
    """LLM 기반 쿼리 강화기.

    오타 교정, 동의어 확장, 대화형 쿼리 재구성 기능을 제공한다.
    모든 결과는 Redis에 캐싱되어 동일 쿼리 재처리를 방지한다.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        """LLMQueryRewriter를 초기화한다.

        Args:
            llm_client: OpenAI-compatible AsyncOpenAI 클라이언트.
            model: LLM 모델 이름. None이면 settings.VLLM_MODEL 사용.
            redis_client: Redis 클라이언트. None이면 지연 초기화.
        """
        self._llm = llm_client
        self._model = model or getattr(settings, "VLLM_MODEL", "gemma-4-31b")
        self._redis = redis_client

    async def _get_redis(self) -> aioredis.Redis:
        """지연 초기화된 Redis 클라이언트를 반환한다."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        return self._redis

    async def _get_cached(self, key: str) -> dict | None:
        """Redis에서 캐시된 JSON을 가져온다."""
        try:
            redis = await self._get_redis()
            cached = await redis.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception:
            log.debug("llm_rewrite_cache_get_failed", exc_info=True)
        return None

    async def _set_cached(self, key: str, data: dict, ttl: int = _CACHE_TTL_SECONDS) -> None:
        """JSON 데이터를 Redis에 캐싱한다."""
        try:
            redis = await self._get_redis()
            await redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        except Exception:
            log.debug("llm_rewrite_cache_set_failed", exc_info=True)

    async def _call_llm(self, prompt: str) -> str:
        """LLM API를 호출하여 텍스트 응답을 반환한다."""
        if self._llm is None:
            raise RuntimeError("LLM 클라이언트가 설정되지 않았습니다")

        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": "JSON만 출력하세요. 다른 텍스트는 포함하지 마세요."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return resp.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # 1. 오타 교정
    # ------------------------------------------------------------------
    async def correct_typos(self, query: str) -> str:
        """LLM으로 검색 쿼리의 오타를 교정한다.

        오타가 없으면 원본 쿼리를 그대로 반환한다.
        Redis에 7일간 캐싱된다.

        Args:
            query: 사용자 검색 쿼리

        Returns:
            교정된 쿼리 (또는 오타가 없으면 원본)
        """
        if not query.strip():
            return query

        start = time.monotonic()
        cache_key = _cache_key(_TYPO_CACHE_PREFIX, query)

        # 캐시 확인
        cached = await self._get_cached(cache_key)
        if cached is not None:
            log.debug("typo_correction_cache_hit", query=query[:100])
            return cached.get("corrected", query)

        # LLM 호출
        try:
            prompt = TYPO_PROMPT.format(query=query)
            raw = await self._call_llm(prompt)
            result = _extract_json(raw)

            corrected = result.get("corrected", query)
            had_typos = result.get("had_typos", False)
            had_changes = result.get("had_changes", had_typos)

            # 캐시 저장
            await self._set_cached(
                cache_key,
                {"corrected": corrected, "had_typos": had_typos, "had_changes": had_changes},
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)
            if had_changes or had_typos:
                log.info(
                    "llm_query_rewritten",
                    action="normalize",
                    original=query[:100],
                    corrected=corrected[:100],
                    had_typos=had_typos,
                    latency_ms=elapsed_ms,
                )
            else:
                log.debug(
                    "typo_correction_no_change",
                    query=query[:100],
                    latency_ms=elapsed_ms,
                )

            return corrected

        except Exception as exc:
            log.warning("typo_correction_failed", error=str(exc), query=query[:100])
            return query

    # ------------------------------------------------------------------
    # 2. 동의어 확장
    # ------------------------------------------------------------------
    async def expand_synonyms(self, query: str, domain_hint: str = "") -> list[str]:
        """LLM으로 동의어/유사 표현을 2-3개 생성한다.

        원본 쿼리를 포함한 리스트를 반환한다.
        multi-query 검색에 사용: 모든 변형으로 검색 후 RRF 병합.

        Args:
            query: 사용자 검색 쿼리
            domain_hint: 도메인 힌트 (예: "제조", "금융", "의료")

        Returns:
            [원본 쿼리, 변형1, 변형2, ...] 리스트
        """
        if not query.strip():
            return [query]

        start = time.monotonic()
        cache_text = f"{query}|{domain_hint}"
        cache_key = _cache_key(_SYNONYM_CACHE_PREFIX, cache_text)

        # 캐시 확인
        cached = await self._get_cached(cache_key)
        if cached is not None:
            variants = cached.get("variants", [])
            log.debug("synonym_expansion_cache_hit", query=query[:100], variants=len(variants))
            return [query] + [v for v in variants if v != query]

        # LLM 호출
        try:
            prompt = SYNONYM_PROMPT.format(
                query=query,
                domain_hint=domain_hint or "일반",
            )
            raw = await self._call_llm(prompt)
            result = _extract_json(raw)

            variants = result.get("variants", [])
            # 원본과 중복 제거
            unique_variants = []
            seen = {query.lower().strip()}
            for v in variants:
                v_lower = v.lower().strip()
                if v_lower and v_lower not in seen:
                    seen.add(v_lower)
                    unique_variants.append(v)

            # 캐시 저장
            await self._set_cached(cache_key, {"variants": unique_variants})

            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "llm_query_rewritten",
                action="synonym_expansion",
                original=query[:100],
                variants=unique_variants,
                latency_ms=elapsed_ms,
            )

            return [query] + unique_variants

        except Exception as exc:
            log.warning("synonym_expansion_failed", error=str(exc), query=query[:100])
            return [query]

    # ------------------------------------------------------------------
    # 3. 대화형 쿼리 재구성
    # ------------------------------------------------------------------
    async def reformulate_for_search(
        self,
        query: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """대화형 쿼리를 독립적인 검색 쿼리로 변환한다.

        "그건 뭐야?" 같은 대명사 참조를 대화 기록에서 복원하여
        독립적으로 검색 가능한 쿼리를 생성한다.
        대화 기록이 없으면 원본을 그대로 반환한다.

        Args:
            query: 사용자의 마지막 질문
            conversation_history: 대화 기록 리스트
                [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]

        Returns:
            (reformulated_query, has_specific_target) 튜플.
            has_specific_target: 대화 이력에서 구체적 대상을 특정했으면 True.
        """
        if not query.strip():
            return query, True

        # 대화 기록이 없으면 원본 반환
        if not conversation_history:
            return query, True

        start = time.monotonic()

        # 캐시 키: 쿼리 + 최근 대화 3턴
        recent_history = conversation_history[-6:]  # 최근 3턴 (user+assistant)
        cache_text = json.dumps(
            {"query": query, "history": recent_history}, ensure_ascii=False
        )
        cache_key = _cache_key(_REFORMULATE_CACHE_PREFIX, cache_text)

        # 캐시 확인
        cached = await self._get_cached(cache_key)
        if cached is not None:
            log.debug("reformulation_cache_hit", query=query[:100])
            return cached.get("reformulated", query), bool(cached.get("has_specific_target", True))

        # LLM 호출
        try:
            history_str = "\n".join(
                f"{'사용자' if m.get('role') == 'user' else '어시스턴트'}: {m.get('content', '')}"
                for m in recent_history
            )
            prompt = REFORMULATE_PROMPT.format(
                conversation_history=history_str,
                query=query,
            )
            raw = await self._call_llm(prompt)
            result = _extract_json(raw)

            reformulated = result.get("reformulated", query)
            resolved = result.get("resolved_references", [])
            has_specific = bool(result.get("has_specific_target", True))

            # 캐시 저장
            await self._set_cached(
                cache_key,
                {"reformulated": reformulated, "resolved_references": resolved,
                 "has_specific_target": has_specific},
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "llm_query_rewritten",
                action="reformulation",
                original=query[:100],
                reformulated=reformulated[:100],
                resolved_references=resolved,
                has_specific_target=has_specific,
                latency_ms=elapsed_ms,
            )

            return reformulated, has_specific

        except Exception as exc:
            log.warning("reformulation_failed", error=str(exc), query=query[:100])
            return query, True
