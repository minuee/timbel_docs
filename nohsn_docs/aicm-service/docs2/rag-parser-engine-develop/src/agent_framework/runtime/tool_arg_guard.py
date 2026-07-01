"""Chokepoint 3 — Tool argument validation boundary.

plan_orchestrator / engine 이 tool 을 invoke 하기 *직전* 에 args 의 query /
text / message / content 류 인자를 검사한다. system prompt / binding policy /
agent_context 텍스트가 그대로 인자에 박혀 있으면 ``ToolArgPollution`` raise.

배경 (2026-05-07 samchully_voc 사건):
- LLM 이 plan 만들면서 ``web.search`` 의 ``query`` 인자에 system prompt 전체
  ("[에이전트 컨텍스트]\\n[BINDING POLICY ...") 를 베껴 넣음.
- web.search 가 stub fallback 으로 그 텍스트를 검색하고 결과 title 로 노출.
- citation [4] 에 system prompt 가 그대로 사용자에게 보임.

근본 원인은 LLM 의 args 채움 실수 — 이 layer 에서 *원천 차단* 한다.
"""
from __future__ import annotations

from typing import Any


class ToolArgPollution(ValueError):
    """tool args 에 system prompt / binding policy 텍스트가 섞여 있을 때 raise.

    engine plan executor 가 catch → 해당 step 을 skip + 로그 + telemetry.
    plan 실행 자체는 계속 (다른 step / fallback 가능).
    """

    def __init__(self, *, tool: str, arg: str, reason: str, preview: str = ""):
        self.tool = tool
        self.arg = arg
        self.reason = reason
        self.preview = preview
        super().__init__(
            f"tool_arg_polluted: tool={tool} arg={arg} reason={reason}"
        )


# system prompt / agent context 의 *고유한* 마커. user message 가 자연스럽게
# 이 문자열을 포함할 가능성은 거의 없음 — 정상 발화 회귀 0 보장.
_PROMPT_MARKERS: tuple[str, ...] = (
    "[BINDING POLICY",
    "[/BINDING POLICY]",
    "[에이전트 컨텍스트]",
    "## current agent:",
    "### goal\n",
    "### guidelines\n",
    "### allowed_tools\n",
    "### done_when\n",
)

# query/text/message 류 인자에서 검사할 키. tool args dict 의 *값* 이 이런
# 키 아래 들어 있을 때만 검사. 다른 키 (created_after, top_k, repo_ids 등) 는
# 통과.
_QUERY_LIKE_KEYS: frozenset[str] = frozenset({
    "query",
    "text",
    "message",
    "content",
    "body",
    "prompt",
    "user_message",
    "q",
})

# user message 는 보통 짧다. system prompt 가 들어오면 4096+ 자가 됨.
# 한국어 발화는 대부분 200자 이내, 긴 메일도 1500자 이내가 정상. 4096 은
# 정상/공격 경계가 명확한 heuristic.
_MAX_QUERY_LEN: int = 4096


def _has_prompt_marker(s: str) -> tuple[bool, str]:
    """문자열에 system prompt 마커가 포함됐는지 검사. (matched, marker)."""
    if not s:
        return False, ""
    for m in _PROMPT_MARKERS:
        if m in s:
            return True, m
    return False, ""


def assert_tool_args_clean(tool: str, args: dict[str, Any]) -> None:
    """tool args 가 system prompt / 정책 텍스트 오염 없는지 검사.

    오염 시 ``ToolArgPollution`` raise. 정상이면 None 반환.

    검사 대상 키: ``_QUERY_LIKE_KEYS`` 만. 다른 args (repo_ids, top_k,
    created_after 등) 는 통과 — schema validation 책임 외.

    Args:
        tool: 도구 이름 (예: "web.search", "kms_rag.search").
        args: tool 의 input args dict.

    Raises:
        ToolArgPollution: 오염 감지.
    """
    if not isinstance(args, dict):
        return
    for k, v in args.items():
        if k not in _QUERY_LIKE_KEYS:
            continue
        if not isinstance(v, str):
            continue
        # 길이 검사 — 4096 초과는 정상 발화 가능성 ~0.
        if len(v) > _MAX_QUERY_LEN:
            raise ToolArgPollution(
                tool=tool,
                arg=k,
                reason=f"length {len(v)} exceeds max {_MAX_QUERY_LEN}",
                preview=v[:200],
            )
        # marker 검사 — system prompt 누설.
        matched, marker = _has_prompt_marker(v)
        if matched:
            raise ToolArgPollution(
                tool=tool,
                arg=k,
                reason=f"system prompt marker {marker!r} detected",
                preview=v[:200],
            )


__all__ = ["ToolArgPollution", "assert_tool_args_clean"]
