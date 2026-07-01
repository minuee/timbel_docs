"""Multi-turn context fix (2026-05-07) — compose prompt + history inject 단위 검증.

검증 항목:
1. ``_build_compose_prompt`` 가 ``recent_history`` 인자를 받으면 user payload 에
   ``recent_history`` 키로 포함시킨다.
2. ``recent_history`` 가 None / 빈 리스트면 payload 에 키 자체가 없어 byte-equal
   호환 (옛 호출자 / snapshot 회귀 0).
3. ``_COMPOSE_SYSTEM_RULES`` 에 발화 유형 4 분기 (action / info / follow-up /
   chitchat) 가 명시되어 있다.
4. content 200 자 클립 적용.
5. role / content 누락 entry 는 skip.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agent_framework.runtime.engine import (
    AgentEngine,
    _COMPOSE_SYSTEM_RULES,
)
from src.agent_framework.runtime.session_store import SessionStore
from src.agent_framework.tools.registry import ToolRegistry


def _make_engine(redis_client) -> AgentEngine:
    """compose prompt 호출에 필요한 최소 engine 구성 — LLM 은 MagicMock 1단."""
    from src.agent_framework.llm.fallback_router import FallbackDecision

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["info_lookup"])
    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    async def _stream(tpl, ctx, **kwargs):
        yield "ok"

    response_gen = MagicMock()
    response_gen.stream = _stream
    # _build_compose_prompt 는 self.response_generator.llm 또는 self.llm 에서 LLM 가져옴.
    response_gen.llm = MagicMock()
    response_gen.llm.complete = AsyncMock(return_value="답변")
    fallback = AsyncMock()
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="")
    )

    return AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry({}),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
    )


@pytest.mark.asyncio
async def test_recent_history_injected_into_payload(redis_client):
    engine = _make_engine(redis_client)
    history = [
        {"role": "user", "content": "환불 정책 알려줘"},
        {"role": "assistant", "content": "환불은 7일 이내 가능합니다."},
        {"role": "user", "content": "그럼 부분 환불도 가능해?"},
    ]
    _llm, system, user = await engine._build_compose_prompt(
        user_message="그럼 부분 환불도 가능해?",
        tool_results=[],
        user_preference=None,
        citation_items=None,
        recent_history=history,
    )
    assert _llm is not None
    assert system is not None
    assert user is not None
    # user payload 가 JSON 으로 시작 (cite_block 은 끝에 붙음).
    payload = json.loads(user.split("\n## ")[0]) if user.startswith("{") else json.loads(user)
    assert "recent_history" in payload
    assert len(payload["recent_history"]) == 3
    assert payload["recent_history"][-1]["content"] == "그럼 부분 환불도 가능해?"


@pytest.mark.asyncio
async def test_recent_history_none_keeps_legacy_payload(redis_client):
    """history None 이면 key 자체가 없어 옛 동작 byte-equal."""
    engine = _make_engine(redis_client)
    _llm, system, user = await engine._build_compose_prompt(
        user_message="안녕",
        tool_results=[],
        user_preference=None,
        citation_items=None,
        recent_history=None,
    )
    payload = json.loads(user)
    assert "recent_history" not in payload
    assert payload["user_message"] == "안녕"


@pytest.mark.asyncio
async def test_recent_history_empty_list_keeps_legacy_payload(redis_client):
    engine = _make_engine(redis_client)
    _llm, system, user = await engine._build_compose_prompt(
        user_message="안녕",
        tool_results=[],
        user_preference=None,
        citation_items=None,
        recent_history=[],
    )
    payload = json.loads(user)
    assert "recent_history" not in payload


@pytest.mark.asyncio
async def test_recent_history_clip_to_200_chars(redis_client):
    engine = _make_engine(redis_client)
    long_text = "가" * 500
    _llm, system, user = await engine._build_compose_prompt(
        user_message="요약해줘",
        tool_results=[],
        recent_history=[{"role": "assistant", "content": long_text}],
    )
    payload = json.loads(user)
    assert "recent_history" in payload
    assert len(payload["recent_history"]) == 1
    clipped = payload["recent_history"][0]["content"]
    # 200자 + "..." (총 200자 이상 - 클립 후 + suffix)
    assert clipped.endswith("...")
    assert len(clipped) <= 210  # 200 + ... + slack


@pytest.mark.asyncio
async def test_recent_history_skips_invalid_entries(redis_client):
    engine = _make_engine(redis_client)
    history = [
        {"role": "user", "content": "정상"},
        {"role": "", "content": "role 빈값 — skip"},
        {"role": "assistant", "content": ""},  # content 빈값 — skip
        {"content": "role 누락 — skip"},
        {"role": "user", "content": "두번째 정상"},
    ]
    _llm, system, user = await engine._build_compose_prompt(
        user_message="현재",
        tool_results=[],
        recent_history=history,
    )
    payload = json.loads(user)
    assert len(payload["recent_history"]) == 2
    assert payload["recent_history"][0]["content"] == "정상"
    assert payload["recent_history"][1]["content"] == "두번째 정상"


@pytest.mark.asyncio
async def test_recent_history_role_whitelist(redis_client):
    """GPT-5 P1 fix — user/assistant 외 role 은 skip (tool/system 오염 차단)."""
    engine = _make_engine(redis_client)
    history = [
        {"role": "user", "content": "정상 user"},
        {"role": "tool", "content": "tool 결과 — skip 되어야 함"},
        {"role": "system", "content": "system 메시지 — skip 되어야 함"},
        {"role": "assistant", "content": "정상 assistant"},
        {"role": "User", "content": "case-insensitive — 통과"},
    ]
    _llm, system, user = await engine._build_compose_prompt(
        user_message="현재",
        tool_results=[],
        recent_history=history,
    )
    payload = json.loads(user)
    assert len(payload["recent_history"]) == 3
    assert payload["recent_history"][0]["content"] == "정상 user"
    assert payload["recent_history"][1]["content"] == "정상 assistant"
    assert payload["recent_history"][2]["content"] == "case-insensitive — 통과"
    # role 은 lowercase 정규화
    assert payload["recent_history"][2]["role"] == "user"


@pytest.mark.asyncio
async def test_recent_history_keeps_last_6_only(redis_client):
    engine = _make_engine(redis_client)
    # 10 entries — 마지막 6 만 inject.
    history = [
        {"role": "user", "content": f"발화 {i}"} for i in range(10)
    ]
    _llm, system, user = await engine._build_compose_prompt(
        user_message="현재",
        tool_results=[],
        recent_history=history,
    )
    payload = json.loads(user)
    assert len(payload["recent_history"]) == 6
    # 마지막 6 = 인덱스 4-9
    assert payload["recent_history"][0]["content"] == "발화 4"
    assert payload["recent_history"][-1]["content"] == "발화 9"


def test_compose_system_rules_has_4_branch():
    """4 발화 유형 분기 명시 검증."""
    text = _COMPOSE_SYSTEM_RULES
    assert "Action" in text or "action" in text
    assert "Info" in text or "info" in text
    assert "Follow-up" in text or "follow-up" in text
    assert "Chitchat" in text or "chitchat" in text
    # 우선순위 룰
    assert "action > follow-up > info > chitchat" in text
    # 컨텍스트 활용 강조
    assert "recent_history" in text
    # 5요소 template 금지 명시 (info / follow-up)
    assert "5요소 template" in text or "5요소 헤더" in text


def test_compose_system_rules_keeps_action_5_elements():
    """action 발화는 5요소 명시 유지 (시연 path 회귀 0)."""
    text = _COMPOSE_SYSTEM_RULES
    # action 섹션의 5요소
    assert "요청 의도" in text
    assert "핵심 슬롯 echo" in text
    assert "실행 가능/불가 상태" in text
    assert "다음 행동 또는 안내" in text
