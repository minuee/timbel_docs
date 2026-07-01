"""Regression scenario types — PR P9.

yaml / DB 양쪽 로드를 동일한 dataclass 로 통일. runner / executor 가 이
타입만 보고 구동.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HttpStep:
    """단일 HTTP 호출. ``expect`` 키:

    * ``status`` (int)            — response status 일치
    * ``body_contains`` (str)     — response.text 부분 문자열 포함
    * ``json_contains`` (dict)    — response.json() 의 key/value 포함
    """

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    file: dict[str, Any] | None = None
    auth_account: str | None = None
    tenant: str | None = None  # personal | business | <tenant_uuid>
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatStep:
    """단일 chat SSE 요청. ``expect`` 키:

    * ``tool`` (str)                          — events 안에 ``tool_call.name`` 일치
    * ``tools_any_of`` (list[str])            — 위 set 중 하나라도
    * ``citations_count`` (str | int)         — ">=N" / N — 정수 비교
    * ``assistant_body_contains`` (str)       — 누적 토큰 substring
    * ``assistant_body_pattern`` (regex)      — re.search 매칭
    * ``assistant_body_nonempty`` (bool)      — 누적 토큰 길이 > 0
    * ``intent_in`` (list[str])               — events 안의 intent 발화
    * ``intent_not_in`` (list[str])           — 발화돼서는 안 되는 intent
    * ``has_event`` (str)                     — 특정 event type 등장
    * ``has_no_event`` (str)                  — 특정 event type 미등장
    """

    user: str
    tenant: str = "personal"
    account: str = "demo-admin"
    expect: dict[str, Any] = field(default_factory=dict)


Step = HttpStep | ChatStep


@dataclass
class Scenario:
    name: str
    references: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)


@dataclass
class StepResult:
    passed: bool
    detail: str = ""
    raw_response: dict[str, Any] | None = None


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    duration_ms: int
    step_results: list[StepResult]
