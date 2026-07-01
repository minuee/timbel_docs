"""결과 충분성 평가기 — 검색 결과가 사용자 질문에 충분한지 LLM이 판단.

검색 결과가 부족하면 suggested_query를 생성하여 재검색을 트리거한다.
비용이 높으므로 기본 비활성화 (enable_sufficiency_check=True일 때만 동작).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.logging import get_logger
from src.search.models import SearchHit

log = get_logger(__name__)

SUFFICIENCY_PROMPT = """다음 검색 결과들이 사용자의 질문에 충분히 답할 수 있는지 평가하라.

질문: {query}

검색 결과:
{results_text}

JSON만 출력 (다른 텍스트 없이):
{{
  "sufficient": true|false,
  "confidence": 0.0~1.0,
  "missing": "부족한 정보 설명 (충분하면 빈 문자열)",
  "suggested_query": "재검색 쿼리 (충분하면 빈 문자열)"
}}

판단 기준:
- sufficient=true: 결과만으로 질문에 정확하게 답변 가능
- sufficient=false: 핵심 정보가 누락되어 답변이 불완전할 것
- suggested_query: 부족한 정보를 보완할 수 있는 다른 검색 쿼리"""


class SufficiencyResult(BaseModel):
    """충분성 평가 결과."""

    sufficient: bool = True
    confidence: float = 0.0
    missing: str = ""
    suggested_query: str = ""
    latency_ms: int = 0


class SufficiencyEvaluator:
    """LLM 기반 검색 결과 충분성 평가기.

    검색 결과가 사용자의 질문에 답하기에 충분한지 판단하고,
    불충분하면 재검색을 위한 쿼리를 제안한다.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str | None = None,
        max_results_to_evaluate: int = 5,
        max_content_chars: int = 500,
    ) -> None:
        """SufficiencyEvaluator를 초기화한다.

        Args:
            llm_client: OpenAI-compatible AsyncOpenAI 클라이언트.
            model: LLM 모델 이름. None이면 settings.VLLM_MODEL 사용.
            max_results_to_evaluate: 평가할 최대 결과 수.
            max_content_chars: 각 결과의 content 최대 문자 수.
        """
        self._llm = llm_client
        self._model = model or getattr(settings, "VLLM_MODEL", "gemma-4-31b")
        self._max_results = max_results_to_evaluate
        self._max_content_chars = max_content_chars

    async def evaluate(
        self,
        query: str,
        results: list[SearchHit],
    ) -> SufficiencyResult:
        """검색 결과의 충분성을 평가한다.

        Args:
            query: 검색 쿼리
            results: 검색 결과 리스트

        Returns:
            SufficiencyResult: 평가 결과
        """
        start = time.monotonic()

        # 결과가 아예 없으면 무조건 불충분
        if not results:
            return SufficiencyResult(
                sufficient=False,
                confidence=1.0,
                missing="검색 결과가 없습니다",
                suggested_query=query,
                latency_ms=0,
            )

        if self._llm is None:
            return SufficiencyResult(
                sufficient=True,
                confidence=0.5,
                missing="",
                suggested_query="",
                latency_ms=0,
            )

        try:
            # 평가할 결과 선택
            eval_results = results[: self._max_results]
            results_text = self._format_results(eval_results)

            prompt = SUFFICIENCY_PROMPT.format(
                query=query,
                results_text=results_text,
            )

            resp = await self._llm.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            raw = resp.choices[0].message.content or ""
            data = self._extract_json(raw)

            elapsed_ms = int((time.monotonic() - start) * 1000)

            result = SufficiencyResult(
                sufficient=data.get("sufficient", True),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                missing=data.get("missing", ""),
                suggested_query=data.get("suggested_query", ""),
                latency_ms=elapsed_ms,
            )

            if not result.sufficient:
                log.info(
                    "sufficiency_check_failed",
                    query=query[:100],
                    confidence=round(result.confidence, 3),
                    missing=result.missing[:200],
                    suggested_query=result.suggested_query[:100],
                    latency_ms=elapsed_ms,
                )
            else:
                log.debug(
                    "sufficiency_check_passed",
                    query=query[:100],
                    confidence=round(result.confidence, 3),
                    latency_ms=elapsed_ms,
                )

            return result

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.warning("sufficiency_evaluation_failed", error=str(exc), query=query[:100])
            # 실패 시 충분하다고 가정 (재검색 트리거 방지)
            return SufficiencyResult(
                sufficient=True,
                confidence=0.0,
                missing="",
                suggested_query="",
                latency_ms=elapsed_ms,
            )

    def _format_results(self, results: list[SearchHit]) -> str:
        """결과를 프롬프트용 텍스트로 포맷팅한다."""
        lines: list[str] = []
        for i, hit in enumerate(results):
            content = hit.content[: self._max_content_chars]
            if len(hit.content) > self._max_content_chars:
                content += "..."
            title = hit.document_title or "제목 없음"
            score = hit.rerank_score or hit.fused_score or hit.dense_score or 0.0
            lines.append(f"[{i + 1}] {title} (스코어: {score:.3f})\n{content}\n")
        return "\n".join(lines)

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """LLM 응답에서 JSON을 추출한다."""
        raw = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL).strip()
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]
        else:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("sufficiency_json_parse_failed", raw=raw[:200])
            return {}
