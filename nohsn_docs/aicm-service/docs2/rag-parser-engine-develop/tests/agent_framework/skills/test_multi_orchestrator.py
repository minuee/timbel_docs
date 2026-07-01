"""MultiSkillOrchestrator 테스트 — compound 판단/sub-skill 선택/병렬 실행/안전 필터."""

from __future__ import annotations

import asyncio
import json

from src.agent_framework.skills.multi_orchestrator import MultiSkillOrchestrator


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """callable 형식 LLM. 큐 순서대로 응답."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            return "{}"
        nxt = self.responses.pop(0)
        if isinstance(nxt, dict):
            return json.dumps(nxt, ensure_ascii=False)
        return nxt


class _Skill:
    def __init__(self, name, description, side_effect_level="read_only", consequential=False):
        self.name = name
        self.description = description
        self.side_effect_level = side_effect_level
        self.consequential = consequential


class _Registry:
    def __init__(self, skills):
        self._skills = list(skills)

    def list_skills(self):
        return list(self._skills)


class _StubRunner:
    def __init__(self, skill_name: str, response: str = "OK"):
        self.skill_name = skill_name
        self._response = response

    async def advance(self, *, user_input, state):
        return type(
            "R", (), {"response": f"[{self.skill_name}] {self._response}",
                       "next_state": {}, "done": True}
        )()


def _factory(response_per_skill: dict[str, str]):
    def _f(*, skill_name: str):
        return _StubRunner(skill_name, response_per_skill.get(skill_name, "OK"))
    return _f


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_compound_query_detected():
    llm = _ScriptedLLM([
        {"compound": True, "reason": "여러 도메인", "required_domains": ["schedule","expense","health"]},
        {"subskills": [
            {"name": "schedule_analyzer", "args": {"period_start": "2026-03-01"}},
            {"name": "expense_analyzer", "args": {"period_start": "2026-03-01"}},
        ]},
        "요약: 3월은 회의 5건, 식비 5만원...",
    ])
    skills = [
        _Skill("schedule_analyzer", "일정 분석"),
        _Skill("expense_analyzer", "지출 분석"),
        _Skill("expense_logger", "지출 기록", side_effect_level="write_external"),
    ]
    orch = MultiSkillOrchestrator(
        llm_client=llm,
        skill_registry=_Registry(skills),
        process_runner_factory=_factory({}),
    )
    out = _run(orch.run(user_text="3월 일정·지출 분석해줘"))
    assert out["compound"] is True
    assert set(out["subskills"]) == {"schedule_analyzer", "expense_analyzer"}
    assert "요약" in out["answer"]


def test_non_compound_falls_through():
    llm = _ScriptedLLM([
        {"compound": False, "reason": "단일 도메인"},
    ])
    skills = [_Skill("schedule_analyzer", "일정 분석")]
    orch = MultiSkillOrchestrator(
        llm_client=llm,
        skill_registry=_Registry(skills),
        process_runner_factory=_factory({}),
    )
    out = _run(orch.run(user_text="오늘 일정 알려줘"))
    assert out["compound"] is False
    assert "subskills" not in out  # caller 가 단일 매칭으로 fallback


def test_only_read_only_skills_eligible():
    """write_external/irreversible 은 자동 호출 후보에서 제외 — 사용자 승인 경로 필요."""
    llm = _ScriptedLLM([
        {"compound": True, "required_domains": ["expense"]},
        # LLM 이 환각해 write skill 을 골라도 필터에서 제외되어야 함
        {"subskills": [{"name": "expense_logger", "args": {}}]},
    ])
    skills = [
        _Skill("expense_logger", "지출 기록", side_effect_level="write_external"),
        _Skill("expense_analyzer", "지출 분석", side_effect_level="read_only"),
    ]
    orch = MultiSkillOrchestrator(
        llm_client=llm,
        skill_registry=_Registry(skills),
        process_runner_factory=_factory({}),
    )
    out = _run(orch.run(user_text="3월 지출 분석"))
    # eligible 에 expense_logger 가 없어 → LLM 이 골라도 filtering 후 빈 list
    assert out["compound"] is True
    assert out["subskills"] == []
    assert out["answer"] is None


def test_hallucinated_skill_filtered():
    llm = _ScriptedLLM([
        {"compound": True, "required_domains": ["schedule"]},
        {"subskills": [
            {"name": "no_such_skill", "args": {}},
            {"name": "schedule_analyzer", "args": {}},
        ]},
        "OK answer",
    ])
    skills = [_Skill("schedule_analyzer", "일정 분석")]
    orch = MultiSkillOrchestrator(
        llm_client=llm,
        skill_registry=_Registry(skills),
        process_runner_factory=_factory({}),
    )
    out = _run(orch.run(user_text="3월 일정 분석"))
    assert out["compound"] is True
    assert out["subskills"] == ["schedule_analyzer"]


def test_select_subskills_handles_invalid_json():
    llm = _ScriptedLLM(["not json at all"])
    skills = [_Skill("schedule_analyzer", "일정 분석")]
    orch = MultiSkillOrchestrator(
        llm_client=llm,
        skill_registry=_Registry(skills),
        process_runner_factory=_factory({}),
    )
    out = _run(orch.select_subskills(
        user_text="3월", required_domains=["schedule"], eligible_skills=skills,
    ))
    assert out == []


def test_runner_exception_caught_and_reported():
    """sub-skill runner 가 예외 던져도 다른 sub-skill 은 진행 + error 키로 합성 진입."""

    class _BoomRunner:
        def __init__(self, name): self.name = name

        async def advance(self, *, user_input, state):
            raise RuntimeError("boom")

    def _mixed_factory(*, skill_name):
        if skill_name == "schedule_analyzer":
            return _BoomRunner(skill_name)
        return _StubRunner(skill_name, "OK")

    llm = _ScriptedLLM([
        {"compound": True, "required_domains": ["schedule","expense"]},
        {"subskills": [
            {"name": "schedule_analyzer", "args": {}},
            {"name": "expense_analyzer", "args": {}},
        ]},
        "answer",
    ])
    skills = [
        _Skill("schedule_analyzer", "일정 분석"),
        _Skill("expense_analyzer", "지출 분석"),
    ]
    orch = MultiSkillOrchestrator(
        llm_client=llm,
        skill_registry=_Registry(skills),
        process_runner_factory=_mixed_factory,
    )
    out = _run(orch.run(user_text="3월 분석"))
    assert out["compound"] is True
    # 양쪽 모두 sub_results 에 들어옴 (하나는 error, 하나는 result)
    by_name = {r["name"]: r for r in out["sub_results"]}
    assert "error" in by_name["schedule_analyzer"]
    assert "result" in by_name["expense_analyzer"]
