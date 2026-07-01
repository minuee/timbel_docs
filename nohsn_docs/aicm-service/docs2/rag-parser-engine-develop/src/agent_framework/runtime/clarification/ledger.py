"""ConversationLedger — turn-cross 영속 (sessions.state JSONB nested).

clarification_history / slot_ledger / topic_thread 의 record/lookup/apply API.
LLM 의미 비교 (semantic_match) 로 같은 슬롯 반복 질문 차단.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from src.agent_framework.llm.json_parse import extract_json

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "ledger_match.md"

# 메모리·DB 부담 줄이기 — record 누적 LRU 한도
_MAX_HISTORY = 50
_MAX_TOPICS = 50


@dataclass
class ClarificationRecord:
    turn_idx: int
    asked: str
    answered: str | None = None
    applied_skill: str | None = None
    applied_slot: str | None = None
    confidence: float = 0.0
    ts: str = ""


@dataclass
class SlotValue:
    value: Any
    source_turn: int
    confidence: float
    ts: str = ""


@dataclass
class TopicTurn:
    turn_idx: int
    topic: str
    entities: list[str] = field(default_factory=list)
    persona_state: str | None = None
    ts: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return "ledger 의미 매칭. JSON: {matched, matched_record_type, matched_record_idx, matched_value, similarity_reason}."


class ConversationLedger:
    """SessionState 의 ledger 필드 wrapping. 인스턴스 자체는 가벼운 facade."""

    def __init__(self, state: Any):
        self.state = state  # SessionState

    @property
    def history(self) -> list[dict]:
        return getattr(self.state, "clarification_history", [])

    @property
    def slots(self) -> dict[str, dict[str, Any]]:
        return getattr(self.state, "slot_ledger", {})

    @property
    def topics(self) -> list[dict]:
        return getattr(self.state, "topic_thread", [])

    # ------------------------- record -------------------------

    def record_clarification(
        self,
        *,
        turn_idx: int,
        asked: str,
        answered: str | None,
        applied_skill: str | None,
        applied_slot: str | None,
        confidence: float,
    ) -> None:
        rec = ClarificationRecord(
            turn_idx=turn_idx, asked=asked, answered=answered,
            applied_skill=applied_skill, applied_slot=applied_slot,
            confidence=confidence, ts=_now_iso(),
        )
        self.history.append(rec.__dict__)
        # LRU
        if len(self.history) > _MAX_HISTORY:
            del self.history[: len(self.history) - _MAX_HISTORY]

    def record_slot(
        self,
        *,
        skill_name: str,
        slot_name: str,
        value: Any,
        source_turn: int,
        confidence: float,
    ) -> None:
        if skill_name not in self.slots:
            self.slots[skill_name] = {}
        self.slots[skill_name][slot_name] = {
            "value": value,
            "source_turn": source_turn,
            "confidence": confidence,
            "ts": _now_iso(),
        }

    def record_topic(
        self,
        *,
        turn_idx: int,
        topic: str,
        entities: list[str] | None = None,
        persona_state: str | None = None,
    ) -> None:
        rec = TopicTurn(
            turn_idx=turn_idx, topic=topic,
            entities=list(entities or []), persona_state=persona_state,
            ts=_now_iso(),
        )
        self.topics.append(rec.__dict__)
        if len(self.topics) > _MAX_TOPICS:
            del self.topics[: len(self.topics) - _MAX_TOPICS]

    # ------------------------- lookup -------------------------

    def lookup_slot(self, skill_name: str, slot_name: str) -> dict[str, Any] | None:
        return (self.slots.get(skill_name) or {}).get(slot_name)

    async def semantic_match(
        self,
        *,
        new_intent: dict[str, Any],
        llm_client: Any,
    ) -> dict[str, Any]:
        """LLM 의 ledger_match.md 로 의미 일치 여부 판단. 빈 ledger 면 matched=False.

        반환: ``{matched, matched_record_type, matched_record_idx, matched_value, similarity_reason}``
        """
        if not (self.history or self.slots or self.topics):
            return {
                "matched": False,
                "matched_record_type": None,
                "matched_record_idx": None,
                "matched_value": None,
                "similarity_reason": "empty_ledger",
            }
        if llm_client is None:
            return {
                "matched": False,
                "matched_record_type": None,
                "matched_record_idx": None,
                "matched_value": None,
                "similarity_reason": "no_llm",
            }

        import json as _json
        base = _load_prompt()
        recent_hist = self.history[-10:] if self.history else []
        recent_topics = self.topics[-10:] if self.topics else []
        user = (
            f"{base}\n\n"
            f"## new_intent\n```json\n{_json.dumps(new_intent, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## ledger_history\n```json\n{_json.dumps(recent_hist, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## ledger_slots\n```json\n{_json.dumps(self.slots, ensure_ascii=False, indent=2)[:2000]}\n```\n\n"
            f"## ledger_topics\n```json\n{_json.dumps(recent_topics, ensure_ascii=False, indent=2)}\n```\n"
        )
        try:
            raw = await llm_client.complete("JSON 형식으로만 응답.", user, response_format="json_object")
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:  # noqa: BLE001
            log.warning("ledger_match_failed", error=str(e))
        return {
            "matched": False,
            "matched_record_type": None,
            "matched_record_idx": None,
            "matched_value": None,
            "similarity_reason": "llm_error",
        }

    # ------------------------- apply -------------------------

    def apply_user_answer(
        self,
        *,
        turn_idx: int,
        question: str,
        answer: str,
        applied_skill: str | None,
        applied_slot: str | None,
        confidence: float,
    ) -> None:
        """사용자 답변을 history + (skill+slot 명시 시) slot_ledger 에 누적."""
        self.record_clarification(
            turn_idx=turn_idx, asked=question, answered=answer,
            applied_skill=applied_skill, applied_slot=applied_slot,
            confidence=confidence,
        )
        if applied_skill and applied_slot:
            self.record_slot(
                skill_name=applied_skill, slot_name=applied_slot,
                value=answer, source_turn=turn_idx, confidence=confidence,
            )
