"""LLM 쿼리 리라이팅 — 검색 히트율 향상을 위한 질의 확장/구체화.

사용자의 짧거나 모호한 검색 쿼리를 LLM이 분석하여:
1. 의미를 구체화한 자연어 질의 (Dense 검색용)
2. 핵심 키워드를 추출/확장 (Sparse/Keyword 검색용)
3. 원본 쿼리도 유지 (사용자 의도 보존)

OpenAI 호환 API (vLLM/Qwen 포함) 및 Anthropic 지원.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from src.common.logging import get_logger
from src.search.models import ProcessedQuery, SearchTraceStep

log = get_logger(__name__)

_REWRITE_PROMPT = """당신은 검색 쿼리 최적화 전문가입니다.
사용자의 검색 쿼리를 분석하여 검색 성능을 높이기 위한 확장 쿼리를 생성하세요.

## 입력 쿼리
{query}

## 출력 형식 (JSON만, 다른 텍스트 없이)
{{
  "rewritten": "의미를 구체화한 자연어 검색 문장 (1문장, 원래 의도 유지)",
  "keywords": ["핵심키워드1", "핵심키워드2", "관련키워드3"],
  "intent": "질문형|조회형|비교형|절차형"
}}

## 규칙
1. rewritten: 원래 의도를 유지하면서 검색에 유리하도록 구체화. 없는 정보를 추가하지 마세요.
2. keywords: 원본에 없더라도 도메인 관련 동의어/관련어를 2~3개 추가.
3. intent: 쿼리 의도를 분류하여 검색 전략 힌트로 사용."""


class QueryRewriter:
    """LLM 기반 쿼리 리라이터.

    LLM이 없으면 원본 쿼리를 그대로 반환 (no-op).
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str = "Qwen/Qwen3.5-27B",
        enabled: bool = True,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._enabled = enabled and llm_client is not None

    async def rewrite(
        self,
        query: str,
        processed: ProcessedQuery,
    ) -> tuple[ProcessedQuery, SearchTraceStep]:
        """검색 쿼리를 리라이팅한다.

        Parameters
        ----------
        query : str
            원본 사용자 쿼리
        processed : ProcessedQuery
            형태소 분석 완료된 전처리 결과

        Returns
        -------
        (ProcessedQuery, SearchTraceStep)
            보강된 쿼리 + 트레이스 단계
        """
        start = time.monotonic()

        if not self._enabled:
            trace = SearchTraceStep(
                step_name="query_rewrite",
                latency_ms=0,
                candidate_count=0,
                details={"skipped": True, "reason": "disabled_or_no_llm"},
            )
            return processed, trace

        try:
            result = await self._call_llm(query)
            rewritten = result.get("rewritten", query)
            extra_keywords = result.get("keywords", [])
            intent = result.get("intent", "")

            # ProcessedQuery 보강
            enhanced = ProcessedQuery(
                original=processed.original,
                cleaned=processed.cleaned,
                keywords=_dedupe(processed.keywords + extra_keywords),
                for_dense=rewritten,  # Dense 검색에 구체화된 쿼리 사용
                for_sparse=processed.for_sparse,  # Sparse는 원본 유지
                for_keyword=_dedupe(processed.for_keyword + extra_keywords),
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)
            trace = SearchTraceStep(
                step_name="query_rewrite",
                latency_ms=elapsed_ms,
                candidate_count=len(extra_keywords),
                details={
                    "original": query,
                    "rewritten": rewritten,
                    "added_keywords": extra_keywords,
                    "intent": intent,
                    "model": self._model,
                },
            )

            log.info(
                "query_rewritten",
                original=query,
                rewritten=rewritten,
                added_keywords=extra_keywords,
                intent=intent,
                latency_ms=elapsed_ms,
            )
            return enhanced, trace

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.warning("query_rewrite_failed", error=str(exc), query=query[:100])
            trace = SearchTraceStep(
                step_name="query_rewrite",
                latency_ms=elapsed_ms,
                candidate_count=0,
                details={"error": str(exc), "fallback": "original_query"},
            )
            return processed, trace

    async def _call_llm(self, query: str) -> dict:
        """LLM 호출 후 JSON 파싱."""
        prompt = _REWRITE_PROMPT.format(query=query)
        raw = await self._invoke(prompt)

        # <think>...</think> 제거
        raw = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL).strip()

        # JSON 추출
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("query_rewrite_json_failed", raw=raw[:200])
            return {"rewritten": query, "keywords": [], "intent": ""}

    async def _invoke(self, prompt: str) -> str:
        """LLM API 호출 (OpenAI 호환 / Anthropic)."""
        # OpenAI 호환
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                resp = await self._llm_client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "JSON만 출력하세요."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=500,
                )
                return resp.choices[0].message.content or ""

            if isinstance(self._llm_client, OpenAI):
                import asyncio

                resp = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "JSON만 출력하세요."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=500,
                )
                return resp.choices[0].message.content or ""
        except ImportError:
            pass

        raise RuntimeError("지원하지 않는 LLM 클라이언트입니다")


def _dedupe(items: list[str]) -> list[str]:
    """중복 제거하며 순서 유지."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        lower = item.lower().strip()
        if lower and lower not in seen:
            seen.add(lower)
            result.append(item.strip())
    return result
