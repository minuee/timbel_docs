"""kb_soldiers_counselor.yaml 이 SkillV2 schema 와 일치하는지 검증."""

from __future__ import annotations

from pathlib import Path

from src.agent_framework.skills.schema_v2 import (
    SkillV2,
    load_all_v2,
    load_skill_v2,
)


YAML_DIR = Path("src/agent_framework/skills/yaml")
KB_PATH = YAML_DIR / "kb_soldiers_counselor.yaml"


def test_kb_soldiers_yaml_loads_into_skill_v2():
    skill = load_skill_v2(KB_PATH)
    assert isinstance(skill, SkillV2)
    assert skill.name == "kb_soldiers_counselor"
    assert "장병내일준비적금" in skill.description
    assert skill.side_effect_level == "read_only"
    assert skill.consequential is False


def test_kb_soldiers_role_has_persona_tone_constraints():
    skill = load_skill_v2(KB_PATH)
    assert skill.role is not None
    assert "콜센터" in skill.role.persona
    assert "친절" in skill.role.tone
    assert "kb_soldiers_savings" in skill.role.knowledge_scope
    assert any("개인정보" in c for c in skill.role.safety_constraints)
    assert any("추측" in c for c in skill.role.safety_constraints)


def test_kb_soldiers_has_triggers_few_shot_delegate_process():
    skill = load_skill_v2(KB_PATH)
    assert len(skill.trigger_examples) >= 5
    assert any("적금" in t for t in skill.trigger_examples)

    assert len(skill.few_shot_examples) == 1
    ex = skill.few_shot_examples[0]
    assert ex.source is not None and "Add-On-Chatbot" in ex.source
    # 6 turns customer/counselor 교차
    assert len(ex.turns) == 6
    assert ex.turns[0].role == "customer"
    assert ex.turns[1].role == "counselor"

    # delegate
    targets = {r.to for r in skill.delegate_when}
    assert "kb_general_counselor" in targets
    assert "kb_authentication_handover" in targets

    # process: elicit → run → render
    assert skill.process is not None
    kinds = [s.kind for s in skill.process.steps]
    assert kinds == ["elicit", "run", "render"]
    elicit_cfg = skill.process.steps[0].config
    assert elicit_cfg["slots"] == ["복무_상태", "전역_예정일"]
    run_cfg = skill.process.steps[1].config
    assert run_cfg["tool"] == "kms_search"


def test_load_all_v2_picks_up_kb_yaml():
    skills = load_all_v2(YAML_DIR)
    assert "kb_soldiers_counselor" in skills
    assert isinstance(skills["kb_soldiers_counselor"], SkillV2)
