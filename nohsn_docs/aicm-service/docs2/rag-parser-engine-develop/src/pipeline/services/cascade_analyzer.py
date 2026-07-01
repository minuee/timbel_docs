"""Cascade Impact Analyzer -- Transition Event의 영향 범위를 분석한다.

LLM(Gemma 4)이 전환 이벤트를 분석하여:
1. 1차 영향: 직접 관련 블럭 (같은 도메인/카테고리)
2. 2차 영향: 간접 관련 블럭 (엔터티/키워드 교차)
3. 각 블럭의 권장 액션 (historical/archived/active 유지)
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.common.config import settings
from src.common.logging import get_logger
from src.core.models.block import Block
from src.core.models.transition import TransitionEvent

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 결과 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class BlockImpact:
    """개별 블럭에 대한 영향 분석 결과."""

    block_id: uuid.UUID
    impact_level: str  # "primary" | "secondary"
    recommended_action: str  # "historical" | "archived" | "active"
    reason: str = ""


@dataclass
class CascadeResult:
    """캐스케이드 분석 전체 결과."""

    primary_blocks: list[BlockImpact] = field(default_factory=list)
    secondary_blocks: list[BlockImpact] = field(default_factory=list)
    total_affected: int = 0
    recommended_actions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능한 dict로 변환한다."""
        return {
            "primary_blocks": [
                {
                    "block_id": str(b.block_id),
                    "impact_level": b.impact_level,
                    "recommended_action": b.recommended_action,
                    "reason": b.reason,
                }
                for b in self.primary_blocks
            ],
            "secondary_blocks": [
                {
                    "block_id": str(b.block_id),
                    "impact_level": b.impact_level,
                    "recommended_action": b.recommended_action,
                    "reason": b.reason,
                }
                for b in self.secondary_blocks
            ],
            "total_affected": self.total_affected,
            "recommended_actions": self.recommended_actions,
        }


# ---------------------------------------------------------------------------
# Cascade Analyzer
# ---------------------------------------------------------------------------


