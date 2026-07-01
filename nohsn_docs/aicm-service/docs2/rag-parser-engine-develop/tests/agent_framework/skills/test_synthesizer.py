"""Synthesizer 테스트 — sub_results → 한국어 답변 합성."""

from __future__ import annotations

import asyncio

from src.agent_framework.skills.synthesizer import synthesize


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _CaptureLLM:
    def __init__(self, return_text: str):
        self._return = return_text
        self.last_prompt: str | None = None

    async def __call__(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._return


def test_synthesize_combines_all_sub_results_into_prompt():
    llm = _CaptureLLM("3월은 회의가 많았고 식비가 컸어요.")
    out = _run(synthesize(
        return_legacy_str=True,
        user_text="3월 분석",
        sub_results=[
            {"name": "schedule_analyzer", "result": {"meetings": 5, "exercise": 2}},
            {"name": "expense_analyzer", "result": {"식비": 55000, "교통": 7000}},
        ],
        llm_client=llm,
    ))
    assert "3월" in out
    # prompt 안에 양쪽 sub-skill 데이터가 한글 그대로 들어감
    assert "schedule_analyzer" in (llm.last_prompt or "")
    assert "expense_analyzer" in (llm.last_prompt or "")
    assert "식비" in (llm.last_prompt or "")


def test_synthesize_handles_error_subresults():
    """error 키 가진 sub-skill 도 prompt 에 포함 → LLM 이 부분 답변 작성."""
    llm = _CaptureLLM("일정은 정리됐고 지출 데이터는 부족했어요.")
    out = _run(synthesize(
        return_legacy_str=True,
        user_text="3월 분석",
        sub_results=[
            {"name": "schedule_analyzer", "result": {"meetings": 3}},
            {"name": "expense_analyzer", "error": "DB connection failed"},
        ],
        llm_client=llm,
    ))
    assert "데이터" in out or "부족" in out
    assert "ERROR" in (llm.last_prompt or "")


def test_synthesize_with_empty_sub_results():
    llm = _CaptureLLM("분석할 데이터가 없습니다.")
    out = _run(synthesize(
        return_legacy_str=True,
        user_text="3월 분석",
        sub_results=[],
        llm_client=llm,
    ))
    assert "데이터" in out
    assert "서브 스킬 결과 없음" in (llm.last_prompt or "")


def test_synthesize_supports_generate_method():
    """generate(prompt) 인터페이스도 지원."""

    class _GenLLM:
        def __init__(self): self.last = None

        async def generate(self, prompt: str) -> str:
            self.last = prompt
            return "via generate"

    llm = _GenLLM()
    out = _run(synthesize(
        return_legacy_str=True,
        user_text="질문",
        sub_results=[{"name": "x", "result": {"k": 1}}],
        llm_client=llm,
    ))
    assert out == "via generate"
    assert llm.last is not None
