"""Search Summary Generator -- 블럭별 검색 최적화 요약 생성.

각 블럭에 대해 LLM이 검색에 최적화된 1-2문장 요약을 생성한다.
생성된 요약은 block.metadata["search_summary"]에 저장되며,
embedding_text 생성 시 원본 content 앞에 결합된다.

Performance:
- 추가 LLM 호출: 1 per block
- Concurrency: env SEARCH_SUMMARY_CONCURRENCY (default 4)
- Cache: block_hash 기반
- Skip: 50자 미만 짧은 블럭
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)


def _get_concurrency() -> int:
    """env SEARCH_SUMMARY_CONCURRENCY (default 4) — D17 GPT-5 G5 반영."""
    raw = os.environ.get("SEARCH_SUMMARY_CONCURRENCY", "4")
    try:
        n = int(raw)
        return max(1, min(16, n))
    except (ValueError, TypeError):
        return 4


_MAX_CONCURRENT = _get_concurrency()
_MIN_CONTENT_LEN = 50
_SKIP_BLOCK_TYPES = frozenset({
    BlockType.SUMMARY,
    BlockType.DIVIDER,
    BlockType.TABLE_OF_CONTENTS,
})

SEARCH_SUMMARY_PROMPT = """다음 블럭 내용을 검색에 최적화된 1-2문장 요약으로 만들라.

블럭 내용:
{content}

요약 규칙:
- 핵심 키워드 포함 (검색될 가능성 높은 단어)
- 추상적 표현보다 구체적 표현
- "이 문서는...", "본 글은..." 같은 메타 표현 금지
- 1-2문장으로 압축

요약 (텍스트만):"""


class SearchSummaryGenerator:
    """블럭별 검색 최적화 요약을 LLM으로 생성한다.

    프로세스
    --------
    1. 각 블럭의 content를 LLM에 전달
    2. 검색에 최적화된 1-2문장 요약 생성
    3. block.metadata["search_summary"]에 저장
    4. embedding_text()에서 요약 + content를 결합

    최적화
    ------
    - block_hash 기반 캐시 (동일 content 중복 호출 방지)
    - 50자 미만 짧은 블럭은 건너뜀 (요약 불필요)
    - SUMMARY, DIVIDER 등 시스템 블럭 제외
    - Concurrency 8 (세마포어)
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client
        # D56 §E PR-E: Redis 기반 enricher cache (in-memory fallback 내장).
        # cfg_hash 자동 부착 — prompt/schema/model/params 변경 시 자동 invalidation.
        from src.pipeline.enrichers.cache import EnricherRedisCache
        from src.common.config import settings as _settings

        self._cache = EnricherRedisCache(
            name="search_summary",
            schema_version="v1",
            prompt_version="v1",
            prompt_text=SEARCH_SUMMARY_PROMPT,
            model_id=getattr(_settings, "VLLM_MODEL", "gemma-4-31b"),
            inference_params={"temperature": 0.2, "max_tokens": 200},
        )

    async def generate_all(self, blocks: list[BlockObject], force: bool = False) -> list[BlockObject]:
        """모든 블럭에 search_summary를 생성하여 부착한다.

        Parameters
        ----------
        blocks : list[BlockObject]
            블럭 목록

        Returns
        -------
        list[BlockObject]
            metadata["search_summary"]가 부착된 블럭 목록
        """
        if not blocks:
            return blocks

        targets = [
            b for b in blocks
            if b.block_type not in _SKIP_BLOCK_TYPES
            # force(수동 생성)면 길이 임계값을 우회한다 — 사용자가 명시적으로 요청한 블록은
            # 짧아도 생성한다. 자동 파이프라인(force=False)은 기존 임계값 유지.
            and (force or len(b.content) >= _MIN_CONTENT_LEN)
            and not b.metadata.get("search_summary")
        ]

        if not targets:
            log.debug("search_summary_no_targets", total=len(blocks))
            return blocks

        success_count = 0
        fail_count = 0
        cache_hit = 0
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _generate_one(block: BlockObject) -> None:
            nonlocal success_count, fail_count, cache_hit

            # D56 §E: Redis cache 확인 (block_hash 기반, cfg_hash 자동 부착)
            cache_key = block.block_hash or block.compute_hash()
            cached = await self._cache.get(cache_key)
            if cached is not None and isinstance(cached, str):
                block.metadata["search_summary"] = cached
                cache_hit += 1
                return

            async with sem:
                try:
                    summary = await self._generate_summary(block.content)
                    if summary:
                        block.metadata["search_summary"] = summary
                        await self._cache.set(cache_key, summary)
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as exc:
                    log.warning(
                        "search_summary_generation_failed",
                        block_id=str(block.id),
                        error=str(exc),
                    )
                    fail_count += 1

        await asyncio.gather(*[_generate_one(b) for b in targets])

        log.info(
            "search_summary_generation_complete",
            total=len(blocks),
            targets=len(targets),
            success=success_count,
            cache_hit=cache_hit,
            failed=fail_count,
        )

        return blocks

    async def _generate_summary(self, content: str) -> str:
        """단일 블럭에 대한 검색 요약을 LLM으로 생성한다."""
        if self._llm_client is not None:
            return await self._call_llm(content)

        # llm_client 없으면 LLM 라우터 사용
        return await self._call_router(content)

    async def _call_llm(self, content: str) -> str:
        """직접 주입된 LLM 클라이언트로 요약을 생성한다."""
        prompt = SEARCH_SUMMARY_PROMPT.format(content=content[:1000])

        # OpenAI 호환 (vLLM, Gemma 등)
        try:
            from openai import AsyncOpenAI, OpenAI

            if isinstance(self._llm_client, AsyncOpenAI):
                from src.common.config import settings

                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
                response = await self._llm_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=200,
                )
                text = response.choices[0].message.content or ""
                return re.sub(
                    r"<think>.*?</think>\s*", "", text, flags=re.DOTALL
                ).strip()

            if isinstance(self._llm_client, OpenAI):
                from src.common.config import settings

                model = getattr(settings, "VLLM_MODEL", "gemma-4-31b")
                response = await asyncio.to_thread(
                    self._llm_client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=200,
                )
                text = response.choices[0].message.content or ""
                return re.sub(
                    r"<think>.*?</think>\s*", "", text, flags=re.DOTALL
                ).strip()
        except ImportError:
            pass

        # D40 Phase A — VLLMAdapter 등 generic adapter 지원.
        if hasattr(self._llm_client, "generate"):
            text = await self._llm_client.generate(prompt)  # type: ignore[union-attr]
            return re.sub(
                r"<think>.*?</think>\s*", "", text, flags=re.DOTALL
            ).strip()

        raise RuntimeError("LLM 클라이언트를 사용할 수 없습니다")

    async def _call_router(self, content: str) -> str:
        """LLM 라우터를 통해 요약을 생성한다."""
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        prompt = SEARCH_SUMMARY_PROMPT.format(content=content[:1000])

        request = LLMRequest(
            prompt=prompt,
            system_prompt=(
                "당신은 검색 최적화 전문가입니다. "
                "블럭 내용을 검색에 유리한 1-2문장으로 압축합니다. "
                "요약 텍스트만 출력하세요."
            ),
            max_tokens=200,
            temperature=0.2,
        )

        response = await llm_router.route(
            task=LLMTask.METADATA_EXTRACTION,
            request=request,
        )

        return response.text.strip()
