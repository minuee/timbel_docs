"""대화 히스토리 기반 질의 보강 — 멀티턴 대화에서 문맥적 참조를 해석."""

from __future__ import annotations

from src.common.logging import get_logger
from src.integration.rag_api.models import ConversationTurn

log = get_logger(__name__)

# 보강에 사용할 최대 턴 수
MAX_HISTORY_TURNS = 5

# 대화 참조 패턴 (한국어 + 영어)
_REFERENCE_PATTERNS = [
    "그거",
    "그것",
    "이거",
    "이것",
    "저거",
    "저것",
    "위에",
    "아까",
    "방금",
    "다른 건",
    "다른 거",
    "그 외",
    "추가로",
    "더",
    "말고",
    "대신",
    "it",
    "that",
    "this",
    "those",
    "above",
    "previous",
    "other",
]


def enrich_with_history(
    question: str,
    conversation_history: list[ConversationTurn] | list[dict],
) -> str:
    """대화 히스토리를 활용하여 현재 질문을 보강한다.

    현재 질문에 참조적 표현("그거 말고 다른 건?", "더 알려줘")이 포함된 경우,
    최근 대화 턴에서 맥락을 추출하여 질문을 보강한다.

    Args:
        question: 현재 사용자 질문
        conversation_history: 이전 대화 턴 리스트

    Returns:
        보강된 질문 문자열. 보강 불필요 시 원본 질문 그대로 반환.
    """
    if not conversation_history:
        return question

    # dict → ConversationTurn 변환
    turns: list[ConversationTurn] = []
    for item in conversation_history:
        if isinstance(item, dict):
            turns.append(ConversationTurn(**item))
        else:
            turns.append(item)

    # 최근 N턴만 사용
    recent_turns = turns[-MAX_HISTORY_TURNS:]

    # 참조적 표현 존재 여부 확인
    if not _has_reference_pattern(question):
        # 참조 표현이 없어도, 짧은 질문(5단어 이하)이면 맥락 보강
        if len(question.split()) > 5:
            return question

    # 대화 맥락 요약 구성
    context_parts: list[str] = []
    for turn in recent_turns:
        role_label = "사용자" if turn.role == "user" else "어시스턴트"
        # 긴 응답은 앞부분만 사용
        content = turn.content[:300] if len(turn.content) > 300 else turn.content
        context_parts.append(f"[{role_label}] {content}")

    context_summary = "\n".join(context_parts)

    enriched = (
        f"[대화 맥락]\n{context_summary}\n\n"
        f"[현재 질문]\n{question}"
    )

    log.info(
        "query_enriched_with_history",
        original_len=len(question),
        enriched_len=len(enriched),
        history_turns=len(recent_turns),
    )

    return enriched


def _has_reference_pattern(text: str) -> bool:
    """텍스트에 참조적 표현이 있는지 확인."""
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in _REFERENCE_PATTERNS)
