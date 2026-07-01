"""블럭 온톨로지 분류기 — 모든 문서 포맷에서 동작.

stage3_enrich의 LLM 분류 로직을 재사용하여 PDF뿐만 아니라
DOCX/HWP/MD/TXT 등 모든 블럭에 nature/time_reference/entities 분류 적용.

기존 3-stage 파이프라인과 동일한 프롬프트 사용.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)

_VALID_NATURES = {"fact", "opinion", "schedule", "record", "reference", "casual"}
_ENRICH_CONCURRENCY = 8  # 순차 큐 덕에 한 문서만 처리되므로 동시성 올려도 OK

_CLASSIFY_PROMPT = """블럭을 분류하세요.

문서: {doc_type} — "{title}"
블럭 타입: {block_type}
내용: {content}

JSON으로 반환:
{{
  "nature": "fact/opinion/schedule/record/reference/casual 중 하나",
  "time_reference": {{"raw": "원문 시간표현", "resolved": "ISO날짜", "basis": "근거"}} 또는 {{}},
  "entities": {{"speakers": [], "people": [], "orgs": [], "locations": []}},
  "confidence": 0.0,
  "reasoning": "분류 근거 한 문장"
}}

nature 기준:
- fact: 객관적 사실/수치/결정사항
- opinion: 주관적 의견/평가
- schedule: 일정/계획/마감일
- record: 기록/로그/회의록
- reference: 참조자료/가이드/매뉴얼
- casual: 일상대화/잡담"""


class OntologyClassifier:
    """블럭에 nature/time_reference/entities 분류를 적용한다.

    LLM 클라이언트가 없으면 no-op (graceful degradation).
    병렬 처리로 속도 최적화.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        document_type: str = "문서",
        document_title: str = "",
    ) -> None:
        self._llm_client = llm_client
        self._doc_type = document_type
        self._doc_title = document_title

    async def classify_all(self, blocks: list[BlockObject], force: bool = False) -> list[BlockObject]:
        """모든 블럭에 분류를 적용한다 (병렬)."""
        if self._llm_client is None:
            log.debug("ontology_classifier_no_llm_skip")
            return blocks

        # 분류 대상 필터: 이미 nature가 있는 블럭 / summary / 짧은 블럭 제외
        # force(수동 생성)면 길이 임계값을 우회한다(빈 content 는 여전히 제외).
        targets = [
            b for b in blocks
            if not b.metadata.get("nature")  # 이미 분류된 것 제외
            and b.block_type not in (BlockType.SUMMARY, BlockType.DIVIDER)
            and b.content
            and (force or len(b.content) >= 20)  # 너무 짧은 블럭 제외(force 시 우회)
        ]

        if not targets:
            return blocks

        sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)
        success = 0
        failed = 0

        async def _classify_one(block: BlockObject) -> None:
            nonlocal success, failed
            async with sem:
                try:
                    await self._classify_block(block)
                    success += 1
                except Exception as exc:
                    failed += 1
                    log.debug(
                        "ontology_classify_failed",
                        block_id=str(block.id),
                        error=str(exc),
                    )

        await asyncio.gather(*[_classify_one(b) for b in targets])

        log.info(
            "ontology_classification_complete",
            total=len(targets),
            success=success,
            failed=failed,
        )
        return blocks

    async def _classify_block(self, block: BlockObject) -> None:
        """단일 블럭 분류."""
        prompt = _CLASSIFY_PROMPT.format(
            doc_type=self._doc_type,
            title=self._doc_title or "제목 없음",
            block_type=block.block_type.value,
            content=block.content[:500],
        )

        raw = await self._call_llm(prompt)
        parsed = self._parse_json(raw)
        if not isinstance(parsed, dict):
            return

        # nature
        nature = parsed.get("nature", "")
        if nature in _VALID_NATURES:
            block.metadata["nature"] = nature

        # time_reference
        time_ref = parsed.get("time_reference", {})
        if isinstance(time_ref, dict) and time_ref:
            block.metadata["time_reference"] = time_ref

        # entities (structured)
        entities = parsed.get("entities", {})
        if isinstance(entities, dict):
            # 기존 entities가 있으면 병합, 없으면 설정
            existing = block.metadata.get("entities")
            if isinstance(existing, dict):
                # 각 entity type별 병합
                for key in ("speakers", "people", "orgs", "locations"):
                    new_list = entities.get(key, [])
                    old_list = existing.get(key, [])
                    if isinstance(new_list, list) and isinstance(old_list, list):
                        # 중복 제거 + 병합
                        merged_list = list({*old_list, *new_list})
                        existing[key] = merged_list
                block.metadata["entities"] = existing
            else:
                block.metadata["entities"] = entities

        # confidence
        confidence = parsed.get("confidence", 0.0)
        if isinstance(confidence, (int, float)):
            block.metadata["classification_confidence"] = float(confidence)

        # reasoning
        reasoning = parsed.get("reasoning", "")
        if reasoning:
            block.metadata["classification_reasoning"] = str(reasoning)

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 호출 (OpenAI 호환 / Anthropic)."""
        # OpenAI 호환 (vLLM, Gemma)
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                from src.common.config import settings
                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
                response = await self._llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=512,
                )
                text = response.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

            if isinstance(self._llm_client, OpenAI):
                from src.common.config import settings
                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
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
        if "```" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]

        try:
            result = json.loads(cleaned)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None
