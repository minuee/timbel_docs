from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.agent_framework.llm.json_parse import extract_json
from src.agent_framework.runtime.time_context import prepend_time


# Intentionally duplicated with slot_filler.LLMClient — see plan Task 9 review note.
# Non-streaming complete() vs streaming stream() keep separate Protocols for v1.
class LLMClient(Protocol):
    async def complete(self, system: str, user: str, *, response_format: str | None = None) -> str: ...


@dataclass
class FallbackDecision:
    next_state: str   # "stay" 또는 available_states 중 하나
    response: str


_SYSTEM = (
    "현재 상태에서 정의된 전이 규칙으로 사용자 메시지를 매칭하지 못했다. "
    "다음 중 하나를 판단해 JSON 으로 반환: "
    "(1) 사용자 의도가 다른 state 로 점프 → 해당 state id, "
    "(2) 같은 state 유지 → 'stay'. "
    "`response` 필드에 자연어 응답을 함께. JSON 만 출력.\n\n"
    "**응답 규칙 (절대 준수)**:\n"
    "- **행동 약속 금지**: '안내해 드릴게요', '잠시만 기다려 주세요', '조회해 볼게요', "
    "'확인해 드릴게요', '처리해 드릴게요' 같은 미래 행동 약속 문구 금지. "
    "시스템이 실제로 할 수 있는 행동은 available_states 전이와 현재 state 유지뿐이다.\n"
    "- **모르는 정보 생성 금지**: 데이터베이스 조회, 목록 나열, 가격, 일정, 의사명 등 "
    "구체적 정보를 지어내지 말 것. 모를 때는 '현재 대화 단계에서 해당 정보는 드릴 수 없어요' 로 응답.\n"
    "- **현재 단계 재확인 권유**: 사용자가 다른 주제로 벗어나면 현재 요청 중인 정보 "
    "(예: '예약 날짜를 먼저 알려주세요') 로 부드럽게 되돌릴 것.\n"
    "- **짧고 솔직하게**: 한 문장 또는 두 문장. 진단/의학적 조언 금지."
)


class FallbackRouter:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def decide(
        self,
        current_state: str,
        user_message: str,
        available_states: list[str],
    ) -> FallbackDecision:
        user = (
            f"현재 state: {current_state}\n"
            f"사용자 메시지: \"{user_message}\"\n"
            f"이동 가능한 state: {available_states}\n"
            f'JSON 형식: {{"next_state": "...", "response": "..."}}'
        )
        raw = await self.llm.complete(
            prepend_time(_SYSTEM), user, response_format="json_object"
        )
        data = extract_json(raw)
        nxt = data.get("next_state", "stay")
        if nxt != "stay" and nxt not in available_states:
            # LLM hallucinated a non-existent state — fall back to "stay"
            nxt = "stay"
        return FallbackDecision(
            next_state=nxt,
            response=data.get("response", ""),
        )
