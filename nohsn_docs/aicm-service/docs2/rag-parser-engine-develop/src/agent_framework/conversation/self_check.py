"""Self-check — 답변 후 자기 검증 (small LLM).

§C #10 (답변 자기 검증). 답변이 생성된 후, 작은 LLM 으로 핵심 사실 일관성을
1 회 확인. 불일치 시 "다시 확인해 보세요" 보강 안내를 추가하거나 SSE
self_check 이벤트로 사용자에게 알린다.

LLM 호출 1 회 늘어나므로 always-on 은 비용 — 옵션 hook 으로 호출.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from src.agent_framework.llm.json_parse import extract_json
from src.common.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SelfCheckResult:
    consistent: bool
    confidence: float  # 0~1, LLM 이 self-rate
    note: str  # 보충 안내 (consistent 가 False 일 때 사용자에게 안내)


class _LLMClient(Protocol):
    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str: ...


_SYSTEM_PROMPT = (
    "당신은 답변 자기 검증 전문가입니다. 주어진 사용자 질문 / 답변 / 사용 출처(있을 경우) "
    "삼자 사이에 명백한 사실 모순·근거 부족·논리적 비약이 있는지 한국어로 평가합니다. "
    "JSON 한 줄만 출력하세요. 형식: "
    '{"consistent": true|false, "confidence": 0.0~1.0, "note": "한 문장 설명"}'
)


class SelfCheck:
    """답변 후 자기 검증 wrapper."""

    def __init__(self, llm: _LLMClient | None):
        self.llm = llm

    async def check(
        self,
        *,
        question: str,
        answer: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> SelfCheckResult:
        """LLM 미주입 시 (테스트 등) 보수적으로 consistent=True / 안내 없음."""
        if self.llm is None:
            return SelfCheckResult(consistent=True, confidence=1.0, note="")

        cite_block = ""
        if citations:
            try:
                cite_block = "\n\n[출처]\n" + json.dumps(
                    citations[:5], ensure_ascii=False
                )
            except (TypeError, ValueError):
                cite_block = ""

        user = f"[질문]\n{question}\n\n[답변]\n{answer}{cite_block}"
        try:
            raw = await self.llm.complete(
                _SYSTEM_PROMPT, user, response_format="json"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("self_check_llm_failed", error=str(e))
            return SelfCheckResult(consistent=True, confidence=0.5, note="")

        try:
            parsed = extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("self_check_parse_failed", error=str(e))
            return SelfCheckResult(consistent=True, confidence=0.5, note="")
        if not isinstance(parsed, dict):
            return SelfCheckResult(consistent=True, confidence=0.5, note="")

        consistent = bool(parsed.get("consistent", True))
        try:
            conf = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        note = str(parsed.get("note", "") or "")[:240]
        return SelfCheckResult(consistent=consistent, confidence=conf, note=note)
