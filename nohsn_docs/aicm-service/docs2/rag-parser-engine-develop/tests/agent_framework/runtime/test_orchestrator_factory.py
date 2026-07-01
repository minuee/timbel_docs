"""orchestrator factory 회귀 테스트 — daily_briefing fix (2026-05-07).

증상 (before fix):
  warning   orchestrator_factory_init_failed
    error="ProcessRunner.__init__() missing 2 required positional arguments:
           'llm_client' and 'tool_invoker'"
    skill=daily_briefing

원인:
  factory.py 가 ProcessRunner(skill=..., llm=...) 으로 호출 — 키워드 ``llm`` 은
  ProcessRunner 가 받지 않고 ``llm_client`` + ``tool_invoker`` 누락.

검증:
  1) make_process_runner_factory 가 daily_briefing 같은 process 정의 있는 skill 에
     대해 None 이 아닌 ProcessRunner 인스턴스를 반환.
  2) 반환된 runner 의 ``llm`` / ``tool_invoker`` 가 deps 와 동일 객체.
  3) advance() 호출 시 init 단계에서 TypeError 가 발생하지 않음.
  4) tool_invoker 미주입 시 _noop_tool_invoker 가 들어가 fallback 가능.
"""
from __future__ import annotations

import asyncio
import json

from src.agent_framework.runtime.orchestrator.factory import (
    OrchestratorDeps,
    _noop_tool_invoker,
    make_process_runner_factory,
)
from src.agent_framework.skills.process_runner import ProcessRunner
from src.agent_framework.skills.schema_v2 import (
    SkillProcess,
    SkillProcessStep,
    SkillV2,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _StubLLM:
    """ProcessRunner 가 기대하는 .complete(system, user, response_format) 만 충족."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self, system: str, user: str, *, response_format: str | None = None
    ) -> str:
        self.calls.append((system, user))
        if not self.responses:
            return json.dumps({})
        return self.responses.pop(0)


def _daily_briefing_skill() -> SkillV2:
    """실 daily_briefing.yaml 과 동등한 process 구조 — 실 yaml 로드 의존성 회피."""
    return SkillV2(
        name="daily_briefing",
        description="직장인의 아침 업무 브리핑",
        process=SkillProcess(
            steps=[
                SkillProcessStep(
                    kind="elicit",
                    config={
                        "slots": ["오늘 날짜", "우선순위"],
                        "question": "오늘의 업무와 우선순위를 알려주세요.",
                    },
                ),
                SkillProcessStep(
                    kind="run",
                    config={
                        "tool": "kms_search",
                        "args": {"query": "오늘의 일정과 우선순위"},
                    },
                ),
                SkillProcessStep(
                    kind="render",
                    config={"template": "오늘의 업무 브리핑입니다."},
                ),
            ]
        ),
    )


# ---------------------------------------------------------------------------
# 1) 정상 DI — ProcessRunner 가 init 됨
# ---------------------------------------------------------------------------


def test_factory_returns_process_runner_for_daily_briefing():
    """fix 회귀: ProcessRunner.__init__ 누락 인자로 None 반환되던 회귀 차단."""
    skill = _daily_briefing_skill()
    llm = _StubLLM()

    invoke_log: list[tuple[str, dict, dict]] = []

    async def _tool_invoker(name, args, slots):
        invoke_log.append((name, dict(args), dict(slots)))
        return "tool-ok"

    deps = OrchestratorDeps(
        llm_client=llm,
        skill_catalog={"daily_briefing": skill},
        tool_invoker=_tool_invoker,
    )
    factory = make_process_runner_factory(deps)
    runner = factory(skill_name="daily_briefing")

    assert runner is not None, (
        "ProcessRunner 가 None 반환되면 회귀 — llm_client/tool_invoker 누락 fix 깨짐"
    )
    assert isinstance(runner, ProcessRunner)
    assert runner.skill is skill
    assert runner.llm is llm
    assert runner.tool_invoker is _tool_invoker


# ---------------------------------------------------------------------------
# 2) tool_invoker 미주입 — _noop_tool_invoker fallback
# ---------------------------------------------------------------------------


def test_factory_uses_noop_tool_invoker_when_omitted():
    skill = _daily_briefing_skill()
    deps = OrchestratorDeps(
        llm_client=_StubLLM(),
        skill_catalog={"daily_briefing": skill},
    )
    factory = make_process_runner_factory(deps)
    runner = factory(skill_name="daily_briefing")

    assert runner is not None
    assert runner.tool_invoker is _noop_tool_invoker

    # noop 호출은 빈 문자열 반환
    out = _run(_noop_tool_invoker("any_tool", {}, {}))
    assert out == ""


# ---------------------------------------------------------------------------
# 3) advance() 가 TypeError 없이 동작 — init 결함 회귀 방지
# ---------------------------------------------------------------------------


def test_factory_runner_advance_does_not_raise_typeerror():
    skill = _daily_briefing_skill()
    llm = _StubLLM(
        [
            json.dumps({"slots": {"오늘 날짜": "2026-05-07", "우선순위": "PR review"}}),
        ]
    )

    async def _tool_invoker(name, args, slots):
        return ""

    deps = OrchestratorDeps(
        llm_client=llm,
        skill_catalog={"daily_briefing": skill},
        tool_invoker=_tool_invoker,
    )
    runner = make_process_runner_factory(deps)(skill_name="daily_briefing")
    assert runner is not None

    # 첫 진입 (user_input None) — elicit 의 question 만 응답으로 받아야 함.
    result = _run(runner.advance(user_input=None, state={}))
    # init 결함이면 여기 도달 전에 TypeError 로 죽음.
    assert "오늘의 업무와 우선순위" in result.response
    assert result.done is False


# ---------------------------------------------------------------------------
# 4) 알 수 없는 skill / process 없는 skill — None 반환 (정상 fallback)
# ---------------------------------------------------------------------------


def test_factory_returns_none_for_unknown_skill():
    deps = OrchestratorDeps(
        llm_client=_StubLLM(),
        skill_catalog={},
    )
    runner = make_process_runner_factory(deps)(skill_name="nonexistent")
    assert runner is None


def test_factory_returns_none_when_process_missing():
    skill_no_proc = SkillV2(name="x", description="d", process=None)
    deps = OrchestratorDeps(
        llm_client=_StubLLM(),
        skill_catalog={"x": skill_no_proc},
    )
    runner = make_process_runner_factory(deps)(skill_name="x")
    assert runner is None
