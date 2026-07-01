"""블럭 → 카테고리 매핑기 (LLM 기반).

테넌트의 카테고리 트리를 받아서 각 블럭이 어떤 카테고리에 속하는지
LLM으로 분류하고 domain_category_ids에 저장한다.

임베딩 기반 1차 필터 + LLM 재분류로 정확도/속도 균형.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any
from uuid import UUID

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType

log = get_logger(__name__)

_MAPPING_CONCURRENCY = 8
_TOP_K_CANDIDATES = 3  # 임베딩으로 top-3 후보 선정 후 LLM 재분류
_EMBEDDING_THRESHOLD = 0.25  # 카테고리 매칭 최소 유사도
_MAX_CATEGORIES_PER_BLOCK = 2  # 한 블럭당 최대 2개 카테고리


class CategoryMapper:
    """블럭을 테넌트의 카테고리에 매핑한다."""

    def __init__(
        self,
        llm_client: Any | None = None,
        categories: list[dict] | None = None,
    ) -> None:
        """초기화.

        Args:
            llm_client: LLM 클라이언트 (AsyncOpenAI 등)
            categories: [{"id": UUID, "name": str, "description": str, "embedding": [float]}]
        """
        self._llm_client = llm_client
        self._categories = categories or []

    async def map_all(self, blocks: list[BlockObject]) -> list[BlockObject]:
        """모든 블럭에 카테고리 매핑을 적용한다."""
        if not self._categories:
            log.debug("category_mapper_no_categories")
            return blocks

        # 매핑 대상 필터
        targets = [
            b for b in blocks
            if b.block_type not in (BlockType.SUMMARY, BlockType.DIVIDER)
            and b.content
            and len(b.content) >= 30
            and not b.metadata.get("domain_category_ids")  # 이미 매핑됨
        ]

        if not targets:
            return blocks

        # 1단계: 임베딩 기반 후보 필터링 (블럭에 dense_vector가 있으면)
        sem = asyncio.Semaphore(_MAPPING_CONCURRENCY)
        success = 0
        failed = 0

        async def _map_one(block: BlockObject) -> None:
            nonlocal success, failed
            async with sem:
                try:
                    candidates = self._find_candidates(block)
                    if not candidates:
                        return

                    # LLM 재분류 (후보가 2개 이상일 때만 LLM 호출)
                    if self._llm_client is not None and len(candidates) > 1:
                        selected = await self._llm_classify(block, candidates)
                    else:
                        selected = candidates[:_MAX_CATEGORIES_PER_BLOCK]

                    if selected:
                        block.metadata["domain_category_ids"] = [
                            {"id": str(c["id"]), "name": c["name"]}
                            for c in selected
                        ]
                    success += 1
                except Exception as exc:
                    failed += 1
                    log.debug("category_mapping_failed", error=str(exc))

        await asyncio.gather(*[_map_one(b) for b in targets])

        log.info(
            "category_mapping_complete",
            total=len(targets),
            categories_available=len(self._categories),
            success=success,
            failed=failed,
        )
        return blocks

    def _find_candidates(self, block: BlockObject) -> list[dict]:
        """임베딩 기반 상위 N개 카테고리 후보 반환.

        블럭에 dense_vector가 없으면 name/description 키워드 매칭 사용.
        """
        if block.dense_vector:
            # 임베딩 코사인 유사도
            scored: list[tuple[float, dict]] = []
            for cat in self._categories:
                cat_vec = cat.get("embedding")
                if not cat_vec or not isinstance(cat_vec, list):
                    continue
                sim = _cosine(block.dense_vector, cat_vec)
                if sim >= _EMBEDDING_THRESHOLD:
                    scored.append((sim, cat))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [c for _, c in scored[:_TOP_K_CANDIDATES]]
        else:
            # Keyword fallback — 카테고리 name/synonyms가 블럭 content에 포함되면 후보
            content_lower = block.content.lower()
            candidates: list[dict] = []
            for cat in self._categories:
                name = cat.get("name", "").lower()
                synonyms = cat.get("synonyms", []) or []
                match = False
                if name and name in content_lower:
                    match = True
                else:
                    for syn in synonyms:
                        if isinstance(syn, str) and syn.lower() in content_lower:
                            match = True
                            break
                if match:
                    candidates.append(cat)
                    if len(candidates) >= _TOP_K_CANDIDATES:
                        break
            return candidates

    async def _llm_classify(
        self, block: BlockObject, candidates: list[dict]
    ) -> list[dict]:
        """LLM으로 후보 중 가장 적합한 카테고리 선택."""
        candidate_list = "\n".join([
            f"- [{c['name']}] {c.get('description', '')}"
            for c in candidates
        ])

        prompt = f"""다음 블럭 내용을 읽고 가장 적합한 카테고리를 선택하세요 (최대 2개).

## 블럭 내용
{block.content[:500]}

## 후보 카테고리
{candidate_list}

## 규칙
- 반드시 위 후보 중에서만 선택
- 관련도 낮으면 빈 배열 반환
- 최대 2개까지만

JSON만 반환:
{{"selected": ["카테고리명1", "카테고리명2"]}}"""

        try:
            raw = await self._call_llm(prompt)
            parsed = self._parse_json(raw)
            if not isinstance(parsed, dict):
                return candidates[:1]

            selected_names = parsed.get("selected", [])
            if not isinstance(selected_names, list):
                return candidates[:1]

            # 카테고리명 → 객체 매핑
            name_to_cat = {c["name"]: c for c in candidates}
            result = []
            for name in selected_names[:_MAX_CATEGORIES_PER_BLOCK]:
                if isinstance(name, str) and name in name_to_cat:
                    result.append(name_to_cat[name])
            return result or candidates[:1]
        except Exception as exc:
            log.debug("category_llm_classify_failed", error=str(exc))
            return candidates[:1]

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
                    max_tokens=150,
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


def _cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def load_tenant_categories(repository_id: UUID) -> list[dict]:
    """저장소의 카테고리 목록과 임베딩을 DB에서 로드한다."""
    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT id, name, description, synonyms, embedding
                    FROM categories
                    WHERE repository_id = :rid
                    AND (deprecated_at IS NULL)
                    ORDER BY name
                """),
                {"rid": str(repository_id)},
            )
            rows = result.fetchall()
            categories = []
            for row in rows:
                cat = {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2] or "",
                    "synonyms": row[3] or [],
                }
                if row[4]:
                    cat["embedding"] = row[4]
                categories.append(cat)
            return categories
    except Exception as exc:
        log.debug("load_tenant_categories_failed", error=str(exc))
        return []
