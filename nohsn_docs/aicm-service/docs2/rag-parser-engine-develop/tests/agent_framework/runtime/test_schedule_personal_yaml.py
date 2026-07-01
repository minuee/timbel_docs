"""schedule_personal.yaml 스키마 검증 — create/list 양쪽 trigger + 상태 완성도.

2026-04-24 실사용 테스트 버그 수정:
- trigger 에 list_schedule 추가
- greet → query / create 분기
- collect state 에 on_enter 프롬프트 (slot 재질문)
- query state 가 schedule.list 도구 사용
"""
from pathlib import Path

from src.agent_framework.runtime.loader import load_skill_from_path


def test_schedule_personal_yaml_loads():
    path = Path("src/agent_framework/skills/schedule_personal.yaml")
    skill = load_skill_from_path(path)
    assert skill.meta.id == "schedule_personal"

    # 두 intent 모두 trigger 로 등록돼 있어야 (Bug 3 회귀)
    trigger_intents = {t.intent for t in skill.triggers}
    assert "create_schedule" in trigger_intents
    assert "list_schedule" in trigger_intents

    ids = [s.id for s in skill.states]
    for required in ["greet", "collect", "create", "query", "done"]:
        assert required in ids, f"state '{required}' missing"

    # greet 의 두 매칭 transition 확인
    greet = next(s for s in skill.states if s.id == "greet")
    wheres = {t.when for t in greet.transitions if t.when}
    assert "has_intent(create_schedule)" in wheres
    assert "has_intent(list_schedule)" in wheres

    # collect state 는 slot 재질문 프롬프트 (schedule_collect.md) 를 가진다 (Bug 2)
    collect = next(s for s in skill.states if s.id == "collect")
    assert collect.on_enter is not None
    assert collect.on_enter.llm_respond is not None
    assert collect.on_enter.llm_respond["template"] == "schedule_collect.md"
    # 2026-04-28 — title + when + where 모두 채워져야 create 로 감 (장소까지 묻기).
    wheres = {t.when for t in collect.transitions if t.when}
    assert "slots_filled(title, when, where)" in wheres

    # query state 는 schedule.list 도구 + 필터링 템플릿
    query = next(s for s in skill.states if s.id == "query")
    assert query.tool == "schedule.list"
    assert query.on_exit is not None
    assert query.on_exit.llm_respond is not None
    assert query.on_exit.llm_respond["template"] == "schedule_query_answer.md"
