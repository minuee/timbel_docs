"""LLM 자가 검증 (Self-Verification) — 분류 결과 2차 리뷰.

기존 온톨로지 분류(nature/category/entities)가 높은 confidence를 보고하면서도
실제로는 오류인 경우를 잡기 위한 비판적 검토자 패턴.

동작 조건:
  - ProcessingConfig.enable_self_verification = True 일 때만 실행
  - classification_confidence < 0.85 인 블럭만 검증 (고신뢰 블럭 스킵)
  - 블럭 해시 기반 캐시로 중복 검증 방지

3가지 검증:
  1. verify_classification — 분류 결과 재검토 (agree/disagree + 신뢰도 보정)
  2. evaluate_block_cohesion — 블럭 응집도 평가 (0.0~1.0)
  3. detect_missing_information — 원문 대비 블럭 누락 정보 탐지
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

VERIFY_CLASSIFICATION_PROMPT = """비판적 검토자로서 다음 블럭의 분류를 재검토하라.

블럭 내용:
{content}

이전 분류 결과:
- nature: {nature}
- entities: {entities}
- confidence: {confidence}
- reasoning: {reasoning}

위 분류에 동의하는가? 다른 의견이 있다면?

JSON: {{
  "agree": true|false,
  "disagree_reason": "이유 (agree=false인 경우)",
  "suggested_nature": "...",
  "suggested_confidence": 0.0~1.0
}}"""

COHESION_PROMPT = """다음 블럭이 하나의 응집된 의미 단위인지 평가하라.

블럭:
{content}

평가 기준:
- 단일 주제인가
- 문장들이 자연스럽게 이어지는가
- 잘린 부분은 없는가

JSON: {{"cohesion_score": 0.0~1.0, "issues": ["문제 목록"]}}"""

MISSING_INFO_PROMPT = """원본 문서 텍스트와 추출된 블럭들을 비교하여 누락된 중요 정보를 찾아라.

원본 (앞부분 5000자):
{document_text}

블럭 요약 (각 블럭의 첫 100자):
{blocks_summary}

