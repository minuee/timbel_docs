"""LLM 기반 리랭커 — BGE Cross-encoder 이후 정밀 재평가.

BGE 리랭킹 결과의 상위 10건에 대해 LLM이 관련도를 1-10으로 평가하여
최종 순위를 재조정한다.

- BGE cross-encoder: 빠르고 비용 없음, 의미적 유사도 기반
- LLM reranker: 느리지만 추론 능력으로 세밀한 관련도 평가 가능
  (예: 질문 의도 이해, 부분 매칭 구분, 도메인 컨텍스트 반영)

비용 제어: top-10 이내만 LLM 평가 (기본값).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from src.common.config import settings
from src.common.logging import get_logger
from src.search.models import SearchHit, SearchTraceStep

log = get_logger(__name__)

RERANK_PROMPT = """다음 검색 결과들을 쿼리와의 관련도로 평가하라.

쿼리: {query}

결과:
{results_with_index}

각 결과의 관련도 점수(1-10)를 JSON 배열로 반환하라.
- 10: 쿼리에 대한 완벽한 답변
- 7-9: 높은 관련도, 핵심 정보 포함
- 4-6: 부분적 관련
- 1-3: 거의 무관

JSON만 출력 (다른 텍스트 없이):
[{{"index": 0, "score": 8, "reason": "관련 이유"}}, ...]"""


def _strip_think_tags(text: str) -> str:
    """<think>...</think> 태그를 제거한다."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _extract_json_array(raw: str) -> list[dict]:
    """LLM 응답에서 JSON 배열을 추출한다."""
    raw = _strip_think_tags(raw)
    # 코드 블럭 내 JSON 추출
    if "```" in raw:
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    else:
        # 배열 시작점 찾기
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]

    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        log.warning("llm_rerank_json_parse_failed", raw=raw[:300])
        return []


class LLMReranker:
    """LLM 기반 결과 리랭커.

    BGE cross-encoder 이후 top-N 결과를 LLM이 세밀하게 재평가한다.
    비용 제어를 위해 기본 max_candidates=10으로 제한한다.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str | None = None,
        max_candidates: int = 10,
        max_content_chars: int = 500,
    ) -> None:
        """LLMReranker를 초기화한다.

        Args:
            llm_client: OpenAI-compatible AsyncOpenAI 클라이언트.
            model: LLM 모델 이름. None이면 settings.VLLM_MODEL 사용.
            max_candidates: LLM 평가 대상 최대 후보 수 (비용 제어).
            max_content_chars: 각 결과의 content 최대 문자 수 (프롬프트 길이 제어).
        """
        self._llm = llm_client
        self._model = model or getattr(settings, "VLLM_MODEL", "gemma-4-31b")
        self._max_candidates = max_candidates
        self._max_content_chars = max_content_chars

    async def rerank(
        self,
        query: str,
        candidates: list[SearchHit],
        top_k: int = 5,
    ) -> tuple[list[SearchHit], SearchTraceStep]:
        """LLM으로 검색 결과를 리랭킹한다.

        Args:
            query: 검색 쿼리
            candidates: BGE rerank 완료된 후보 목록
            top_k: 최종 반환할 결과 수

        Returns:
            (리랭킹된 결과 리스트, 트레이스 단계)
        """
        start = time.monotonic()

        if not candidates:
            trace = SearchTraceStep(
                step_name="llm_reranking",
                latency_ms=0,
                candidate_count=0,
                details={"skipped": True, "reason": "no_candidates"},
            )
            return [], trace

        if self._llm is None:
            trace = SearchTraceStep(
                step_name="llm_reranking",
                latency_ms=0,
                candidate_count=len(candidates),
                details={"skipped": True, "reason": "no_llm_client"},
            )
            return candidates[:top_k], trace

        # 비용 제어: max_candidates 이내만 LLM 평가
        eval_candidates = candidates[: self._max_candidates]
        remaining = candidates[self._max_candidates :]

        try:
            # 프롬프트 구성
            results_text = self._format_results(eval_candidates)
            prompt = RERANK_PROMPT.format(
                query=query,
                results_with_index=results_text,
            )

            # LLM 호출
            resp = await self._llm.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "JSON 배열만 출력하세요. 다른 텍스트는 포함하지 마세요.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=800,
            )
            raw = resp.choices[0].message.content or ""
            scores = _extract_json_array(raw)

            # 스코어 매핑 적용
            score_map: dict[int, float] = {}
            reason_map: dict[int, str] = {}
            for item in scores:
                idx = item.get("index")
                score = item.get("score", 0)
                reason = item.get("reason", "")
                if isinstance(idx, int) and 0 <= idx < len(eval_candidates):
                    # 1-10 → 0.0-1.0 정규화
                    score_map[idx] = max(0.0, min(1.0, float(score) / 10.0))
                    reason_map[idx] = reason

            # 스코어가 매핑된 후보는 LLM 스코어로, 아닌 후보는 기존 스코어 유지
            for i, hit in enumerate(eval_candidates):
                if i in score_map:
                    # LLM 스코어를 rerank_score에 반영 (기존 BGE 스코어와 가중 합산)
                    bge_score = hit.rerank_score or hit.fused_score or 0.0
                    llm_score = score_map[i]
                    # BGE 60% + LLM 40% 가중 합산
                    hit.rerank_score = bge_score * 0.6 + llm_score * 0.4
                    hit.metadata = hit.metadata or {}
                    hit.metadata["llm_rerank_score"] = round(llm_score, 4)
                    hit.metadata["llm_rerank_reason"] = reason_map.get(i, "")

            # LLM 평가된 후보 정렬
            eval_candidates.sort(key=lambda x: x.rerank_score or 0.0, reverse=True)
            final = (eval_candidates + remaining)[:top_k]

            elapsed_ms = int((time.monotonic() - start) * 1000)
            trace = SearchTraceStep(
                step_name="llm_reranking",
                latency_ms=elapsed_ms,
                candidate_count=len(final),
                details={
                    "input_count": len(candidates),
                    "evaluated_count": len(eval_candidates),
                    "scores_received": len(score_map),
                    "model": self._model,
                    "top_llm_scores": [
                        round(score_map.get(i, 0.0), 3) for i in range(min(5, len(score_map)))
                    ],
                },
            )

            log.info(
                "llm_reranked",
                input_count=len(candidates),
                evaluated=len(eval_candidates),
                output_count=len(final),
                latency_ms=elapsed_ms,
            )

            return final, trace

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.warning("llm_rerank_failed", error=str(exc), query=query[:100])
            trace = SearchTraceStep(
                step_name="llm_reranking",
                latency_ms=elapsed_ms,
                candidate_count=len(candidates),
                details={"error": str(exc), "fallback": "bge_scores_only"},
            )
            # 실패 시 기존 BGE 순위 유지
            return candidates[:top_k], trace

    def _format_results(self, candidates: list[SearchHit]) -> str:
        """결과를 LLM 프롬프트용 텍스트로 포맷팅한다."""
        lines: list[str] = []
        for i, hit in enumerate(candidates):
            content = hit.content[: self._max_content_chars]
            if len(hit.content) > self._max_content_chars:
                content += "..."
            title = hit.document_title or "제목 없음"
            section = hit.section_title or ""
            header = f"[{i}] 문서: {title}"
            if section:
                header += f" > {section}"
            lines.append(f"{header}\n{content}\n")
        return "\n".join(lines)
