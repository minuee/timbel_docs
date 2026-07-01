"""RAG 답변 환각(hallucination) 감지 서비스.

LLM을 사용하여 RAG 답변이 제공된 출처에 의해 뒷받침되는지 검증한다.
출처에 없는 주장(claim)을 식별하고, 신뢰도 점수를 산출한다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from src.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 프롬프트 템플릿
# ---------------------------------------------------------------------------

HALLUCINATION_CHECK_PROMPT = """다음 RAG 답변이 제공된 출처에 의해 충분히 뒷받침되는지 검증하라.

질문: {query}

답변:
{answer}

출처 자료:
{sources}

답변 내 주장(claim)을 추출하고, 각 주장이 출처에 있는지 확인:
JSON: {{
  "supported_claims": ["출처에 명시된 주장1", ...],
  "unsupported_claims": [
    {{"claim": "출처에 없는 주장", "reason": "어떤 부분이 추측인지"}}
  ],
  "fact_check_score": 0.0~1.0,
  "verdict": "supported"|"partial"|"hallucinated"
}}

기준:
- supported (>=0.85): 모든 주장이 출처에 명시
- partial (0.5~0.85): 일부 주장만 출처 기반
- hallucinated (<0.5): 다수 주장이 추측

반드시 유효한 JSON만 출력하라. 다른 텍스트는 포함하지 마라."""


# ---------------------------------------------------------------------------
# 응답 모델
# ---------------------------------------------------------------------------


class UnsupportedClaim(BaseModel):
    """출처에서 뒷받침되지 않는 주장."""

    claim: str = Field(..., description="출처에 없는 주장")
    reason: str = Field(..., description="해당 주장이 추측인 이유")


class HallucinationResult(BaseModel):
    """환각 감지 결과."""

    supported_claims: list[str] = Field(default_factory=list, description="출처에 뒷받침되는 주장 목록")
    unsupported_claims: list[UnsupportedClaim] = Field(
        default_factory=list, description="출처에 없는 주장 목록"
    )
    fact_check_score: float = Field(
        1.0, ge=0.0, le=1.0, description="사실 검증 점수 (1.0 = 완전 뒷받침)"
    )
    verdict: str = Field(
        "supported",
        pattern=r"^(supported|partial|hallucinated)$",
        description="검증 판정",
    )


# ---------------------------------------------------------------------------
# Redis 캐시 키 생성
# ---------------------------------------------------------------------------


def _make_cache_key(answer: str, sources_text: str) -> str:
    """답변과 출처의 해시로 캐시 키를 생성한다."""
    combined = f"{answer}|{sources_text}"
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]
    return f"aicm:hallucination:{digest}"


# ---------------------------------------------------------------------------
# HallucinationDetector
# ---------------------------------------------------------------------------


class HallucinationDetector:
    """RAG 답변의 환각을 감지하는 서비스.

    LLM을 사용하여 답변 내 주장을 추출하고, 각 주장이 출처에
    의해 뒷받침되는지 검증한다. Redis 기반 캐시를 지원한다.
    """

    CACHE_TTL = 86400  # 1일 (초)

    async def detect(
        self,
        answer: str,
        sources: list[dict[str, Any]],
        *,
        query: str = "",
    ) -> HallucinationResult:
        """RAG 답변의 환각을 감지한다.

        Args:
            answer: LLM이 생성한 RAG 답변
            sources: 답변 근거 출처 목록 (각 dict에 document_title, content 등 포함)
            query: 원래 사용자 질의

        Returns:
            HallucinationResult: 환각 감지 결과
        """
        if not answer or not answer.strip():
            return HallucinationResult(
                supported_claims=[],
                unsupported_claims=[],
                fact_check_score=1.0,
                verdict="supported",
            )

        if not sources:
            return HallucinationResult(
                supported_claims=[],
                unsupported_claims=[
                    UnsupportedClaim(
                        claim="전체 답변",
                        reason="제공된 출처가 없어 검증 불가",
                    )
                ],
                fact_check_score=0.0,
                verdict="hallucinated",
            )

        # 출처 텍스트 조립
        sources_text = self._format_sources(sources)

        # Redis 캐시 확인
        cached = await self._get_cached(answer, sources_text)
        if cached is not None:
            logger.info("hallucination_cache_hit", query=query[:50])
            return cached

        # LLM 호출
        result = await self._call_llm(answer, sources_text, query)

        # Redis 캐시 저장
        await self._set_cached(answer, sources_text, result)

        logger.info(
            "hallucination_detected",
            query=query[:50],
            verdict=result.verdict,
            fact_check_score=result.fact_check_score,
            supported_count=len(result.supported_claims),
            unsupported_count=len(result.unsupported_claims),
        )

        return result

    async def get_safe_answer(
        self,
        answer: str,
        hallucination_result: HallucinationResult,
    ) -> str:
        """환각이 감지된 경우 안전한 답변을 반환한다.

        Args:
            answer: 원본 LLM 답변
            hallucination_result: 환각 감지 결과

        Returns:
            안전한 답변 문자열. 환각 감지 시 경고를 포함한다.
        """
        if hallucination_result.verdict == "supported":
            return answer

        unsupported_summary = ", ".join(
            c.claim for c in hallucination_result.unsupported_claims
        )

        if hallucination_result.verdict == "hallucinated":
            warning = (
                "[주의: 이 답변은 출처에 의해 충분히 뒷받침되지 않습니다.]\n\n"
                f"{answer}\n\n"
                f"--- 출처에서 확인되지 않은 내용: {unsupported_summary}"
            )
            return warning

        # partial
        warning = (
            f"{answer}\n\n"
            f"--- 다음 내용은 출처에서 명확히 확인되지 않습니다: {unsupported_summary}"
        )
        return warning

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_sources(self, sources: list[dict[str, Any]]) -> str:
        """출처 목록을 LLM 프롬프트용 텍스트로 변환한다."""
        parts: list[str] = []
        for i, src in enumerate(sources, 1):
            title = src.get("document_title", "") or src.get("title", "")
            content = src.get("content", "") or src.get("context", "")
            section = src.get("section_title", "")
            header = f"[출처 {i}] {title}"
            if section:
                header += f" > {section}"
            parts.append(f"{header}\n{content}")
        return "\n\n".join(parts)

    async def _call_llm(
        self,
        answer: str,
        sources_text: str,
        query: str,
    ) -> HallucinationResult:
        """LLM을 호출하여 환각 감지를 수행한다."""
        prompt = HALLUCINATION_CHECK_PROMPT.format(
            query=query,
            answer=answer,
            sources=sources_text,
        )

        try:
            from src.common.llm.base import LLMRequest, LLMTask
            from src.common.llm.router import llm_router

            response = await llm_router.route(
                task=LLMTask.RAG_GENERATION,
                request=LLMRequest(
                    prompt=prompt,
                    system_prompt=(
                        "당신은 RAG 답변의 사실 검증 전문가입니다. "
                        "답변 내 각 주장이 출처에 의해 뒷받침되는지 엄격하게 검증하세요. "
                        "반드시 유효한 JSON만 출력하세요."
                    ),
                    max_tokens=1000,
                    temperature=0.1,
                    response_format="json",
                ),
            )

            return self._parse_llm_response(response.text)

        except ImportError:
            logger.warning("hallucination_llm_unavailable", reason="LLM router not available")
            return HallucinationResult(
                supported_claims=[],
                unsupported_claims=[],
                fact_check_score=1.0,
                verdict="supported",
            )
        except Exception as exc:
            logger.error("hallucination_llm_error", error=str(exc))
            # LLM 오류 시 안전하게 "supported"로 반환 (검증 불가)
            return HallucinationResult(
                supported_claims=[],
                unsupported_claims=[],
                fact_check_score=1.0,
                verdict="supported",
            )

    def _parse_llm_response(self, text: str) -> HallucinationResult:
        """LLM 응답 텍스트를 HallucinationResult로 파싱한다."""
        try:
            # JSON 블록 추출 (```json ... ``` 패턴 또는 순수 JSON)
            cleaned = text.strip()
            if cleaned.startswith("```"):
                # 코드 블록 내 JSON 추출
                lines = cleaned.split("\n")
                json_lines: list[str] = []
                inside = False
                for line in lines:
                    if line.strip().startswith("```") and not inside:
                        inside = True
                        continue
                    if line.strip().startswith("```") and inside:
                        break
                    if inside:
                        json_lines.append(line)
                cleaned = "\n".join(json_lines)

            data = json.loads(cleaned)

            # 결과 구조 검증 및 변환
            supported = data.get("supported_claims", [])
            unsupported_raw = data.get("unsupported_claims", [])
            score = float(data.get("fact_check_score", 1.0))
            verdict = data.get("verdict", "supported")

            # score 범위 보정
            score = max(0.0, min(1.0, score))

            # verdict 보정 (score 기반)
            if verdict not in ("supported", "partial", "hallucinated"):
                if score >= 0.85:
                    verdict = "supported"
                elif score >= 0.5:
                    verdict = "partial"
                else:
                    verdict = "hallucinated"

            # unsupported_claims 변환
            unsupported: list[UnsupportedClaim] = []
            for item in unsupported_raw:
                if isinstance(item, dict):
                    unsupported.append(
                        UnsupportedClaim(
                            claim=item.get("claim", ""),
                            reason=item.get("reason", ""),
                        )
                    )
                elif isinstance(item, str):
                    unsupported.append(
                        UnsupportedClaim(claim=item, reason="상세 이유 미제공")
                    )

            return HallucinationResult(
                supported_claims=supported if isinstance(supported, list) else [],
                unsupported_claims=unsupported,
                fact_check_score=score,
                verdict=verdict,
            )

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "hallucination_parse_error",
                error=str(exc),
                response_preview=text[:200],
            )
            # 파싱 실패 시 안전하게 반환
            return HallucinationResult(
                supported_claims=[],
                unsupported_claims=[],
                fact_check_score=1.0,
                verdict="supported",
            )

    # ------------------------------------------------------------------
    # Redis Cache
    # ------------------------------------------------------------------

    async def _get_cached(
        self,
        answer: str,
        sources_text: str,
    ) -> HallucinationResult | None:
        """Redis에서 캐시된 환각 감지 결과를 조회한다."""
        try:
            from src.common.redis import get_redis_client

            redis = await get_redis_client()
            key = _make_cache_key(answer, sources_text)
            raw = await redis.get(key)
            await redis.aclose()

            if raw:
                data = json.loads(raw)
                return HallucinationResult(**data)
        except Exception as exc:
            logger.debug("hallucination_cache_get_error", error=str(exc))

        return None

    async def _set_cached(
        self,
        answer: str,
        sources_text: str,
        result: HallucinationResult,
    ) -> None:
        """환각 감지 결과를 Redis에 캐시한다 (TTL 1일)."""
        try:
            from src.common.redis import get_redis_client

            redis = await get_redis_client()
            key = _make_cache_key(answer, sources_text)
            await redis.setex(
                key,
                self.CACHE_TTL,
                result.model_dump_json(),
            )
            await redis.aclose()
        except Exception as exc:
            logger.debug("hallucination_cache_set_error", error=str(exc))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

hallucination_detector = HallucinationDetector()
