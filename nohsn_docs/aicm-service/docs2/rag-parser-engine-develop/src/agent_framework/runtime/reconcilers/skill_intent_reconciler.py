"""skill_v2 auto-loader 와 intent_classifier 결정 mismatch 해소 — 2026-05-06 § 4.3 D.

배경 (Trace C):
  발화: "내일 병원 진료 예약을 꼭 할수 있게 메모 해줘"
  - skill_v2 auto-loader: schedule_personal (예약/내일 우세, 0ms 결정론)
  - intent_classifier: memo_capture (정답, 1.96s)
  → plan_generator 가 schedule_personal frame 으로 schedule.create plan 생성
  → DB 에 잘못된 일정 INSERT, 답변 자체 자기모순.

이 모듈은 두 결정의 cross-domain 충돌을 LLM 위임으로 해소.

GPT-5.5 권고 + 사용자 1원칙: 결정론 키워드/우선순위 룰 사용 금지. LLM 이
발화 안의 명시적 동사 vs 암시적 신호 가중치를 *그 발화에 대해* 판정.

pre-demo: 어디서도 호출 안 됨. 단위 테스트만. dispatcher 통합은 시연 후
SKILL_INTENT_RECONCILE flag on 시.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class SkillIntentDecision:
    skill_v2: str | None
    intent_label: str | None
    conflict: bool
    resolved_skill: str | None
    confidence: float
    reason: str


class _LlmProto(Protocol):
    async def complete(self, system: str, user: str, **kwargs: Any) -> dict[str, Any]: ...


_PROMPT_SYSTEM = """\
You are a routing reconciler. The user said something, and two upstream
classifiers disagree on which skill should handle it.

Decide which skill (or 'none' if you cannot tell) best matches the *user's
explicit intent in this single utterance*.

Output strict JSON only:
{
  "resolved_skill": "<one of available_skills, or null>",
  "confidence": <0.0..1.0>,
  "reason": "<one short sentence in Korean>"
}

Rules:
- Weigh the user's explicit verb (e.g. "메모해줘", "등록해줘", "보내줘")
  more than supporting nouns/dates ("예약", "내일").
- If the verb signal is genuinely ambiguous, set resolved_skill=null and
  confidence < 0.5 — that asks the system to clarify with the user.
- Do not invent skills. resolved_skill MUST be one of available_skills or null.
"""


def _is_conflict(skill_v2: str | None, intent: str | None) -> bool:
    if skill_v2 is None or intent is None:
        return False
    return skill_v2 != intent


async def reconcile(
    user_message: str,
    skill_v2_decision: str | None,
    intent_label: str | None,
    available_skills: list[str],
    *,
    llm: _LlmProto,
) -> SkillIntentDecision:
    if not _is_conflict(skill_v2_decision, intent_label):
        return SkillIntentDecision(
            skill_v2=skill_v2_decision,
            intent_label=intent_label,
            conflict=False,
            resolved_skill=skill_v2_decision or intent_label,
            confidence=1.0 if skill_v2_decision else 0.0,
            reason="비충돌 — passthrough",
        )

    user_payload = (
        f"user_message: {user_message}\n"
        f"skill_v2_decision: {skill_v2_decision}\n"
        f"intent_classifier: {intent_label}\n"
        f"available_skills: {available_skills}\n"
    )

    try:
        resp = await llm.complete(_PROMPT_SYSTEM, user_payload, response_format="json_object")
        content = resp["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise TypeError(f"reconciler LLM returned non-dict JSON: {type(parsed).__name__}")
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError, AttributeError) as e:
        return SkillIntentDecision(
            skill_v2=skill_v2_decision,
            intent_label=intent_label,
            conflict=True,
            resolved_skill=None,
            confidence=0.0,
            reason=f"reconciler LLM parse fallback: {type(e).__name__}",
        )

    resolved = parsed.get("resolved_skill")
    if resolved is not None and resolved not in available_skills:
        # LLM 이 발명한 skill — 안전 fallback.
        return SkillIntentDecision(
            skill_v2=skill_v2_decision,
            intent_label=intent_label,
            conflict=True,
            resolved_skill=None,
            confidence=0.0,
            reason="LLM 이 가용 skill 외 응답 — fallback to clarify",
        )

    raw_conf = parsed.get("confidence", 0.0)
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.5:
        # 자신 없음 — clarify 권장.
        return SkillIntentDecision(
            skill_v2=skill_v2_decision,
            intent_label=intent_label,
            conflict=True,
            resolved_skill=None,
            confidence=confidence,
            reason=str(parsed.get("reason", "low confidence")),
        )

    return SkillIntentDecision(
        skill_v2=skill_v2_decision,
        intent_label=intent_label,
        conflict=True,
        resolved_skill=resolved,
        confidence=confidence,
        reason=str(parsed.get("reason", "")),
    )
