"""self_check — 답변 자기 검증 (LLM mock)."""

from __future__ import annotations

import pytest

from src.agent_framework.conversation.self_check import SelfCheck


class _FakeLLM:
    def __init__(self, out: str):
        self.out = out
        self.last_user: str = ""

    async def complete(self, system: str, user: str, *, response_format=None) -> str:
        self.last_user = user
        return self.out


class _FailingLLM:
    async def complete(self, system: str, user: str, *, response_format=None) -> str:
        raise RuntimeError("network down")


class TestSelfCheck:
    @pytest.mark.asyncio
    async def test_no_llm_returns_consistent(self):
        sc = SelfCheck(llm=None)
        r = await sc.check(question="?", answer="...")
        assert r.consistent is True
        assert r.confidence == 1.0

    @pytest.mark.asyncio
    async def test_consistent_response(self):
        sc = SelfCheck(
            llm=_FakeLLM(
                '{"consistent": true, "confidence": 0.92, "note": "근거 명확"}'
            )
        )
        r = await sc.check(question="결제일?", answer="T+2 입니다.")
        assert r.consistent is True
        assert r.confidence == pytest.approx(0.92, abs=0.001)
        assert "근거" in r.note

    @pytest.mark.asyncio
    async def test_inconsistent_response(self):
        sc = SelfCheck(
            llm=_FakeLLM(
                '{"consistent": false, "confidence": 0.4, "note": "출처 불일치"}'
            )
        )
        r = await sc.check(question="?", answer="...")
        assert r.consistent is False
        assert r.note == "출처 불일치"

    @pytest.mark.asyncio
    async def test_invalid_json_safe_default(self):
        sc = SelfCheck(llm=_FakeLLM("not a json"))
        r = await sc.check(question="?", answer="...")
        # safe default — consistent True, mid confidence
        assert r.consistent is True
        assert r.confidence == 0.5

    @pytest.mark.asyncio
    async def test_llm_exception_safe_default(self):
        sc = SelfCheck(llm=_FailingLLM())
        r = await sc.check(question="?", answer="...")
        assert r.consistent is True
        assert r.confidence == 0.5

    @pytest.mark.asyncio
    async def test_citations_passed_to_prompt(self):
        llm = _FakeLLM('{"consistent": true, "confidence": 0.8}')
        sc = SelfCheck(llm=llm)
        await sc.check(
            question="결제일?",
            answer="T+2",
            citations=[{"doc_id": "a", "title": "매매제도"}],
        )
        assert "매매제도" in llm.last_user
