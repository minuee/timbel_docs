"""Wave Wire-up Final — engine.turn() 의 SkillV2 auto_loader/persona_loader 실 wire 검증.

KMS_AUTO_SKILL_ENABLED=true 일 때만 SSE 이벤트 ``skill_activated`` 가 발화되는지,
매칭 없음 시 흐름이 막히지 않는지 검증.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools import calendar_mock
from src.agent_framework.tools.registry import ToolRegistry


class _FakeLLMComplete:
    """auto_loader 가 요구하는 LLMClient.complete(system, user, *, response_format=...)."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, *, response_format: str | None = None) -> str:
        self.calls.append((system, user))
        return self.response


def _build_engine_with_llm(redis_client, *, llm) -> AgentEngine:
    from src.agent_framework.llm.fallback_router import FallbackDecision

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["book_appointment"])
    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    async def stream_response(tpl, ctx, **kwargs):
        yield "응답"

    response_gen = MagicMock()
    response_gen.stream = stream_response
    # response_gen 에 .llm attr 노출 — engine 이 이걸 LLM 클라이언트로 인식.
    response_gen.llm = llm
    fallback = AsyncMock()
    # PR-AA2 — slot 미충족 시 fallback 호출 — proper FallbackDecision stub 필수.
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    return AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )


@pytest.mark.asyncio
async def test_skill_activated_event_when_flag_on_and_matched(redis_client, monkeypatch):
    """KMS_AUTO_SKILL_ENABLED=true + LLM 이 카탈로그 내 skill 선택 → SSE skill_activated."""
    calendar_mock._reset()
    monkeypatch.setenv("KMS_AUTO_SKILL_ENABLED", "true")
    # Wave V4 — orchestrator wire 가 LLM call count 에 끼지 않도록 격리.
    monkeypatch.delenv("KMS_MULTI_ORCHESTRATOR_ENABLED", raising=False)

    # auto_loader 의 LLM 응답 — study_planner (personal tenant 통과 + tenant_scope=['personal']).
    # 2026-04-25 V5-P0: kb_soldiers_counselor 는 tenant_scope=['kb_callcenter','kb_bank'] 라서
    # 기본 'tenant-x' personal tenant 에서는 scope filter 에 차단됨. 테스트 본질은 LLM 이
    # 카탈로그 내 skill 선택 시 SSE skill_activated 가 emit 되는 것이라, scope 통과하는
    # study_planner 로 검증.
    fake_llm = _FakeLLMComplete(
        '{"skill_name": "study_planner", "confidence": 0.92, "reason": "시험 계획"}'
    )
    engine = _build_engine_with_llm(redis_client, llm=fake_llm)

    events: list[dict[str, Any]] = []
    async for evt in engine.turn("s_skill_v2_1", "tenant-x", "내일 시험 어떻게 준비하지"):
        events.append(evt)

    activated_events = [e for e in events if e["event"] == "skill_activated"]
    assert len(activated_events) == 1, (
        f"expected 1 skill_activated, got events={[e['event'] for e in events]}"
    )
    data = activated_events[0]["data"]
    assert data["name"] == "study_planner"
    assert data.get("persona") is not None
    # LLM 이 정확히 한 번 호출 (auto_loader.select_skill)
    assert len(fake_llm.calls) == 1


@pytest.mark.asyncio
async def test_no_skill_activated_event_when_flag_off(redis_client, monkeypatch):
    """env flag default false (또는 명시 false) — auto_loader 호출 안 됨."""
    calendar_mock._reset()
    monkeypatch.delenv("KMS_AUTO_SKILL_ENABLED", raising=False)
    # Wave V4 — orchestrator wire 가 별도 flag 라 LLM call count 에 끼지 않도록 격리.
    monkeypatch.delenv("KMS_MULTI_ORCHESTRATOR_ENABLED", raising=False)

    fake_llm = _FakeLLMComplete(
        '{"skill_name": "kb_soldiers_counselor", "confidence": 0.95, "reason": "..."}'
    )
    engine = _build_engine_with_llm(redis_client, llm=fake_llm)

    events: list[dict[str, Any]] = []
    async for evt in engine.turn("s_skill_v2_2", "tenant-y", "장병적금 가입"):
        events.append(evt)

    assert not any(e["event"] == "skill_activated" for e in events)
    # LLM 도 호출되지 않아야 함 (flag off)
    assert len(fake_llm.calls) == 0


@pytest.mark.asyncio
async def test_no_match_does_not_break_turn(redis_client, monkeypatch):
    """flag on + LLM 이 빈 skill_name 반환 → skill_activated 미발화 + turn 정상 종료."""
    calendar_mock._reset()
    monkeypatch.setenv("KMS_AUTO_SKILL_ENABLED", "true")
    monkeypatch.delenv("KMS_MULTI_ORCHESTRATOR_ENABLED", raising=False)

    fake_llm = _FakeLLMComplete(
        '{"skill_name": "", "confidence": 0.0, "reason": "no match"}'
    )
    engine = _build_engine_with_llm(redis_client, llm=fake_llm)

    events: list[dict[str, Any]] = []
    async for evt in engine.turn("s_skill_v2_3", "tenant-z", "그냥 안녕"):
        events.append(evt)

    assert not any(e["event"] == "skill_activated" for e in events)
    # done 은 정상 발화
    assert any(e["event"] == "done" for e in events)
