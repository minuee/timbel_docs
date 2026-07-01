from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class MatcherContext:
    user_message: str
    detected_intents: list[str]
    slots: dict[str, Any]
    tool_result: dict[str, Any] | None
    user_intent: str | None


_RE_HAS_INTENT = re.compile(r"^has_intent\(([a-z0-9_]+)\)$")
_RE_SLOT_FILLED = re.compile(r"^slot_filled\(([a-z0-9_]+)\)$")
# PR-C — multi-slot AND. ``slots_filled(title, when)`` 형태.
# 사례 yaml 늘리지 말고 메커니즘만 도입 — 콤마 split 후 모든 슬롯이 채워졌는지 검사.
_RE_SLOTS_FILLED = re.compile(r"^slots_filled\(([a-z0-9_,\s]+)\)$")
_RE_USER_INTENT = re.compile(r"^user_intent\(([a-z0-9_]+)\)$")
_RE_TOOL_RESULT = re.compile(r"^(not\s+)?tool_result\.([a-z0-9_]+)$")


def _slot_present(value: Any) -> bool:
    """슬롯이 의미 있는 값으로 채워졌는지. None / "" / 빈 컨테이너는 미충족."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return False
    return True


def evaluate_when(expr: str | None, ctx: MatcherContext) -> bool:
    """transition when 조건 평가. boolean ``and`` / ``or`` 를 dispatch 한다.

    GPT-5.5 검토(2026-04-28): 57 yaml 이 ``slot_filled(a) and slot_filled(b)``
    형태로 가드를 작성했는데 옛 구현은 atom 만 지원해 항상 False. 그 결과
    fallback_router 만으로 분기되며 가드가 우회됐다. 본 함수가 boolean
    operator 를 split 한 뒤 atom 평가에 위임한다.

    우선순위: ``or`` 가 가장 낮음, ``and`` 가 그 위, atom 이 가장 높음. 괄호 미지원.
    """
    if not expr:
        return True
    e = expr.strip()

    # OR 우선 split (lowest precedence). " or " 구분자.
    if " or " in e:
        return any(evaluate_when(part, ctx) for part in _split_top_level(e, " or "))
    if " and " in e:
        return all(evaluate_when(part, ctx) for part in _split_top_level(e, " and "))

    if m := _RE_HAS_INTENT.match(e):
        return m.group(1) in ctx.detected_intents

    if m := _RE_SLOT_FILLED.match(e):
        return _slot_present(ctx.slots.get(m.group(1)))

    if m := _RE_SLOTS_FILLED.match(e):
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        if not names:
            return False
        return all(_slot_present(ctx.slots.get(n)) for n in names)

    if m := _RE_USER_INTENT.match(e):
        return ctx.user_intent == m.group(1)

    if m := _RE_TOOL_RESULT.match(e):
        negated = bool(m.group(1))
        key = m.group(2)
        val = bool((ctx.tool_result or {}).get(key, False))
        return (not val) if negated else val

    return False


def _split_top_level(expr: str, sep: str) -> list[str]:
    """괄호 깊이 0 에서 ``sep`` 로 split. atom 안의 콤마/공백 보호."""
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    i = 0
    L = len(sep)
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0 and expr[i : i + L] == sep:
            out.append("".join(buf).strip())
            buf = []
            i += L
            continue
        buf.append(ch)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    return [p for p in out if p]
