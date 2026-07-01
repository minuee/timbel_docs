"""LLM 기반 캡션 감지기.

표/이미지 블럭의 주변 텍스트에서 캡션(제목, 출처)을 추출한다.
caption_detection.py 프롬프트를 사용.

LLM이 없으면 regex fallback.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.prompts.caption_detection import build_caption_detection_prompt

log = get_logger(__name__)

_CAPTION_CONCURRENCY = 8
_CAPTION_REGEX = re.compile(
    r"(그림|Figure|Fig\.|표|Table|사진|Photo|도표|Chart)\s*[\d]+[.:\s]*(.*)",
    re.IGNORECASE,
)


class CaptionDetector:
    """표/이미지 블럭의 캡션을 LLM으로 감지한다."""

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    async def detect_all(self, blocks: list[BlockObject]) -> list[BlockObject]:
        """모든 표/이미지 블럭에 캡션 감지 적용."""
        targets_with_context: list[tuple[int, BlockObject, str]] = []
        for i, block in enumerate(blocks):
            if block.block_type not in (BlockType.TABLE, BlockType.IMAGE):
                continue
            if block.metadata.get("caption"):  # 이미 감지됨
                continue

            # 전후 컨텍스트 수집 (직전/직후 블럭 200자씩)
            context_parts: list[str] = []
            for neighbor_idx in [i - 1, i + 1]:
                if 0 <= neighbor_idx < len(blocks):
                    neighbor = blocks[neighbor_idx]
                    if neighbor.block_type in (BlockType.TABLE, BlockType.IMAGE):
                        continue
                    snippet = neighbor.content.strip()[:300]
                    if snippet:
                        context_parts.append(snippet)

            context_text = "\n".join(context_parts)
            if not context_text:
                continue

            targets_with_context.append((i, block, context_text))

        if not targets_with_context:
            return blocks

        # LLM 병렬 감지 (llm_client 있을 때)
        if self._llm_client is not None:
            sem = asyncio.Semaphore(_CAPTION_CONCURRENCY)

            async def _detect_one(block: BlockObject, context: str) -> None:
                element_type = "table" if block.block_type == BlockType.TABLE else "image"
                async with sem:
                    try:
                        caption = await self._detect_with_llm(context, element_type)
                        if caption:
                            block.metadata["caption"] = caption
                            block.metadata["caption_source"] = "llm"
                    except Exception as exc:
                        log.debug("caption_llm_failed", error=str(exc))
                        # LLM 실패 시 regex fallback
                        caption = self._detect_with_regex(context)
                        if caption:
                            block.metadata["caption"] = caption
                            block.metadata["caption_source"] = "regex_fallback"

            await asyncio.gather(
                *[_detect_one(b, c) for _, b, c in targets_with_context]
            )
        else:
            # LLM 없음 → regex only
            for _, block, context in targets_with_context:
                caption = self._detect_with_regex(context)
                if caption:
                    block.metadata["caption"] = caption
                    block.metadata["caption_source"] = "regex"

        detected_count = sum(1 for b in blocks if b.metadata.get("caption"))
        log.info(
            "caption_detection_complete",
            total_candidates=len(targets_with_context),
            detected=detected_count,
            llm_used=self._llm_client is not None,
        )
        return blocks

    async def _detect_with_llm(self, context: str, element_type: str) -> str:
        """LLM으로 캡션 감지."""
        prompt = build_caption_detection_prompt(context, element_type)
        raw = await self._call_llm(prompt)
        parsed = self._parse_json(raw)
        if isinstance(parsed, dict):
            caption = parsed.get("caption")
            if isinstance(caption, str) and caption.strip():
                return caption.strip()
        return ""

    @staticmethod
    def _detect_with_regex(context: str) -> str:
        """Regex fallback — 첫 줄에서 캡션 패턴 찾기."""
        for line in context.split("\n"):
            line = line.strip()
            if 5 < len(line) < 200:
                if _CAPTION_REGEX.match(line):
                    return line
        return ""

    async def _call_llm(self, prompt: str) -> str:
        """LLM API 호출."""
        try:
            from openai import AsyncOpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                from src.common.config import settings
                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
                response = await self._llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=200,
                )
                text = response.choices[0].message.content or ""
                return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
        except ImportError:
            pass

        # D40 Phase A — VLLMAdapter 등 generic adapter 지원.
        if hasattr(self._llm_client, "generate"):
            text = await self._llm_client.generate(prompt)  # type: ignore[union-attr]
            return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()

        raise RuntimeError("LLM 클라이언트 없음")

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        cleaned = raw.strip()
        if "```" in cleaned:
            s = cleaned.find("{")
            e = cleaned.rfind("}")
            if s >= 0 and e > s:
                cleaned = cleaned[s : e + 1]
        try:
            result = json.loads(cleaned)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None