JSON: {{"missing": [{{"description": "...", "original_snippet": "..."}}]}}"""

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

_VERIFY_CONCURRENCY = 4
_CONFIDENCE_THRESHOLD = 0.85  # 이 이상이면 검증 스킵
_COHESION_DISPUTE_THRESHOLD = 0.5  # 이 미만이면 disputed 플래그
_CONFIDENCE_PENALTY = 0.2  # disagree 시 감점

_VALID_NATURES = {"fact", "opinion", "schedule", "record", "reference", "casual"}


class SelfVerifier:
    """LLM 자가 검증기 — 분류 결과를 비판적 관점에서 재검토한다.

    Parameters
    ----------
    llm_client : Any
        OpenAI 호환 AsyncOpenAI 클라이언트 (vLLM).
    model : str
        사용할 LLM 모델명. 비어있으면 settings에서 가져온다.
    """

    def __init__(self, llm_client: Any, model: str = "") -> None:
        self._llm_client = llm_client
        self._model = model
        # D56 §E PR-E: Redis 기반 enricher cache.
        from src.pipeline.enrichers.cache import EnricherRedisCache
        from src.common.config import settings as _settings

        self._cache = EnricherRedisCache(
            name="self_verifier",
            schema_version="v1",
            prompt_version="v1",
            prompt_text=VERIFY_CLASSIFICATION_PROMPT,
            model_id=model or getattr(_settings, "VLLM_MODEL", "gemma-4-31b"),
            inference_params={"temperature": 0.2},
        )

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    async def verify_all(
        self,
        blocks: list[BlockObject],
        document_text: str = "",
    ) -> list[BlockObject]:
        """모든 블럭에 자가 검증을 적용한다.

        1) 분류 검증 (confidence < threshold 블럭만)
        2) 응집도 평가 (confidence < threshold 블럭만)
        3) 누락 정보 탐지 (문서 전체 1회)

        Parameters
        ----------
        blocks : list[BlockObject]
            분류가 완료된 블럭 목록.
        document_text : str
            전체 문서 원문 (누락 탐지용).

        Returns
        -------
        list[BlockObject]
            검증 메타데이터가 추가된 블럭 목록 (in-place 수정).
        """
        if not blocks or self._llm_client is None:
            return blocks

        # 검증 대상: confidence < threshold & 유효한 블럭 타입
        targets = [
            b for b in blocks
            if b.block_type not in (BlockType.SUMMARY, BlockType.DIVIDER)
            and b.content
            and len(b.content) >= 20
            and b.metadata.get("classification_confidence", 0.0) < _CONFIDENCE_THRESHOLD
            and b.metadata.get("nature")  # 분류가 있는 블럭만
        ]

        if not targets:
            log.info(
                "self_verification_skipped",
                reason="no_blocks_below_threshold",
                total_blocks=len(blocks),
            )
            return blocks

        log.info(
            "self_verification_start",
            total_blocks=len(blocks),
            target_blocks=len(targets),
            confidence_threshold=_CONFIDENCE_THRESHOLD,
        )

        # 1) 분류 검증 + 2) 응집도 평가 (병렬)
        sem = asyncio.Semaphore(_VERIFY_CONCURRENCY)
        verified = 0
        disagreed = 0
        disputed = 0

        async def _verify_one(block: BlockObject) -> None:
            nonlocal verified, disagreed, disputed
            async with sem:
                # D56 §E: Redis cache 확인
                cache_key = block.block_hash
                if cache_key:
                    cached = await self._cache.get(cache_key)
                    if cached is not None and isinstance(cached, dict):
                        self._apply_verification_result(block, cached)
                        verified += 1
                        if not cached.get("agree", True):
                            disagreed += 1
                        return

                # 분류 검증
                v_result = await self.verify_classification(block)
                if v_result:
                    self._apply_verification_result(block, v_result)
                    if not v_result.get("agree", True):
                        disagreed += 1
                    # 캐시 저장
                    if cache_key:
                        await self._cache.set(cache_key, v_result)

                # 응집도 평가
                cohesion = await self.evaluate_block_cohesion(block)
                if cohesion is not None:
                    block.metadata["cohesion_score"] = cohesion
                    if cohesion < _COHESION_DISPUTE_THRESHOLD:
                        block.metadata["validity_status"] = "disputed"
                        disputed += 1

                verified += 1

        await asyncio.gather(
            *[_verify_one(b) for b in targets],
            return_exceptions=True,
        )

        # 3) 누락 정보 탐지 (문서 전체 1회)
        missing_items: list[dict] = []
        if document_text:
            missing_items = await self.detect_missing_information(blocks, document_text)

        log.info(
            "self_verification_complete",
            verified=verified,
            disagreed=disagreed,
            disputed=disputed,
            missing_items=len(missing_items),
        )

        return blocks

    # ------------------------------------------------------------------
    # 1) 분류 검증
    # ------------------------------------------------------------------

    async def verify_classification(self, block: BlockObject) -> dict:
        """블럭의 기존 분류를 비판적으로 재검토한다.

        Parameters
        ----------
        block : BlockObject
            분류가 완료된 블럭.

        Returns
        -------
        dict
            {"agree": bool, "suggested_corrections": dict, "confidence_adjustment": float}
        """
        nature = block.metadata.get("nature", "")
        entities = block.metadata.get("entities", {})
        confidence = block.metadata.get("classification_confidence", 0.0)
        reasoning = block.metadata.get("classification_reasoning", "")

        prompt = VERIFY_CLASSIFICATION_PROMPT.format(
            content=block.content[:500],
            nature=nature,
            entities=json.dumps(entities, ensure_ascii=False) if entities else "없음",
            confidence=confidence,
            reasoning=reasoning or "없음",
        )

        try:
            raw = await self._call_llm(prompt)
            parsed = self._parse_json(raw)
            if not isinstance(parsed, dict):
                return {}

            agree = parsed.get("agree", True)
            if isinstance(agree, str):
                agree = agree.lower() in ("true", "yes", "동의")

            suggested_nature = parsed.get("suggested_nature", "")
            suggested_confidence = parsed.get("suggested_confidence", confidence)
            if not isinstance(suggested_confidence, (int, float)):
                suggested_confidence = confidence

            # 결과 구성
            result: dict[str, Any] = {
                "agree": bool(agree),
                "suggested_corrections": {},
                "confidence_adjustment": 0.0,
            }

            if not agree:
                corrections: dict[str, Any] = {}
                if suggested_nature and suggested_nature in _VALID_NATURES:
                    corrections["nature"] = suggested_nature
                disagree_reason = parsed.get("disagree_reason", "")
                if disagree_reason:
                    corrections["reason"] = str(disagree_reason)
                if isinstance(suggested_confidence, (int, float)):
                    corrections["suggested_confidence"] = float(
                        max(0.0, min(1.0, suggested_confidence))
                    )
                result["suggested_corrections"] = corrections
                result["confidence_adjustment"] = -_CONFIDENCE_PENALTY

            log.debug(
                "classification_verified",
                block_id=str(block.id),
                agree=result["agree"],
                adjustment=result["confidence_adjustment"],
            )
            return result

        except Exception as exc:
            log.warning(
                "verify_classification_failed",
                block_id=str(block.id),
                error=str(exc),
            )
            return {}

    # ------------------------------------------------------------------
    # 2) 블럭 응집도 평가
    # ------------------------------------------------------------------

    async def evaluate_block_cohesion(self, block: BlockObject) -> float | None:
        """블럭이 하나의 응집된 의미 단위인지 LLM으로 평가한다.

        Parameters
        ----------
        block : BlockObject
            평가 대상 블럭.

        Returns
        -------
        float | None
            응집도 점수 0.0~1.0. 실패 시 None.
        """
        prompt = COHESION_PROMPT.format(content=block.content[:500])

        try:
            raw = await self._call_llm(prompt)
            parsed = self._parse_json(raw)
            if not isinstance(parsed, dict):
                return None

            score = parsed.get("cohesion_score", None)
            if not isinstance(score, (int, float)):
                return None

            score = float(max(0.0, min(1.0, score)))
            issues = parsed.get("issues", [])

            if issues and isinstance(issues, list):
                block.metadata["cohesion_issues"] = [str(i) for i in issues[:5]]

            log.debug(
                "cohesion_evaluated",
                block_id=str(block.id),
                cohesion_score=score,
                issues_count=len(issues) if isinstance(issues, list) else 0,
            )
            return score

        except Exception as exc:
            log.warning(
                "evaluate_cohesion_failed",
                block_id=str(block.id),
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # 3) 누락 정보 탐지
    # ------------------------------------------------------------------

    async def detect_missing_information(
        self,
        blocks: list[BlockObject],
        document_text: str,
    ) -> list[dict]:
        """원문 대비 블럭에 누락된 중요 정보를 탐지한다.

        Parameters
        ----------
        blocks : list[BlockObject]
            추출된 블럭 목록.
        document_text : str
            전체 문서 원문.

        Returns
        -------
        list[dict]
            [{"description": "...", "snippet": "..."}, ...]
        """
        if not document_text or not blocks:
            return []

        # 블럭 요약 구성 (각 블럭의 첫 100자)
        summaries = []
        for i, b in enumerate(blocks):
            if b.block_type in (BlockType.SUMMARY, BlockType.DIVIDER):
                continue
            snippet = b.content[:100].replace("\n", " ")
            summaries.append(f"[{i}] {b.block_type.value}: {snippet}")

        blocks_summary = "\n".join(summaries[:50])  # 최대 50블럭

        prompt = MISSING_INFO_PROMPT.format(
            document_text=document_text[:5000],
            blocks_summary=blocks_summary,
        )

        try:
            raw = await self._call_llm(prompt)
            parsed = self._parse_json(raw)
            if not isinstance(parsed, dict):
                return []

            missing = parsed.get("missing", [])
            if not isinstance(missing, list):
                return []

            # 정규화
            results: list[dict] = []
            for item in missing:
                if not isinstance(item, dict):
                    continue
                desc = item.get("description", "")
                snippet = item.get("original_snippet", "")
                if desc:
                    results.append({
                        "description": str(desc),
                        "snippet": str(snippet)[:200] if snippet else "",
                    })

            if results:
                log.warning(
                    "missing_information_detected",
                    count=len(results),
                    descriptions=[r["description"][:80] for r in results[:3]],
                )

            return results

        except Exception as exc:
            log.warning("detect_missing_info_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_verification_result(block: BlockObject, result: dict) -> None:
        """검증 결과를 블럭 메타데이터에 적용한다."""
        block.metadata["self_verification"] = {
            "agree": result.get("agree", True),
            "corrections": result.get("suggested_corrections", {}),
            "confidence_adjustment": result.get("confidence_adjustment", 0.0),
        }

        if not result.get("agree", True):
            # confidence 감점
            current = block.metadata.get("classification_confidence", 0.0)
            adjustment = result.get("confidence_adjustment", -_CONFIDENCE_PENALTY)
            new_confidence = max(0.0, current + adjustment)
            block.metadata["classification_confidence"] = new_confidence

            # 제안된 nature가 있으면 적용
            corrections = result.get("suggested_corrections", {})
            suggested_nature = corrections.get("nature", "")
            if suggested_nature in _VALID_NATURES:
                block.metadata["original_nature"] = block.metadata.get("nature", "")
                block.metadata["nature"] = suggested_nature

            log.info(
                "classification_corrected",
                block_id=str(block.id),
                original_confidence=current,
                new_confidence=new_confidence,
                nature_changed=bool(suggested_nature),
            )

    def _resolve_model(self) -> str:
        """사용할 모델명을 결정한다."""
        if self._model:
            return self._model
        try:
            from src.common.config import settings
            return getattr(settings, "VLLM_MODEL", "gemma-4-31b")
        except ImportError:
            return "gemma-4-31b"

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 호출 (OpenAI 호환 / Anthropic)."""
        model = self._resolve_model()

        # OpenAI 호환 (vLLM, Gemma 4)
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                response = await self._llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=512,
                )
                text = response.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

            if isinstance(self._llm_client, OpenAI):
                response = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=512,
                )
                text = response.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
        except ImportError:
            pass

        # D40 Phase A — VLLMAdapter 등 generic adapter 지원.
        if hasattr(self._llm_client, "generate"):
            text = await self._llm_client.generate(prompt)  # type: ignore[union-attr]
            return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

        raise RuntimeError("LLM 클라이언트를 사용할 수 없습니다")

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        """LLM 응답에서 JSON 객체 추출."""
        cleaned = raw.strip()

        # 코드블럭 내 JSON 추출
        if "```" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        # { 로 시작하는 JSON 찾기
        if cleaned and cleaned[0] != "{":
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        try:
            result = json.loads(cleaned)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None
