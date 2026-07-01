"""Task 32 — Skill YAML schema v1.1 테스트.

- SlotDef.must_be_specific / validators 필드 기본값 & 설정값
- SkillAvailability.business_type 가 Enum 으로 제약되는지
- SKILL_SCHEMA_CURRENT_VERSION 상수
- validators 모듈 (time_of_day_required / future_only) 동작
- appointment_derm.yaml 이 v1.1 로 올바르게 로드되는지
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agent_framework.runtime.schema import (
    SKILL_SCHEMA_CURRENT_VERSION,
    Skill,
    SkillAvailability,
    SlotDef,
)
from src.agent_framework.runtime.validators import (
    future_only,
    get_validator,
    run_validator,
    time_of_day_required,
    validators_list,
)


# ──────────────────────────────────────────────────────────────────────────────
# SlotDef v1.1
# ──────────────────────────────────────────────────────────────────────────────


def test_slot_def_must_be_specific_default_false():
    slot = SlotDef.model_validate({"name": "a", "type": "text"})
    assert slot.must_be_specific is False
    assert slot.validators == []


def test_slot_def_accepts_new_fields():
    slot = SlotDef.model_validate(
        {
            "name": "when",
            "type": "datetime",
            "required": True,
            "must_be_specific": True,
            "validators": ["time_of_day_required", "future_only"],
        }
    )
    assert slot.must_be_specific is True
    assert slot.validators == ["time_of_day_required", "future_only"]


# ──────────────────────────────────────────────────────────────────────────────
# SkillAvailability.business_type Enum
# ──────────────────────────────────────────────────────────────────────────────


def test_availability_business_type_enum_accepts_valid():
    av = SkillAvailability.model_validate(
        {"scope": "business_only", "business_type": "medical"}
    )
    assert av.business_type == "medical"


def test_availability_business_type_rejects_invalid():
    with pytest.raises(ValidationError):
        SkillAvailability.model_validate(
            {"scope": "business_only", "business_type": "spaceship"}
        )


def test_availability_business_type_still_optional():
    av = SkillAvailability.model_validate({"scope": "personal"})
    assert av.business_type is None


# ──────────────────────────────────────────────────────────────────────────────
# validators 모듈
# ──────────────────────────────────────────────────────────────────────────────


def test_time_of_day_required_accepts_datetime():
    ok, _ = time_of_day_required(datetime(2026, 4, 24, 15, 0))
    assert ok is True


def test_time_of_day_required_accepts_hhmm_string():
    ok, _ = time_of_day_required("2026-04-24 15:00")
    assert ok is True


def test_time_of_day_required_rejects_vague():
    ok, reason = time_of_day_required("내일 저녁")
    assert ok is False
    assert "HH:MM" in reason or "no" in reason.lower()


def test_time_of_day_required_rejects_date_only():
    ok, _ = time_of_day_required(date(2026, 4, 24))
    assert ok is False


def test_future_only_accepts_today_and_future():
    ok_today, _ = future_only(date.today())
    ok_future, _ = future_only(date.today() + timedelta(days=3))
    assert ok_today is True
    assert ok_future is True


def test_future_only_rejects_past():
    ok, reason = future_only(date.today() - timedelta(days=1))
    assert ok is False
    assert "past" in reason


def test_run_validator_unknown_name_passes_safely():
    ok, reason = run_validator("definitely_not_registered", "any")
    assert ok is True
    assert "unknown" in reason


def test_validators_list_includes_v11_entries():
    names = validators_list()
    assert "time_of_day_required" in names
    assert "future_only" in names


def test_get_validator_returns_callable():
    fn = get_validator("time_of_day_required")
    assert callable(fn)


# ──────────────────────────────────────────────────────────────────────────────
# Schema 상수 + appointment_derm.yaml 로드
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_current_version_is_1_1():
    assert SKILL_SCHEMA_CURRENT_VERSION == "1.1"


def test_existing_0_1_version_yaml_still_loads():
    """0.1 같은 과거 버전 skill YAML 도 여전히 로드되어야 한다 (backward compat)."""
    raw = {
        "skill": {"id": "legacy", "version": "0.1", "domain": "test", "description": "x"},
        "triggers": [{"intent": "start"}],
        "slots": [{"name": "a", "type": "text"}],
        "initial_state": "s1",
        "states": [{"id": "s1", "transitions": [{"to": "done"}]}, {"id": "done"}],
    }
    skill = Skill.model_validate(raw)
    assert skill.meta.version == "0.1"


def test_appointment_derm_loads_with_v11_fields():
    """appointment_derm.yaml — must_be_specific + validators 포함해 로드 성공."""
    from src.agent_framework.runtime.loader import load_skill_from_path

    path = Path("src/agent_framework/skills/appointment_derm.yaml")
    skill = load_skill_from_path(path)
    assert skill.meta.version == "1.1"
    dt_slot = next(s for s in skill.slots if s.name == "preferred_datetime")
    assert dt_slot.must_be_specific is True
    assert "time_of_day_required" in dt_slot.validators
    assert "future_only" in dt_slot.validators
