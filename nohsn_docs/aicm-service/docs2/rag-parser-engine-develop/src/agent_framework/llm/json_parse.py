"""LLM JSON 응답 robust 파서.

vLLM 모델들(Gemma 포함)은 `response_format=json_object` 가 걸려있어도 종종
markdown 코드 펜스(` ```json ... ``` `)로 감싸서 반환한다. 이 모듈은
펜스를 벗겨내고 첫 JSON 객체만 파싱한다.
"""
from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(?P<body>.*?)\n?```\s*$",
    re.DOTALL,
)


def extract_json(raw: str) -> Any:
    """Strip optional markdown fences, parse as JSON.

    Raises json.JSONDecodeError on parse failure (caller decides fail-safe policy).

    Handles:
    - Plain JSON: `{"a": 1}` → {"a": 1}
    - Fenced with `json` label: ```json\n{"a": 1}\n``` → {"a": 1}
    - Fenced no label: ```\n{"a": 1}\n``` → {"a": 1}
    - Fenced with surrounding whitespace/newlines
    - JSON with leading/trailing prose (extracts first {...} block)
    """
    if not isinstance(raw, str):
        raise TypeError(f"expected str, got {type(raw).__name__}")

    stripped = raw.strip()
    # Case 1: markdown-fenced
    m = _FENCE_RE.match(stripped)
    if m:
        return json.loads(m.group("body").strip())

    # Case 2: plain JSON
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Case 3: embedded JSON (e.g., LLM adds prose before/after)
    # Greedy match: outermost braces
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidate = stripped[start : end + 1]
        return json.loads(candidate)

    # Give up, raise original error
    raise json.JSONDecodeError("no parseable JSON object found", stripped, 0)
