"""SkillV2 schema 로딩 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_framework.skills.schema_v2 import (
    SkillV2,
    SkillV2LoadError,
    from_dict,
    load_skill_v2,
)


def test_minimal_skill_loads():
    skill = from_dict({"name": "echo", "description": "단순 echo"})
    assert isinstance(skill, SkillV2)
    assert skill.name == "echo"
    assert skill.side_effect_level == "read_only"
    assert skill.consequential is False
    assert skill.role is None
    assert skill.process is None


def test_full_skill_with_role_process_few_shot_delegate():
    raw = {
        "name": "kb_savings_counselor",
        "description": "KB 적금 안내",
        "side_effect_level": "read_only",
        "role": {
            "persona": "KB 콜센터 5년차 상담사",
            "tone": "친절·존댓말",
            "knowledge_scope": ["kb_soldiers"],
            "safety_constraints": ["추측 금지", "개인정보 요구 금지"],
        },
        "trigger_examples": ["적금 가입하려고요", "군적금 어떻게"],
        "few_shot_examples": [
            {
                "source": "demo.xlsx",
                "turns": [
                    {"role": "customer", "text": "가입하려고요"},
                    {"role": "counselor", "text": "복무 중이신가요?"},
                ],
            }
        ],
        "delegate_when": [
            {"condition": "보안 절차 진입", "to": "auth_handover"},
        ],
        "process": {
            "steps": [
                {"kind": "elicit", "config": {"slots": ["복무_상태"]}},
                {"kind": "run", "config": {"tool": "kms_search"}},
                {"kind": "render", "config": {"template": "안내드립니다"}},
            ]
        },
    }
    skill = from_dict(raw)
    assert skill.role is not None
    assert skill.role.persona.startswith("KB")
    assert "추측 금지" in skill.role.safety_constraints
    assert len(skill.few_shot_examples) == 1
    assert skill.few_shot_examples[0].turns[0].role == "customer"
    assert len(skill.delegate_when) == 1
    assert skill.delegate_when[0].to == "auth_handover"
    assert skill.process is not None
    assert [s.kind for s in skill.process.steps] == ["elicit", "run", "render"]


def test_invalid_side_effect_level_rejected():
    with pytest.raises(SkillV2LoadError):
        from_dict(
            {
                "name": "x",
                "description": "y",
                "side_effect_level": "🤔nope",
            }
        )


def test_role_scope_fields_default_empty():
    """tenant_scope / persona_required / role_min 미지정 시 빈 리스트 + viewer 기본."""
    raw = {
        "name": "x",
        "description": "y",
        "role": {"persona": "P", "tone": "T"},
    }
    skill = from_dict(raw)
    assert skill.role is not None
    assert skill.role.tenant_scope == []
    assert skill.role.persona_required == []
    assert skill.role.role_min == "viewer"


def test_role_scope_fields_loaded():
    """tenant_scope / persona_required / role_min 명시 시 그대로 로드."""
    raw = {
        "name": "x",
        "description": "y",
        "role": {
            "persona": "P",
            "tone": "T",
            "tenant_scope": ["personal", "hospital"],
            "persona_required": ["doctor", "nurse"],
            "role_min": "admin",
        },
    }
    skill = from_dict(raw)
    assert skill.role is not None
    assert skill.role.tenant_scope == ["personal", "hospital"]
    assert skill.role.persona_required == ["doctor", "nurse"]
    assert skill.role.role_min == "admin"


def test_load_from_yaml_file(tmp_path: Path):
    yaml_path = tmp_path / "demo.yaml"
    yaml_path.write_text(
        "name: demo\n"
        "description: demo skill\n"
        "side_effect_level: write_external\n"
        "consequential: true\n"
        "role:\n"
        "  persona: 데모 페르소나\n"
        "  tone: 정중한\n"
        "trigger_examples:\n"
        "  - 데모 해줘\n",
        encoding="utf-8",
    )
    skill = load_skill_v2(yaml_path)
    assert skill.name == "demo"
    assert skill.side_effect_level == "write_external"
    assert skill.consequential is True
    assert skill.role and skill.role.persona == "데모 페르소나"
    assert skill.trigger_examples == ["데모 해줘"]
