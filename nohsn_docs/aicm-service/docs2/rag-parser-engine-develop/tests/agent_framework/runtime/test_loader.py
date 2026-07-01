from pathlib import Path
import pytest

from src.agent_framework.runtime.loader import load_skill_from_path, SkillLoadError


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_skill.yaml"


def test_load_minimal_ok():
    s = load_skill_from_path(FIXTURE)
    assert s.meta.id == "echo_bot"


def test_load_missing_file_raises():
    with pytest.raises(SkillLoadError):
        load_skill_from_path(Path("/nonexistent/skill.yaml"))


def test_load_bad_yaml_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("skill: [unclosed")
    with pytest.raises(SkillLoadError):
        load_skill_from_path(bad)
