from pathlib import Path
import yaml
from pydantic import ValidationError

from src.agent_framework.runtime.schema import Skill


class SkillLoadError(Exception):
    pass


def load_skill_from_path(path: Path) -> Skill:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise SkillLoadError(f"skill file not found: {path}") from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SkillLoadError(f"invalid YAML at {path}: {e}") from e
    try:
        return Skill.model_validate(raw)
    except ValidationError as e:
        raise SkillLoadError(f"schema violation at {path}: {e}") from e


def load_all_skills(dir_path: Path) -> dict[str, Skill]:
    """dir 안의 *.yaml 전부 로드. 실패한 파일은 skip 하고 로그."""
    from src.common.logging import get_logger
    log = get_logger(__name__)
    result: dict[str, Skill] = {}
    for yaml_file in sorted(dir_path.glob("*.yaml")):
        try:
            skill = load_skill_from_path(yaml_file)
            result[skill.meta.id] = skill
        except SkillLoadError as e:
            log.error("skill load failed", path=str(yaml_file), error=str(e))
    return result
