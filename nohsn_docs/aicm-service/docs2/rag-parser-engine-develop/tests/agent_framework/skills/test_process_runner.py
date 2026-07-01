"""process_runner 테스트 — multi-turn 워크플로 엔진 검증."""

from __future__ import annotations

import asyncio
import json

from src.agent_framework.skills.process_runner import ProcessRunner
from src.agent_framework.skills.schema_v2 import (
    SkillProcess,
    SkillProcessStep,
    SkillV2,
)


def _run(coro):
    # 새 event loop 를 매번 생성해서 cross-test pollution 방지.
    # asyncio_mode=auto 인 다른 테스트가 loop 를 닫으면
    # asyncio.get_event_loop() 가 RuntimeError 를 던지기 때문.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _ScriptedLLM:
    """미리 정해진 응답 큐를 순서대로 반환."""

    def __init__(self, responses: list[str | dict]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str:
        self.calls.append((system, user))
        if not self.responses:
            return json.dumps({})
        nxt = self.responses.pop(0)
        if isinstance(nxt, dict):
            return json.dumps(nxt, ensure_ascii=False)
        return nxt


async def _no_tool(name, args, slots):  # pragma: no cover
    return ""


def _skill_with(steps: list[SkillProcessStep]) -> SkillV2:
    return SkillV2(
        name="t",
        description="d",
        process=SkillProcess(steps=steps),
    )


# ---------------------------------------------------------------------------
# elicit
# ---------------------------------------------------------------------------


def test_elicit_asks_when_slots_missing_and_advances_when_filled():
    skill = _skill_with(
        [
            SkillProcessStep(
                kind="elicit",
                config={
                    "slots": ["복무_상태", "전역_예정일"],
                    "question": "복무 상태와 전역 예정일을 알려주세요.",
                },
            ),
            SkillProcessStep(kind="notify", config={"message": "감사합니다"}),
        ]
    )
    # 첫 호출: 사용자 입력 없음 → 질문만
    llm = _ScriptedLLM(
        [
            # 두 번째 advance 에서 슬롯 일부 추출
            {"slots": {"복무_상태": "현역"}},
            # 세 번째 advance 에서 나머지 추출
            {"slots": {"전역_예정일": "2027-04-01"}},
        ]
    )
    runner = ProcessRunner(skill, llm, _no_tool)

    state: dict = {}

    r1 = _run(runner.advance(user_input=None, state=state))
    assert "복무 상태와 전역 예정일" in r1.response
    assert r1.done is False
    state = r1.next_state

    r2 = _run(runner.advance(user_input="현역입니다", state=state))
    # 일부만 채워짐 → 부족 안내 + 같은 question
    assert "전역_예정일" in r2.response
    assert r2.done is False
    state = r2.next_state

    r3 = _run(runner.advance(user_input="2027년 4월 1일이요", state=state))
    # 전부 채워짐 → 다음 step (notify) 응답
    assert r3.response == "감사합니다"
    assert r3.done is True


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_step_invokes_tool_and_stores_result():
    skill = _skill_with(
        [
            SkillProcessStep(kind="run", config={"tool": "kms_search", "args": {"q": "적금"}}),
            SkillProcessStep(kind="notify", config={"message": "결과: {kms_search_result}"}),
        ]
    )
    captured: list[tuple[str, dict, dict]] = []

    async def tool(name, args, slots):
        captured.append((name, args, slots))
        return "금리 5%"

    llm = _ScriptedLLM([])
    runner = ProcessRunner(skill, llm, tool)

    state: dict = {}
    r1 = _run(runner.advance(user_input=None, state=state))
    # run 은 즉시 다음 step (notify) 까지 가지 않음 — advance 는 1 step 단위.
    # 하지만 run 은 응답이 빈 문자열이고 done=False. 다음 advance 가 notify 처리.
    assert captured[0][0] == "kms_search"
    assert r1.done is False
    state = r1.next_state

    r2 = _run(runner.advance(user_input=None, state=state))
    assert r2.response == "결과: 금리 5%"
    assert r2.done is True


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_step_formats_template_with_slots():
    skill = _skill_with(
        [
            SkillProcessStep(
                kind="render",
                config={"template": "{이름}님, 안녕하세요. 잔액은 {잔액}원입니다."},
            ),
        ]
    )
    llm = _ScriptedLLM([])
    runner = ProcessRunner(skill, llm, _no_tool)

    state = {
        "slots": {"이름": "홍길동", "잔액": "100000"},
        "current_step_idx": 0,
        "last_tool_result": None,
    }
    r = _run(runner.advance(user_input=None, state=state))
    assert r.response == "홍길동님, 안녕하세요. 잔액은 100000원입니다."
    assert r.done is True


# ---------------------------------------------------------------------------
# approve_request
# ---------------------------------------------------------------------------


def test_approve_request_branches_on_yes_no():
    skill = _skill_with(
        [
            SkillProcessStep(kind="approve_request", config={"question": "가입할까요?"}),
            SkillProcessStep(kind="notify", config={"message": "가입 진행합니다"}),
        ]
    )
    llm = _ScriptedLLM([{"decision": "approve", "reason": "yes"}])
    runner = ProcessRunner(skill, llm, _no_tool)

    state: dict = {}
    r1 = _run(runner.advance(user_input=None, state=state))
    assert "가입할까요?" in r1.response
    assert r1.done is False
    state = r1.next_state

    r2 = _run(runner.advance(user_input="네 진행해주세요", state=state))
    assert r2.response == "가입 진행합니다"
    assert r2.done is True


def test_approve_request_reject_ends_process():
    skill = _skill_with(
        [
            SkillProcessStep(
                kind="approve_request",
                config={"question": "가입할까요?", "on_reject": "취소했습니다"},
            ),
            SkillProcessStep(kind="notify", config={"message": "여기는 안 옴"}),
        ]
    )
    llm = _ScriptedLLM([{"decision": "reject", "reason": "no"}])
    runner = ProcessRunner(skill, llm, _no_tool)

    state: dict = {}
    _ = _run(runner.advance(user_input=None, state=state))
    state = _.next_state
    r = _run(runner.advance(user_input="아니요", state=state))
    assert r.response == "취소했습니다"
    assert r.done is True


# ---------------------------------------------------------------------------
# done — empty process
# ---------------------------------------------------------------------------


def test_no_process_returns_done_immediately():
    skill = SkillV2(name="x", description="d", process=None)
    llm = _ScriptedLLM([])
    runner = ProcessRunner(skill, llm, _no_tool)
    r = _run(runner.advance(user_input=None, state={}))
    assert r.done is True
    assert r.response == ""
