"""self-confidence 자가 평가 — 각 LLM 단계 (extract/distill/synthesize/answer/...) 에 호출.

쓰임:
- engine 의 답변 송출 사이 hook 이 호출 → 결과 .confidence 로 분기
- synthesizer 가 통합 답변 후 자체 평가 (이미 prompt 안에 confidence 출력 포함되므로 중복 호출 불필요)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from src.agent_framework.llm.json_parse import extract_json

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "confidence_assess.md"


@dataclass
class ConfidenceResult:
    confidence: float
    reason: str
    missing_info: str | None
    stage: str


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return "self-confidence 평가. JSON: {confidence, reason, missing_info}."


async def self_confidence_score(
    *,
    stage: str,
    output: Any,
    context: Any = None,
    grounding_used: list[str] | None = None,
    llm_client: Any,
) -> ConfidenceResult:
    """LLM 자가 평가. LLM 미주입 또는 실패 시 confidence=0.5 (중립) 로 fallback."""
    if llm_client is None:
        return ConfidenceResult(confidence=0.5, reason="no_llm", missing_info=None, stage=stage)

    import json as _json
    base = _load_prompt()
    try:
        out_str = _json.dumps(output, ensure_ascii=False, default=str)[:2000]
    except (TypeError, ValueError):
        out_str = str(output)[:2000]
    try:
        ctx_str = _json.dumps(context, ensure_ascii=False, default=str)[:2000]
    except (TypeError, ValueError):
        ctx_str = str(context)[:2000] if context else "(없음)"
    grounding_str = _json.dumps(grounding_used or [], ensure_ascii=False)

    user = (
        f"{base}\n\n## stage\n{stage}\n\n"
        f"## output\n```json\n{out_str}\n```\n\n"
        f"## context\n```json\n{ctx_str}\n```\n\n"
        f"## grounding_used\n{grounding_str}\n"
    )
    try:
        raw = await llm_client.complete("JSON 형식으로만 응답.", user, response_format="json_object")
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            conf = float(parsed.get("confidence") or 0.0)
            conf = max(0.0, min(1.0, conf))
            reason = str(parsed.get("reason") or "")[:300]
            missing = parsed.get("missing_info")
            missing = str(missing)[:300] if missing else None
            return ConfidenceResult(
                confidence=conf, reason=reason, missing_info=missing, stage=stage
            )
    except Exception as e:  # noqa: BLE001
        log.warning("confidence_assess_failed", error=str(e), stage=stage)
    return ConfidenceResult(confidence=0.5, reason="parse_failed", missing_info=None, stage=stage)
