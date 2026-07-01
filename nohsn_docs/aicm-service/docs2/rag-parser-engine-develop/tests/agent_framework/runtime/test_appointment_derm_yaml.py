from pathlib import Path
from src.agent_framework.runtime.loader import load_skill_from_path


def test_appointment_derm_yaml_loads():
    path = Path("src/agent_framework/skills/appointment_derm.yaml")
    skill = load_skill_from_path(path)
    assert skill.meta.id == "appointment_derm"
    ids = [s.id for s in skill.states]
    # Task 25-C v0.2 — datetime 통합 + doctor 선택 상태 포함
    for required in [
        "greet",
        "list_doctors_state",
        "collect_datetime",
        "collect_doctor",
        "collect_service",
        "check_slot",
        "confirm",
        "book",
        "done",
    ]:
        assert required in ids
