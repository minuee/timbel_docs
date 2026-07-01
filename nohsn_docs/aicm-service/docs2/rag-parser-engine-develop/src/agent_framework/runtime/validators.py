"""Skill slot validator registry (Task 32).

Skill YAML v1.1 의 `slots[].validators: [...]` 에서 이름으로 참조된다.
각 validator 는 slot 값(임의 타입)을 받아 (ok: bool, reason: str) 을 반환한다.

slot_filler / state_machine 이 run_validator(name, value) 를 호출해 값 채움 판정을 보조한다.
등록되지 않은 이름이 지정되면 (True, "unknown validator skipped") 로 안전 통과시킨다 — YAML 오타로 스킬 전체가 막히는 일 없도록.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Tuple

ValidatorFn = Callable[[Any], Tuple[bool, str]]


# ---------------------------------------------------------------------------
# 기본 제공 validator
# ---------------------------------------------------------------------------


_HH_MM_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def time_of_day_required(value: Any) -> tuple[bool, str]:
    """HH:MM 형태의 시각이 포함되어 있는지 확인.

    허용:
      - datetime 객체
      - "2026-04-24 15:00" / "15:00" 문자열
    거절:
      - "내일 저녁" / "오후" 등 모호한 자연어
    """
    if value is None or value == "":
        return False, "empty value"
    if isinstance(value, datetime):
        return True, ""
    if isinstance(value, date):
        return False, "date only, no time"
    if isinstance(value, str):
        if _HH_MM_RE.search(value):
            return True, ""
        return False, "no HH:MM pattern"
    return False, f"unsupported type: {type(value).__name__}"


def future_only(value: Any) -> tuple[bool, str]:
    """주어진 date/datetime 이 오늘(포함) 이후인지 확인."""
    if value is None or value == "":
        return False, "empty value"
    today = date.today()
    if isinstance(value, datetime):
        target = value.date()
    elif isinstance(value, date):
        target = value
    elif isinstance(value, str):
        # 최소 YYYY-MM-DD 접두사만 시도
        try:
            target = date.fromisoformat(value[:10])
        except ValueError:
            return False, "unparseable date string"
    else:
        return False, f"unsupported type: {type(value).__name__}"

    if target < today:
        return False, f"date {target.isoformat()} is in the past"
    return True, ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, ValidatorFn] = {
    "time_of_day_required": time_of_day_required,
    "future_only": future_only,
}


def get_validator(name: str) -> ValidatorFn | None:
    """이름으로 validator 함수를 조회. 없으면 None."""
    return _REGISTRY.get(name)


def run_validator(name: str, value: Any) -> tuple[bool, str]:
    """이름 지정 validator 실행. 이름이 없으면 안전 통과."""
    fn = get_validator(name)
    if fn is None:
        return True, f"unknown validator '{name}' skipped"
    try:
        return fn(value)
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"validator {name} raised: {exc}"


def register_validator(name: str, fn: ValidatorFn) -> None:
    """런타임 확장용 — 테스트/플러그인에서 추가 validator 등록."""
    _REGISTRY[name] = fn


def validators_list() -> list[str]:
    """등록된 validator 이름 목록 (디버깅/introspection 용)."""
    return sorted(_REGISTRY.keys())
