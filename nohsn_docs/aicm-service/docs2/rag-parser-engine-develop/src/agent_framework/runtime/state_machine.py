from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from src.agent_framework.runtime.schema import Skill, StateDef
from src.agent_framework.runtime.matcher import MatcherContext, evaluate_when


@dataclass
class TurnResult:
    next_state: str
    requires_llm_fallback: bool
    state_executed: bool   # on_enter/tool 실행됨 여부


class StateMachine:
    def __init__(self, skill: Skill):
        self.skill = skill
        self._states_by_id: dict[str, StateDef] = {s.id: s for s in skill.states}

    def get_state(self, state_id: str) -> StateDef:
        return self._states_by_id[state_id]

    async def step(
        self,
        session: dict,
        user_message: str,
        detected_intents: list[str],
        llm_callbacks: Any = None,
        tool_result: dict | None = None,
        user_intent: str | None = None,
    ) -> TurnResult:
        current_id = session.get("current_state") or self.skill.initial_state
        current = self.get_state(current_id)

        ctx = MatcherContext(
            user_message=user_message,
            detected_intents=detected_intents,
            slots=session.get("slots", {}),
            tool_result=tool_result,
            user_intent=user_intent,
        )

        # 1. 먼저 명시적 `when:` 이 있는 transitions 를 순서대로 평가 (조건부 우선)
        unconditional: list = []
        for t in current.transitions:
            if t.llm_fallback:
                continue
            if t.when is None:
                # `to:` 만 있고 when 없는 transition — 최종 unconditional fallback 후보.
                # llm_fallback 이 있으면 그쪽이 먼저이므로 일단 보류.
                unconditional.append(t)
                continue
            if t.to and evaluate_when(t.when, ctx):
                return TurnResult(next_state=t.to, requires_llm_fallback=False, state_executed=False)

        # 2. 조건부 매칭 없음 — llm_fallback 이 있으면 우선 trigger
        has_fallback = any(t.llm_fallback for t in current.transitions)
        if has_fallback:
            return TurnResult(next_state=current_id, requires_llm_fallback=True, state_executed=False)

        # 3. 조건도 fallback 도 없으면 unconditional `to:` (기본 경로) 채택
        if unconditional:
            t = unconditional[0]
            return TurnResult(next_state=t.to, requires_llm_fallback=False, state_executed=False)

        return TurnResult(next_state=current_id, requires_llm_fallback=False, state_executed=False)
