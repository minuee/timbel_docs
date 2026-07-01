"""Fallback composer — 외부 호출 실패 시 대안 답변 합성.

§C #4 (무응답 회피). 외부 API/tool 호출이 실패하면 단순 "에러" 가 아니라
 "지금은 X 못 했어요. 대신 Y 는 가능합니다." 식의 자연스러운 안내.

본 모듈은 LLM 미사용 — 정적 템플릿 + 템플릿 채우기로 충분. (LLM 까지 가면
실패 위에 또 실패 가능성. KISS.)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FallbackContext:
    """fallback 합성 입력.

    failed_action : 실패한 작업 인간 친화 라벨 (예: "뉴스 조회", "결제 요청")
    error_kind : "timeout" | "unauthorized" | "rate_limited" | "service_down" | "unknown"
    alternatives : 추가 가능 대안 (예: ["일정 조회", "메모 저장"])
    """

    failed_action: str
    error_kind: str = "unknown"
    alternatives: list[str] | None = None


_KIND_TEMPLATES: dict[str, str] = {
    "timeout": "지금은 {action} 응답이 늦어 가져오지 못했습니다.",
    "unauthorized": "지금은 {action} 권한 확인 문제로 진행하지 못했습니다.",
    "rate_limited": "지금은 {action} 요청이 한도에 닿아 잠시 후 다시 시도가 필요합니다.",
    "service_down": "지금은 {action} 외부 서비스에 일시적 장애가 있어 진행하지 못했습니다.",
    "unknown": "지금은 {action} 을(를) 진행하지 못했습니다.",
}


class FallbackComposer:
    """외부 호출 실패 시 안내 문구를 만든다.

    Pattern:
      "지금은 {failed_action} 못 했어요. 대신 {alternatives[0]}, {alternatives[1]} 는 가능합니다."
    """

    def __init__(self, *, default_message: str | None = None):
        self.default_message = (
            default_message
            or "지금은 그 작업을 진행하지 못했습니다. 잠시 후 다시 시도해 주세요."
        )

    def compose(self, ctx: FallbackContext) -> str:
        action = (ctx.failed_action or "").strip() or "요청한 작업"
        kind = ctx.error_kind if ctx.error_kind in _KIND_TEMPLATES else "unknown"
        head = _KIND_TEMPLATES[kind].format(action=action)
        alts = [a for a in (ctx.alternatives or []) if a and a.strip()]
        if not alts:
            return head + " 잠시 후 다시 시도해 주세요."
        if len(alts) == 1:
            return f"{head} 대신 '{alts[0]}' 는 바로 가능합니다."
        if len(alts) == 2:
            return f"{head} 대신 '{alts[0]}' 또는 '{alts[1]}' 는 바로 가능합니다."
        joined = ", ".join(f"'{a}'" for a in alts[:3])
        return f"{head} 대신 {joined} 같은 작업은 바로 가능합니다."
