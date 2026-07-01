from src.agent_framework.runtime.router import SkillRouter
from src.agent_framework.runtime.schema import Skill


def _skill(id_, triggers):
    return Skill.model_validate({
        "skill": {"id": id_, "version": "0.1", "domain": "test", "description": "x"},
        "triggers": [{"intent": t} for t in triggers],
        "slots": [],
        "initial_state": "s",
        "states": [{"id": "s"}],
    })


def test_router_matches_intent():
    router = SkillRouter({
        "aa": _skill("aa", ["book"]),
        "bb": _skill("bb", ["diary"]),
    })
    assert router.route(["book"]) == "aa"
    assert router.route(["diary"]) == "bb"
    assert router.route(["unknown"]) is None


def test_router_first_match_wins():
    router = SkillRouter({
        "aa": _skill("aa", ["general"]),
        "bb": _skill("bb", ["general"]),
    })
    # 결정적 — 알파벳 순 (aa 우선)
    assert router.route(["general"]) == "aa"
