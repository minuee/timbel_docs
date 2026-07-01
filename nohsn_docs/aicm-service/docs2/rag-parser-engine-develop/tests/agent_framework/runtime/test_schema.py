import pytest
from pydantic import ValidationError

from src.agent_framework.runtime.schema import Skill, SkillMeta, SlotDef, StateDef, Transition


def test_skill_roundtrip_minimal():
    raw = {
        "skill": {"id": "foo", "version": "0.1", "domain": "test", "description": "x"},
        "triggers": [{"intent": "start"}],
        "slots": [{"name": "a", "type": "text", "required": True}],
        "initial_state": "s1",
        "states": [
            {"id": "s1", "transitions": [{"to": "done"}]},
            {"id": "done"},
        ],
    }
    skill = Skill.model_validate(raw)
    assert skill.meta.id == "foo"
    assert skill.initial_state == "s1"
    assert len(skill.states) == 2


def test_skill_rejects_unknown_initial_state():
    raw = {
        "skill": {"id": "foo", "version": "0.1", "domain": "test", "description": "x"},
        "triggers": [{"intent": "start"}],
        "slots": [],
        "initial_state": "missing",
        "states": [{"id": "s1"}],
    }
    with pytest.raises(ValidationError) as exc:
        Skill.model_validate(raw)
    assert "initial_state" in str(exc.value)


def test_slot_type_validation():
    with pytest.raises(ValidationError):
        SlotDef.model_validate({"name": "x", "type": "bogus"})


# ────────────────────────────────────────────
# Task 1 리뷰 후속 하드닝 테스트
# ────────────────────────────────────────────

def test_transition_requires_to_or_fallback():
    # Transition._one_of 검증 — when 만 있고 to/llm_fallback 없으면 ValidationError
    with pytest.raises(ValidationError):
        Transition.model_validate({"when": "has_intent(foo)"})


def test_skill_meta_id_regex_enforced():
    # SkillMeta.id 는 ^[a-z][a-z0-9_]+$ — 대문자/하이픈 금지
    with pytest.raises(ValidationError):
        SkillMeta.model_validate({
            "id": "Bad-ID",
            "version": "0.1",
            "domain": "test",
            "description": "x",
        })
