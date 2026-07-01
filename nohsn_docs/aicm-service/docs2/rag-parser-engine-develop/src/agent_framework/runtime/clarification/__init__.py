"""Wave 6 (D 코스) — Adaptive Behavior: Confidence × Ledger × Proactive Elicitation.

자비스의 정직한 적응 행동:
- ``confidence.self_confidence_score`` — LLM 자가 평가
- ``ledger.ConversationLedger`` — clarification_history/slot_ledger/topic_thread 의 turn-cross 영속
- ``elicitation.should_ask / pick_question / budget_check`` — 유도 질문 패턴

threshold 는 const, 분기는 prompt 가이드로 위임 (rule 금지).
"""
from src.agent_framework.runtime.clarification.confidence import (
    ConfidenceResult,
    self_confidence_score,
)
from src.agent_framework.runtime.clarification.elicitation import (
    GuidingQuestion,
    budget_check,
    ledger_apply,
    pick_question,
    should_ask,
)
from src.agent_framework.runtime.clarification.ledger import ConversationLedger

THRESHOLDS = {
    "AUTONOMOUS": 0.85,   # ≥ 자율 진행
    "VERIFICATION": 0.70,  # ≥ verification 질문
    # < 0.70: 유도 질문
}

__all__ = [
    "THRESHOLDS",
    "ConfidenceResult",
    "self_confidence_score",
    "ConversationLedger",
    "GuidingQuestion",
    "should_ask",
    "pick_question",
    "budget_check",
    "ledger_apply",
]