class CascadeAnalyzer:
    """전환 이벤트의 캐스케이드 영향을 분석한다.

    1차 영향은 키워드/카테고리 매칭으로 결정하고,
    2차 영향은 LLM(Gemma 4 via vLLM)을 사용하여 간접 관련 블럭을 식별한다.
    """

    # 1차 분석에서 LLM에 보낼 최대 블럭 수 (토큰 제한)
    MAX_BLOCKS_FOR_LLM: int = 200

    def __init__(self, llm_url: str | None = None, llm_model: str | None = None) -> None:
        self._llm_url = llm_url or settings.VLLM_URL
        self._llm_model = llm_model or "google/gemma-3-27b-it"

    async def analyze(
        self,
        event: TransitionEvent,
        blocks: list[Block],
    ) -> CascadeResult:
        """전환 이벤트의 영향을 분석한다.

        Args:
            event: 분석 대상 전환 이벤트
            blocks: 테넌트의 모든 active 블럭

        Returns:
            CascadeResult: 1차/2차 영향 블럭 및 권장 액션
        """
        # 1차 영향: 키워드/카테고리/도메인 매칭
        primary = self._find_primary_impact(event, blocks)
        primary_ids = {b.block_id for b in primary}

        # 1차에 해당하지 않는 블럭들만 2차 분석 대상
        remaining = [b for b in blocks if b.id not in primary_ids]

        # 2차 영향: LLM 분석 (1차 영향과 연관된 다른 블럭)
        secondary = await self._find_secondary_impact(event, primary, remaining)

        total = len(primary) + len(secondary)
        actions = self._build_recommended_actions(event, primary, secondary)

        return CascadeResult(
            primary_blocks=primary,
            secondary_blocks=secondary,
            total_affected=total,
            recommended_actions=actions,
        )

    def _find_primary_impact(
        self,
        event: TransitionEvent,
        blocks: list[Block],
    ) -> list[BlockImpact]:
        """키워드/카테고리/도메인 매칭으로 1차 영향 블럭을 식별한다."""
        affected_domains = set(event.affected_domains or [])
        change_from_values = set(_extract_values(event.change_from or {}))
        change_to_values = set(_extract_values(event.change_to or {}))
        keywords = affected_domains | change_from_values | change_to_values

        # 이벤트 라벨에서도 키워드 추출
        if event.event_label:
            for part in event.event_label.replace("->", " ").replace("→", " ").split():
                stripped = part.strip()
                if len(stripped) >= 2:
                    keywords.add(stripped.lower())

        results: list[BlockImpact] = []
        for block in blocks:
            if block.validity_status != "active":
                continue

            content_lower = block.content.lower()
            matched_keyword = None

            # 키워드 매칭
            for kw in keywords:
                if kw.lower() in content_lower:
                    matched_keyword = kw
                    break

            # 도메인 카테고리 매칭
            domain_match = False
            if block.domain_category_ids and affected_domains:
                block_domains = block.domain_category_ids
                if isinstance(block_domains, list):
                    for dc in block_domains:
                        cat_id = dc.get("id", "") if isinstance(dc, dict) else str(dc)
                        if cat_id in affected_domains:
                            domain_match = True
                            break

            # 엔터티 매칭
            entity_match = False
            if block.entities:
                entities = block.entities
                for entity_list in entities.values():
                    if isinstance(entity_list, list):
                        for ent in entity_list:
                            ent_lower = str(ent).lower()
                            for kw in keywords:
                                if kw.lower() in ent_lower:
                                    entity_match = True
                                    break
                            if entity_match:
                                break
                    if entity_match:
                        break

            if matched_keyword or domain_match or entity_match:
                reason_parts = []
                if matched_keyword:
                    reason_parts.append(f"키워드 '{matched_keyword}' 매칭")
                if domain_match:
                    reason_parts.append("도메인 카테고리 매칭")
                if entity_match:
                    reason_parts.append("엔터티 매칭")

                results.append(
                    BlockImpact(
                        block_id=block.id,
                        impact_level="primary",
                        recommended_action="historical",
                        reason=", ".join(reason_parts),
                    )
                )

        return results

    async def _find_secondary_impact(
        self,
        event: TransitionEvent,
        primary: list[BlockImpact],
        remaining_blocks: list[Block],
    ) -> list[BlockImpact]:
        """LLM을 사용하여 2차 영향 블럭을 식별한다.

        1차 영향 블럭과 의미적으로 관련된 나머지 블럭을 분석한다.
        """
        if not remaining_blocks or not primary:
            return []

        # LLM 분석 대상 블럭 수 제한
        candidates = remaining_blocks[: self.MAX_BLOCKS_FOR_LLM]

        block_summaries = "\n".join(
            f"- [{i}] block_id={b.id}, type={b.block_type}, "
            f"content_preview={b.content[:100]}..."
            for i, b in enumerate(candidates)
        )

        prompt = f"""전환 이벤트를 분석하세요.

이벤트: {event.event_label}
변경: {json.dumps(event.change_from or {}, ensure_ascii=False)} → {json.dumps(event.change_to or {}, ensure_ascii=False)}
영향 도메인: {event.affected_domains or []}

이미 1차 영향으로 분류된 블럭이 {len(primary)}개 있습니다.
아래 블럭들 중 이 전환에 간접적으로 영향을 받는 것을 식별하세요.
각 블럭에 권장 액션을 제시하세요.

블럭 목록:
{block_summaries}

JSON 배열로만 반환하세요 (다른 텍스트 없이):
[{{"index": 0, "impact": "secondary", "action": "historical", "reason": "설명"}}]

영향 없는 블럭은 포함하지 마세요. 빈 배열 []도 가능합니다."""

        try:
            llm_results = await self._call_llm(prompt)
            return self._parse_llm_results(llm_results, candidates)
        except Exception as exc:
            logger.warning(
                "llm_secondary_analysis_failed",
                error=str(exc),
                candidate_count=len(candidates),
            )
            return []

    async def _call_llm(self, prompt: str) -> list[dict[str, Any]]:
        """vLLM (OpenAI compatible) API를 호출한다."""
        url = f"{self._llm_url}/chat/completions"
        payload = {
            "model": self._llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "당신은 지식 관리 시스템의 전환 이벤트 분석 전문가입니다. "
                        "JSON 형식으로만 응답하세요."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.VLLM_API_KEY}"},
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]

        # JSON 추출 (코드 블럭 안에 있을 수도 있음)
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            # 첫 줄(```json)과 마지막 줄(```) 제거
            json_lines = [ln for ln in lines[1:] if not ln.strip().startswith("```")]
            content = "\n".join(json_lines)

        return json.loads(content)

    def _parse_llm_results(
        self,
        llm_results: list[dict[str, Any]],
        candidates: list[Block],
    ) -> list[BlockImpact]:
        """LLM 결과를 BlockImpact 리스트로 변환한다."""
        results: list[BlockImpact] = []
        for item in llm_results:
            idx = item.get("index")
            if idx is None or not isinstance(idx, int) or idx >= len(candidates):
                continue

            block = candidates[idx]
            action = item.get("action", "historical")
            if action not in ("historical", "archived", "active"):
                action = "historical"

            results.append(
                BlockImpact(
                    block_id=block.id,
                    impact_level="secondary",
                    recommended_action=action,
                    reason=item.get("reason", "LLM 2차 분석"),
                )
            )
        return results

    def _build_recommended_actions(
        self,
        event: TransitionEvent,
        primary: list[BlockImpact],
        secondary: list[BlockImpact],
    ) -> dict[str, list[dict[str, Any]]]:
        """영향 블럭들을 권장 액션별로 그룹화한다."""
        groups: dict[str, list[dict[str, Any]]] = {
            "historical": [],
            "archived": [],
            "active": [],
        }
        for impact in primary + secondary:
            groups.setdefault(impact.recommended_action, []).append(
                {
                    "block_id": str(impact.block_id),
                    "impact_level": impact.impact_level,
                    "reason": impact.reason,
                }
            )
        # 빈 그룹 제거
        return {k: v for k, v in groups.items() if v}


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _extract_values(d: dict[str, Any]) -> list[str]:
    """JSONB dict에서 모든 문자열 값을 추출한다."""
    values: list[str] = []
    for v in d.values():
        if isinstance(v, str):
            values.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    values.append(item)
    return values
