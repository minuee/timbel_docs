import pytest
from src.agent_framework.runtime.state_machine import StateMachine, TurnResult
from src.agent_framework.runtime.loader import load_skill_from_path
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_skill.yaml"


@pytest.mark.asyncio
async def test_single_transition_progresses():
    skill = load_skill_from_path(FIXTURE)
    sm = StateMachine(skill)
    # 초기 state 로 시작
    session = {"current_state": "s_greet", "slots": {}}
    result = await sm.step(
        session,
        user_message="hi",
        detected_intents=["echo"],
        llm_callbacks=None,
    )
    assert isinstance(result, TurnResult)
    assert result.next_state == "done"
    assert result.requires_llm_fallback is False


@pytest.mark.asyncio
async def test_no_match_stays_in_state():
    # 조건이 충족되지 않고 llm_fallback 도 없으면 같은 state 유지
    # (minimal fixture 는 조건 없는 to: done 이라 이 케이스는 불가 — 다른 fixture)
    pass   # 다음 Task 에서 확장. 여기선 happy path 만
