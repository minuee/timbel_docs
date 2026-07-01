"""BindingGate (L8) — OOS fast-track 분류 단위 검증.

회귀 케이스:
- in_scope=true → GateDecision.in_scope=True, rejection_message=""
- in_scope=false → GateDecision.in_scope=False, rejection_message 채워짐
- LLM 타임아웃 → in_scope=True default (안전 fallback)
- LLM 호출 실패 → in_scope=True default
- malformed JSON → in_scope=True default
- 짧은 발화 (인사 등) → in_scope=True (도메인 추정 모호)
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.agent_framework.runtime.agent_context import AgentContext
from src.agent_framework.runtime.binding_gate import BindingGate, GateDecision


def _make_role_agent_ctx(name: str = "KB 장병", goal: str = "적금 가입 안내") -> AgentContext:
    return AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name=name, goal=goal,
        guidelines_md="## 역할\n장병내일적금 안내만 응대.",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"], done_when=None, kind="role",
    )


class _FakeLLM:
    def __init__(self, response: str | None = None, raise_exc: Exception | None = None,
                 sleep_s: float = 0.0):
        self.response = response
        self.raise_exc = raise_exc
        self.sleep_s = sleep_s
        self.calls = 0

    async def complete(self, system: str, user: str, **kwargs) -> str:
        self.calls += 1
        if self.sleep_s > 0:
            await asyncio.sleep(self.sleep_s)
        if self.raise_exc:
            raise self.raise_exc
        return self.response or ""


@pytest.mark.asyncio
async def test_in_scope_pass_returns_decision_true():
    llm = _FakeLLM(response=json.dumps({"in_scope": True, "reason": "도메인 안"}))
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("적금 가입 어떻게 해?", ctx)
    assert d.in_scope is True
    assert d.rejection_message == ""
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_out_of_scope_returns_rejection():
    llm = _FakeLLM(response=json.dumps({"in_scope": False, "reason": "가스 폭발 OOS"}))
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("가스 폭발 위험 알려줘", ctx)
    assert d.in_scope is False
    assert d.rejection_message
    # rejection 은 agent.name 과 goal 을 echo.
    assert "KB 장병" in d.rejection_message
    assert "적금 가입" in d.rejection_message


@pytest.mark.asyncio
async def test_timeout_falls_back_to_in_scope():
    """LLM 응답 타임아웃 → 안전 fallback (in_scope=True)."""
    llm = _FakeLLM(sleep_s=2.0, response=json.dumps({"in_scope": False}))
    gate = BindingGate(llm, timeout_s=0.3)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("가스 폭발 위험 알려줘", ctx)
    assert d.in_scope is True
    assert d.reason == "timeout_default_pass"


@pytest.mark.asyncio
async def test_call_failure_falls_back():
    llm = _FakeLLM(raise_exc=RuntimeError("vllm down"))
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("가입 한도?", ctx)
    assert d.in_scope is True
    assert d.reason == "call_failed_default_pass"


@pytest.mark.asyncio
async def test_malformed_json_falls_back():
    llm = _FakeLLM(response="not json at all")
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("배달 시킬 수 있어?", ctx)
    assert d.in_scope is True
    assert d.reason == "parse_failed_default_pass"


@pytest.mark.asyncio
async def test_short_message_skips_llm_call():
    """짧은 발화 (인사 등) 는 LLM 안 부르고 즉시 in_scope=True."""
    llm = _FakeLLM(response=json.dumps({"in_scope": False}))
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("안녕", ctx)
    assert d.in_scope is True
    assert d.reason == "too_short_inconclusive"
    # LLM 호출 미발생.
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_empty_message_skips_llm_call():
    llm = _FakeLLM(response=json.dumps({"in_scope": False}))
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("", ctx)
    assert d.in_scope is True
    assert d.reason == "empty_message"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_no_agent_context_passes():
    llm = _FakeLLM(response=json.dumps({"in_scope": False}))
    gate = BindingGate(llm)
    d = await gate.classify("아무 발화", agent_context=None)
    assert d.in_scope is True
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_fenced_json_response_is_parsed():
    """LLM 이 ```json fence 로 감싸 반환해도 파싱 성공."""
    fenced = "```json\n" + json.dumps({"in_scope": False, "reason": "OOS"}) + "\n```"
    llm = _FakeLLM(response=fenced)
    gate = BindingGate(llm)
    ctx = _make_role_agent_ctx()
    d = await gate.classify("가스 폭발 위험 알려줘", ctx)
    assert d.in_scope is False
