"""Chat SSE executor — ``/api/v1/chat/message`` 또는 호환 endpoint.

events 를 모두 읽고 expect 키에 매칭. 본 모듈은 backend SSE 가 도달하지
않거나 stream 이 비정상 종료해도 graceful 하게 fail 처리.

memory rule: rule/regex 의 강박 X — assistant_body_pattern 같은 regex 는
yaml 시나리오 작성자가 제어. executor 자체는 패턴 매칭의 기반만 제공.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..types import ChatStep, StepResult


# 사용자 발견 회귀 패턴 (memory feedback_validation_must_include_multiturn_patterns)
# 을 yaml 표현으로 옮긴다. 본 executor 는 keys 를 일반화 비교만 한다.

CHAT_ENDPOINT_CANDIDATES = (
    "/api/v1/chat/message",
    "/api/v1/agent/chat/message",
    "/agent/chat/message",
)


def _compare_count(actual: int, expr: Any) -> tuple[bool, str]:
    """``">=N"`` / ``"==N"`` / ``"<=N"`` / 정수 비교."""
    if isinstance(expr, int):
        return (actual == expr, f"{actual} != {expr}")
    if isinstance(expr, str):
        s = expr.strip()
        m = re.match(r"^(>=|<=|==|>|<|=)?\s*(\d+)$", s)
        if not m:
            return False, f"bad count expr {expr!r}"
        op = m.group(1) or "=="
        n = int(m.group(2))
        if op in ("==", "="):
            return (actual == n, f"{actual} != {n}")
        if op == ">=":
            return (actual >= n, f"{actual} < {n}")
        if op == "<=":
            return (actual <= n, f"{actual} > {n}")
        if op == ">":
            return (actual > n, f"{actual} <= {n}")
        if op == "<":
            return (actual < n, f"{actual} >= {n}")
    return False, f"bad count expr {expr!r}"


async def _stream_sse(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """Open SSE; collect (event, data dict) tuples until 'done' or close."""
    events: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"sse {resp.status_code}: {body[:200]!r}"
                    )
                cur_event: str | None = None
                buf: list[str] = []
                async for raw in resp.aiter_lines():
                    if raw is None:
                        continue
                    line = raw.rstrip("\r")
                    if line == "":
                        # event boundary
                        if buf or cur_event:
                            data_str = "\n".join(buf)
                            try:
                                data = json.loads(data_str) if data_str else {}
                            except (ValueError, json.JSONDecodeError):
                                data = {"raw": data_str}
                            events.append({"event": cur_event or "message", "data": data})
                            if cur_event == "done":
                                break
                        cur_event = None
                        buf = []
                        continue
                    if line.startswith("event:"):
                        cur_event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        buf.append(line[len("data:"):].lstrip())
    except Exception as e:  # noqa: BLE001
        events.append({"event": "_executor_error", "data": {"error": str(e)}})
    return events


async def execute_chat(
    step: ChatStep,
    base_url: str,
    account_tokens: dict[str, str],
    tenant_resolver: Any | None = None,
    session_id: str | None = None,
) -> StepResult:
    token = account_tokens.get(step.account)
    if not token:
        return StepResult(False, f"no token for account {step.account!r}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    if step.tenant:
        tenant_id = step.tenant
        if tenant_resolver:
            try:
                tenant_id = await tenant_resolver(step.account, step.tenant)
            except Exception:  # noqa: BLE001
                pass
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id

    payload: dict[str, Any] = {"message": step.user, "text": step.user}
    if session_id:
        payload["session_id"] = session_id

    # 첫 후보 endpoint 만 시도 — SSE 호환 차이는 backend 설정 문제이므로 fail-fast.
    url = base_url + CHAT_ENDPOINT_CANDIDATES[0]
    events = await _stream_sse(url, headers, payload)

    # 누적 토큰 본문.
    body_parts: list[str] = []
    tool_names: list[str] = []
    intents: list[str] = []
    citations: list[Any] = []
    event_types: list[str] = []
    error_event: dict[str, Any] | None = None
    for ev in events:
        et = ev.get("event")
        data = ev.get("data") or {}
        event_types.append(et or "")
        if et == "_executor_error":
            error_event = data
            break
        if et == "token":
            t = data.get("text") or data.get("delta") or ""
            if isinstance(t, str):
                body_parts.append(t)
        elif et == "tool_call":
            n = data.get("name") or data.get("tool")
            if isinstance(n, str):
                tool_names.append(n)
        elif et == "intent":
            i = data.get("intent") or data.get("name") or data.get("type")
            if isinstance(i, str):
                intents.append(i)
        elif et == "citations" or et == "citations_finalized":
            its = data.get("items") or data.get("citations") or []
            if isinstance(its, list):
                citations = its

    if error_event:
        return StepResult(
            False, f"sse stream error: {error_event.get('error')!r}"
        )

    body = "".join(body_parts)
    expect = step.expect or {}

    # ---- expectation 평가. yaml 어휘 일반화. ----

    if "tool" in expect:
        if expect["tool"] not in tool_names:
            return StepResult(
                False,
                f"tool_call {expect['tool']!r} not seen "
                f"(seen: {tool_names!r})",
            )

    if "tools_any_of" in expect:
        wanted = expect["tools_any_of"] or []
        if not any(t in tool_names for t in wanted):
            return StepResult(
                False,
                f"none of {wanted!r} in tool_calls (seen: {tool_names!r})",
            )

    if "tools_none_of" in expect:
        forbidden = expect["tools_none_of"] or []
        bad = [t for t in tool_names if t in forbidden]
        if bad:
            return StepResult(
                False, f"forbidden tool_calls observed: {bad!r}"
            )

    if "citations_count" in expect:
        ok, why = _compare_count(len(citations), expect["citations_count"])
        if not ok:
            return StepResult(False, f"citations_count: {why}")

    if "assistant_body_contains" in expect:
        sub = expect["assistant_body_contains"]
        if sub not in body:
            return StepResult(
                False,
                f"assistant body missing {sub!r} (got: {body[:200]!r})",
            )

    if "assistant_body_pattern" in expect:
        pat = expect["assistant_body_pattern"]
        try:
            if not re.search(pat, body):
                return StepResult(
                    False,
                    f"assistant body pattern {pat!r} not matched "
                    f"(got: {body[:200]!r})",
                )
        except re.error as e:
            return StepResult(False, f"bad regex {pat!r}: {e}")

    if expect.get("assistant_body_nonempty"):
        if not body.strip():
            return StepResult(False, "assistant body is empty")

    if "intent_in" in expect:
        wanted = expect["intent_in"] or []
        if not any(i in intents for i in wanted):
            return StepResult(
                False,
                f"none of {wanted!r} in intents (seen: {intents!r})",
            )

    if "intent_not_in" in expect:
        forbidden = expect["intent_not_in"] or []
        bad = [i for i in intents if i in forbidden]
        if bad:
            return StepResult(
                False, f"forbidden intent observed: {bad!r}"
            )

    if "has_event" in expect:
        if expect["has_event"] not in event_types:
            return StepResult(
                False,
                f"event {expect['has_event']!r} not seen "
                f"(types: {sorted(set(event_types))!r})",
            )

    if "has_no_event" in expect:
        if expect["has_no_event"] in event_types:
            return StepResult(
                False, f"forbidden event {expect['has_no_event']!r} seen"
            )

    return StepResult(True, "OK")
