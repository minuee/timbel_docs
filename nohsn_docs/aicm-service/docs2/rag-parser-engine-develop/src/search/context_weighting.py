"""대화 컨텍스트 가중 검색 — 현재 발화 dense 벡터에 이전 맥락 벡터를 저가중 융합.

reformulate(LLM) 없이 현재 발화가 검색을 지배하고 이전 발화는 약한 보정만 하도록 한다.
설계: docs/superpowers/specs/2026-06-16-context-weighted-colbot-search-design.md
"""
from __future__ import annotations

import hashlib
import json


def build_context_text(
    conversation_history: list[dict] | None,
    max_turns: int = 3,
) -> str:
    """대화 이력에서 최근 max_turns 턴(=user+assistant)의 content를 공백 결합.

    이력 없음/빈 값이면 빈 문자열. 1턴=2메시지로 보고 최근 max_turns*2 메시지를 취한다.
    """
    if not conversation_history:
        return ""
    msgs = conversation_history[-(max_turns * 2):]
    parts = [str(m.get("content", "")).strip() for m in msgs if m.get("content")]
    return " ".join(p for p in parts if p)


def combine_dense_vectors(
    primary: list[float],
    context: list[float],
    w_c: float = 0.8,
    w_p: float = 0.2,
) -> list[float]:
    """현재 발화 dense 벡터(primary)와 이전 맥락 벡터(context)를 요소별 가중 결합.

    q = w_c * primary + w_p * context
    - context 가 비었거나 길이가 primary 와 다르면 primary 를 그대로 반환(안전 폴백).
    - dense collection 은 Cosine 거리이므로 정규화 불필요(방향만 의미).
    """
    if not context or len(context) != len(primary):
        return primary
    return [w_c * p + w_p * c for p, c in zip(primary, context)]


def build_anchor_query_text(
    current_query: str,
    conversation_history: list[dict] | None,
    max_user_turns: int = 3,
) -> str:
    """앵커 해석용 텍스트 — 현재 발화 + 최근 USER 발화(assistant 제외).

    봇 인사/메뉴 안내(assistant)가 여러 상품명을 나열해 앵커를 흐리는 것을 막기 위해
    role == 'user' 메시지만 사용한다. 최근 max_user_turns 개만(과거 다른 상품 잔향 약화).
    """
    parts: list[str] = []
    if conversation_history:
        user_msgs = [
            str(m.get("content", "")).strip()
            for m in conversation_history
            if m.get("role") == "user" and m.get("content")
        ]
        parts.extend(user_msgs[-max_user_turns:])
    cur = (current_query or "").strip()
    if cur:
        parts.append(cur)
    return " ".join(p for p in parts if p)


def select_anchors(
    ranked: list[tuple[str, float]],
    abs_min: float,
    rel_ratio: float,
) -> list[str]:
    """제목매칭 결과에서 앵커 문서 선택.

    1) score >= abs_min 인 문서만 후보.
    2) top1 점수 대비 rel_ratio 이상인 동률군은 모두 앵커(복수 상품 비교질의 대응).
    3) 없으면 [] (앵커 없음 -> 스코프 미적용).
    """
    cands = [(d, s) for d, s in ranked if s >= abs_min]
    if not cands:
        return []
    top = max(s for _, s in cands)
    return [d for d, s in cands if s >= top * rel_ratio]


def context_fingerprint(
    conversation_history: list[dict] | None,
    w_c: float,
    w_p: float,
) -> str:
    """캐시 키용 컨텍스트 지문. 이력 content + 가중치를 해싱(16자).

    이력/가중치가 다르면 다른 키 → 이력 교차오염 방지. 이력 없으면 "".
    """
    ctx = build_context_text(conversation_history, max_turns=3)
    if not ctx:
        return ""
    blob = json.dumps(
        {"ctx": ctx, "w_c": w_c, "w_p": w_p}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
