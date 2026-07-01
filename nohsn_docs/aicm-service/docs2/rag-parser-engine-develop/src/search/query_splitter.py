"""검색 쿼리 분해기 — 복합/멀티턴 질문을 자기완결 서브질문 N개로 분해(LLM).

기존 필터추출 QueryDecomposer 와 역할이 다르다(혼동 금지):
QueryDecomposer = 필터(category/nature/entity) 추출. QuerySplitter = 질문을 서브질문으로 분할.
"""
from __future__ import annotations

import asyncio
import json
import re

import structlog

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "너는 검색 쿼리 분해기다. 대화 맥락을 사용해 마지막 사용자 발화의 생략·대명사·참조를 "
    "해소하고, 의미 단위로 독립적이고 자기완결적인 검색용 서브질문으로 분해한다. "
    "복합이면 여러 개, 단순이면 1개. 각 서브질문은 그 자체로 검색 가능해야 한다. "
    'JSON 배열로만 답하라. 예: ["서브질문1", "서브질문2"]'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class QuerySplitter:
    def __init__(self, llm_client, model: str):
        self._llm = llm_client
        self._model = model

    async def split(
        self,
        query: str,
        conversation_history: list[dict] | None,
        max_subqueries: int = 4,
        timeout_s: float = 2.0,
    ) -> list[str]:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": query})
        try:
            resp = await asyncio.wait_for(
                self._llm.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=256,
                ),
                timeout=timeout_s,
            )
            content = resp.choices[0].message.content or ""
        except Exception as exc:
            log.warning("query_split_llm_failed", error=str(exc))
            return [query]

        subs = self._parse(content)
        if not subs:
            return [query]
        return subs[:max_subqueries]

    @staticmethod
    def _parse(content: str) -> list[str]:
        text = content.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()  # F3
        m = _FENCE_RE.search(text)
        if m:
            text = m.group(1).strip()
        try:
            arr = json.loads(text)
        except Exception:
            return []
        if not isinstance(arr, list):
            return []
        out = []
        for item in arr:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
