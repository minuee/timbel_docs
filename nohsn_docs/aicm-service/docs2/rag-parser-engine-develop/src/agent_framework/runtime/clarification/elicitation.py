"""Proactive Elicitation — 유도 질문 패턴 (단순 "모릅니다" 금지).

- ``should_ask`` — confidence + ledger 보고 질문 필요 여부 판단
- ``pick_question`` — 유도 질문 LLM 생성 (옵션 + 이유 + prefix)
- ``budget_check`` — 한 발화 ≤ 1 질문, turn 누적 ≤ 2
- ``ledger_apply`` — 사용자 답변 ledger 에 누적
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog

from src.agent_framework.llm.json_parse import extract_json

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "guiding_question.md"

_BUDGET_PER_UTTERANCE = 1
_BUDGET_PER_TURN = 2


@dataclass
class GuidingQuestion:
    question_text: str
    options: list[str] = field(default_factory=list)
    reason: str = ""
    prefix: str | None = None
    kind: Literal["verification", "guided"] = "guided"


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return "유도 질문 생성. JSON: {question_text, options, reason, prefix, kind}."


def budget_check(
    *,
    asked_in_current_utterance: int,
    asked_in_current_turn: int,
) -> bool:
    """budget 안 남았으면 True (질문 가능)."""
    if asked_in_current_utterance >= _BUDGET_PER_UTTERANCE:
        return False
    if asked_in_current_turn >= _BUDGET_PER_TURN:
        return False
    return True


async def should_ask(
    *,
    confidence: float,
    new_intent: dict[str, Any],
    ledger: Any,  # ConversationLedger
    llm_client: Any,
    autonomous_threshold: float = 0.85,
    verification_threshold: float = 0.70,
) -> dict[str, Any]:
    """confidence 기반 분기 + ledger 의미 매칭.

    반환: ``{action: "autonomous" | "verification" | "guided" | "ledger_hit",
              ledger_match: dict, reason: str}``
    """
    if confidence >= autonomous_threshold:
        return {"action": "autonomous", "ledger_match": None,
                "reason": f"confidence {confidence:.2f} ≥ {autonomous_threshold}"}

    # ledger 먼저 — 이미 답변 받은 슬롯/토픽이면 재질문 X
    match = await ledger.semantic_match(new_intent=new_intent, llm_client=llm_client)
    if match.get("matched"):
        return {"action": "ledger_hit", "ledger_match": match,
                "reason": match.get("similarity_reason", "matched")}

    if confidence >= verification_threshold:
        return {"action": "verification", "ledger_match": match,
                "reason": f"confidence {confidence:.2f} 0.7~0.85"}
    return {"action": "guided", "ledger_match": match,
            "reason": f"confidence {confidence:.2f} < {verification_threshold}"}


async def pick_question(
    *,
    missing_info: str,
    ledger: Any,
    persona: dict | None,
    threshold_stage: Literal["verification", "guided"],
    llm_client: Any,
) -> GuidingQuestion | None:
    """LLM 으로 유도 질문 생성. 실패 시 fallback "조금 더 알려주실 수 있나요?" """
    if llm_client is None:
        return GuidingQuestion(
            question_text=("이 부분이 정확하지 않아요. 조금 더 알려주실 수 있을까요?"
                           if threshold_stage == "guided" else "이렇게 이해했는데, 맞을까요?"),
            options=[],
            reason=missing_info or "정보 부족",
            prefix=None,
            kind=threshold_stage,
        )
    import json as _json
    base = _load_prompt()
    user = (
        f"{base}\n\n"
        f"## missing_info\n{missing_info or '(미상)'}\n\n"
        f"## ledger_recent\n```json\n{_json.dumps(ledger.history[-5:], ensure_ascii=False, indent=2)}\n```\n\n"
        f"## persona\n```json\n{_json.dumps(persona or {}, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## threshold_stage\n{threshold_stage}\n"
    )
    try:
        raw = await llm_client.complete("JSON 형식으로만 응답.", user, response_format="json_object")
        parsed = extract_json(raw)
        if isinstance(parsed, dict) and parsed.get("question_text"):
            return GuidingQuestion(
                question_text=str(parsed.get("question_text"))[:500],
                options=[str(o)[:200] for o in (parsed.get("options") or [])][:4],
                reason=str(parsed.get("reason") or "")[:200],
                prefix=(str(parsed.get("prefix")) if parsed.get("prefix") else None),
                kind=threshold_stage,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("pick_question_failed", error=str(e))
    return GuidingQuestion(
        question_text="이 부분이 정확하지 않아요. 조금 더 알려주실 수 있을까요?",
        options=[], reason=missing_info or "정보 부족",
        prefix=None, kind=threshold_stage,
    )


def ledger_apply(
    *,
    ledger: Any,
    turn_idx: int,
    question: GuidingQuestion,
    answer: str,
    applied_skill: str | None,
    applied_slot: str | None,
    confidence: float,
) -> None:
    """사용자 답변을 ledger.history + slot_ledger 에 누적."""
    ledger.apply_user_answer(
        turn_idx=turn_idx,
        question=question.question_text,
        answer=answer,
        applied_skill=applied_skill,
        applied_slot=applied_slot,
        confidence=confidence,
    )
