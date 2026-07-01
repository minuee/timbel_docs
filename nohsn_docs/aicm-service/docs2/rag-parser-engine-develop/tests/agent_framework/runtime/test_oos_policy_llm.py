"""OOS policy LLM enforcement (2026-05-07).

KMS-Plus role agent 의 *도메인 외 발화 정책* 이 LLM prompt 에 강제 inject
되는지 회귀 검증.

회귀 시나리오 — KB 봇이 "배달 취소" 발화 받고 우연 매칭 chunk 로 일반 응답
시도 → 거절 응답 안 나옴. 5 role agent 의 cross-domain 발화 모두 동일 패턴.

테스트 범위:
1. to_binding_policy_block() — guidelines_md 가 [BINDING POLICY] block 으로 추출.
2. to_prompt_section() — binding policy 가 *맨 앞* prepend (일반 ## 섹션 위).
3. _llm_compose_tool_answer system prompt — agent_context set 시 binding policy
   가 system prompt 의 *맨 앞* 에 prepend.
4. relevance gate — kms_rag.search hits 가 비거나 top1 score < 0.3 이면
   no_relevant_content / oos_hint 를 user payload 에 inject.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.agent_framework.runtime.agent_context import AgentContext


# ---- 공통 fixture ----

def _kb_role_agent() -> AgentContext:
    """KB 장병내일적금 role agent — 도메인 외 발화 정책 명시."""
    return AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="KB 장병내일적금 상담",
        goal="장병내일적금 가입·조회 안내",
        guidelines_md=(
            "## 역할\nKB 장병내일적금 상품 안내만 응대.\n\n"
            "## 도메인 외 발화 정책\n"
            "장병내일적금 외 모든 토픽 (배달/주가/날씨/타사 상품) 은 다음 문장으로 거절:\n"
            "'이 상담은 KB 장병내일적금 관련 문의만 응대합니다.'\n"
        ),
        primary_repo_ids=[uuid4()],
        fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"],
        done_when=None,
        kind="role",
    )


def _musinsa_agent() -> AgentContext:
    return AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="무신사 고객상담",
        goal="배송·교환·반품 안내",
        guidelines_md=(
            "## 역할\n무신사 주문/배송/교환/반품 안내만 응대.\n\n"
            "## 도메인 외 발화 정책\n"
            "쇼핑·무신사 외 모든 토픽 거절: '이 상담은 무신사 쇼핑 관련 문의만 응대합니다.'\n"
        ),
        primary_repo_ids=[uuid4()],
        fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"],
        done_when=None,
        kind="role",
    )


def _samchully_agent() -> AgentContext:
    return AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="삼천리가스 상담",
        goal="도시가스 요금/안전 안내",
        guidelines_md=(
            "## 역할\n삼천리가스 도시가스 안내만 응대.\n\n"
            "## 도메인 외 발화 정책\n"
            "도시가스 외 토픽 거절: '이 상담은 삼천리가스 도시가스 관련 문의만 응대합니다.'\n"
        ),
        primary_repo_ids=[uuid4()],
        fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"],
        done_when=None,
        kind="role",
    )


# ---- 1. to_binding_policy_block() ----

def test_binding_policy_block_extracts_guidelines():
    ctx = _kb_role_agent()
    block = ctx.to_binding_policy_block()
    assert block, "binding policy block 이 비어 있으면 안 된다"
    assert "[BINDING POLICY" in block
    assert "[/BINDING POLICY]" in block
    assert "KB 장병내일적금" in block
    assert "도메인 외 발화 정책" in block
    # OOS guard 한 줄 자동 강제 (guidelines_md 안에 정책 있어도 추가).
    assert "도메인 외" in block or "도메인·역할과 무관" in block


def test_binding_policy_block_empty_guidelines_returns_empty():
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="x", goal="y", guidelines_md="",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None, kind="role",
    )
    assert ctx.to_binding_policy_block() == ""


def test_binding_policy_block_admin_label():
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="Locus", goal="비서",
        guidelines_md="all enabled",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None, kind="admin",
    )
    block = ctx.to_binding_policy_block()
    assert "admin" in block


# ---- 2. to_prompt_section() — binding policy 가 *맨 앞* prepend ----

def test_to_prompt_section_binding_policy_at_top():
    """guidelines_md 의 [BINDING POLICY] block 이 ## current agent 섹션 *위* 에
    위치해야 한다. LLM 이 정책 우선 적용하도록.
    """
    ctx = _kb_role_agent()
    text = ctx.to_prompt_section()
    binding_idx = text.find("[BINDING POLICY")
    section_idx = text.find("## current agent")
    assert binding_idx != -1, "[BINDING POLICY] 가 prompt 에 없다"
    assert section_idx != -1, "## current agent 헤더가 prompt 에 없다"
    assert binding_idx < section_idx, (
        "[BINDING POLICY] 는 ## current agent 보다 *앞* 에 있어야 한다 — "
        f"binding_idx={binding_idx} section_idx={section_idx}"
    )


def test_to_prompt_section_empty_guidelines_no_binding():
    """guidelines_md 비어 있으면 binding policy 자체가 없음 (회귀 0)."""
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="x", goal="y", guidelines_md="",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None, kind="role",
    )
    text = ctx.to_prompt_section()
    assert "[BINDING POLICY" not in text
    # ## current agent 는 그대로 노출 (기존 동작 회귀 0).
    assert "## current agent" in text


# ---- 3. _llm_compose_tool_answer — binding policy injection ----

@pytest.mark.asyncio
async def test_compose_tool_answer_injects_binding_policy_for_role_agent():
    """role agent path 에서 _llm_compose_tool_answer 의 system prompt 첫 줄이
    [BINDING POLICY] 로 시작해야 한다. LLM 이 OOS 정책 우선 적용.
    """
    from src.agent_framework.runtime.engine import AgentEngine

    captured_system = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured_system["system"] = system
            captured_system["user"] = user
            return "MOCK ANSWER"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _kb_role_agent()
    eng._is_admin_agent = False

    tool_results = [
        {
            "tool": "kms_rag.search",
            "result": {
                "hits": [
                    {"title": "KB 장병내일적금 약관 제3조",
                     "score": 0.42, "content": "..."},
                ],
                "summary": "검색 결과 1건",
            },
        }
    ]
    out = await eng._llm_compose_tool_answer(
        user_message="배달 취소 어떻게 해?",
        tool_results=tool_results,
        user_preference=None,
        citation_items=None,
    )
    assert out == "MOCK ANSWER"
    sys_prompt = captured_system["system"]
    assert sys_prompt.startswith("[BINDING POLICY"), (
        "system prompt 의 첫 부분이 [BINDING POLICY] 로 시작해야 한다 — "
        f"실제 prefix={sys_prompt[:80]!r}"
    )
    assert "KB 장병내일적금" in sys_prompt
    assert "도메인 외 발화 정책" in sys_prompt


@pytest.mark.asyncio
async def test_compose_tool_answer_no_agent_context_byte_equal():
    """agent_context 미설정 (default chat) 시 binding policy 가 없어야 한다.
    회귀 0 보장.
    """
    from src.agent_framework.runtime.engine import AgentEngine

    captured_system = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured_system["system"] = system
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = None
    eng._is_admin_agent = False

    out = await eng._llm_compose_tool_answer(
        user_message="hi",
        tool_results=[{"tool": "weather.lookup", "result": {"summary": "맑음"}}],
        user_preference=None,
        citation_items=None,
    )
    assert "[BINDING POLICY" not in captured_system["system"]


# ---- 4. relevance gate — no_relevant_content 신호 ----

@pytest.mark.asyncio
async def test_compose_tool_answer_relevance_gate_empty_hits():
    """D84 (2026-05-13) — strict isolation + KMS hits 0 → runtime hard gate.

    이전 동작: payload['fallback_hint'] 주입 → LLM 일반지식 답변.
    새 동작: LLM 호출 자체 차단, 중앙화된 거절 응답 반환. captured["user"]
    는 채워지지 않음 (LLM 미호출).
    """
    from src.agent_framework.runtime.engine import AgentEngine
    from src.agent_framework.runtime.strict_evidence_policy import (
        STRICT_NO_EVIDENCE_REFUSAL,
    )

    captured = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured["user"] = user
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _musinsa_agent()  # knowledge_isolation="strict"
    eng._is_admin_agent = False

    out = await eng._llm_compose_tool_answer(
        user_message="주가 알려줘",
        tool_results=[
            {"tool": "kms_rag.search",
             "result": {"hits": [], "summary": "검색 결과 0건"}},
        ],
        user_preference=None,
        citation_items=None,
    )
    # strict gate — LLM 호출 자체 차단.
    assert out == STRICT_NO_EVIDENCE_REFUSAL
    assert "user" not in captured  # LLM 미호출 검증.


@pytest.mark.asyncio
async def test_compose_tool_answer_relevance_gate_low_score():
    """D84 — strict + KMS top1 score < 0.3 → runtime hard gate (refuse)."""
    from src.agent_framework.runtime.engine import AgentEngine
    from src.agent_framework.runtime.strict_evidence_policy import (
        STRICT_NO_EVIDENCE_REFUSAL,
    )

    captured = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured["user"] = user
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _samchully_agent()  # knowledge_isolation="strict"
    eng._is_admin_agent = False

    out = await eng._llm_compose_tool_answer(
        user_message="오늘 날씨 알려줘",
        tool_results=[
            {"tool": "kms_rag.search",
             "result": {
                 "hits": [{"title": "도시가스 요금표", "score": 0.12,
                           "content": "..."}],
                 "summary": "검색 결과 1건",
             }},
        ],
        user_preference=None,
        citation_items=None,
    )
    assert out == STRICT_NO_EVIDENCE_REFUSAL
    assert "user" not in captured


@pytest.mark.asyncio
async def test_compose_tool_answer_relevance_gate_high_score_no_signal():
    """top1 score >= 0.3 이면 no_relevant_content 신호 *없음* (정상 응답 path)."""
    from src.agent_framework.runtime.engine import AgentEngine

    captured = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured["user"] = user
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _kb_role_agent()
    eng._is_admin_agent = False

    await eng._llm_compose_tool_answer(
        user_message="장병적금 가입 조건 알려줘",
        tool_results=[
            {"tool": "kms_rag.search",
             "result": {
                 "hits": [{"title": "KB 장병내일적금 가입조건", "score": 0.78,
                           "content": "만 19~28세, 군 복무 중 가입 가능"}],
                 "summary": "검색 결과 1건",
             }},
        ],
        user_preference=None,
        citation_items=None,
    )
    payload_text = captured["user"]
    payload = json.loads(payload_text.split("\n## 참고 후보")[0])
    # no_relevant_content 가 *없거나* false. 정상 응답 path.
    assert not payload.get("no_relevant_content", False)


@pytest.mark.asyncio
async def test_compose_tool_answer_strict_fail_closed_on_evaluate_error(
    monkeypatch,
):
    """D84 GPT-5.5 사전 권고 — strict 는 evaluate_evidence 자체 실패 시에도
    fail-closed (거절 응답 반환). priority/broad 는 fail-open (기존 path).
    """
    from src.agent_framework.runtime.engine import AgentEngine
    from src.agent_framework.runtime import strict_evidence_policy as _sep
    from src.agent_framework.runtime.strict_evidence_policy import (
        STRICT_NO_EVIDENCE_REFUSAL,
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("evaluate_evidence forced failure")

    monkeypatch.setattr(_sep, "evaluate_evidence", _boom)

    captured = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured["user"] = user
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _musinsa_agent()  # knowledge_isolation="strict"
    eng._is_admin_agent = False

    out = await eng._llm_compose_tool_answer(
        user_message="아무거나",
        tool_results=[
            {"tool": "kms_rag.search", "result": {"hits": [{"score": 0.9}]}},
        ],
        user_preference=None,
        citation_items=None,
    )
    # strict — fail-closed: 평가 실패해도 거절 응답.
    assert out == STRICT_NO_EVIDENCE_REFUSAL
    assert "user" not in captured  # LLM 미호출.


@pytest.mark.asyncio
async def test_compose_tool_answer_metric_failure_does_not_block_refuse(
    monkeypatch,
):
    """D84 GPT-5.5 사전 권고 — metric inc 가 실패해도 refusal 반환은 진행."""
    from src.agent_framework.runtime.engine import AgentEngine
    from src.agent_framework.runtime.strict_evidence_policy import (
        STRICT_NO_EVIDENCE_REFUSAL,
    )
    from src.common import metrics as _metrics

    class _ExplodingCounter:
        def labels(self, *args, **kwargs):
            raise RuntimeError("metric system down")

    monkeypatch.setattr(
        _metrics, "KMS_STRICT_NO_EVIDENCE_REFUSAL_TOTAL", _ExplodingCounter(),
    )

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = MagicMock()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = _musinsa_agent()  # strict, 0 hits → refuse path.
    eng._is_admin_agent = False

    out = await eng._llm_compose_tool_answer(
        user_message="아무거나",
        tool_results=[
            {"tool": "kms_rag.search", "result": {"hits": []}},
        ],
        user_preference=None,
        citation_items=None,
    )
    assert out == STRICT_NO_EVIDENCE_REFUSAL


@pytest.mark.asyncio
async def test_compose_tool_answer_admin_no_relevance_gate():
    """admin agent (Locus) 는 OOS 가드 약함 — _is_admin_agent True 인 경우
    relevance gate 자체를 우회해야 한다 (회귀 0). admin 은 자기 비서 path."""
    from src.agent_framework.runtime.engine import AgentEngine

    captured = {}

    class _MockLLM:
        async def complete(self, system, user, response_format=None):
            captured["user"] = user
            return "MOCK"

    eng = AgentEngine.__new__(AgentEngine)
    eng.llm = _MockLLM()
    eng.response_generator = MagicMock()
    eng.fallback_router = MagicMock()
    eng._agent_context = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="Locus", goal="비서", guidelines_md="all enabled",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None, kind="admin",
    )
    eng._is_admin_agent = True

    await eng._llm_compose_tool_answer(
        user_message="아무거나",
        tool_results=[
            {"tool": "kms_rag.search",
             "result": {"hits": [], "summary": "0건"}},
        ],
        user_preference=None,
        citation_items=None,
    )
    payload_text = captured["user"]
    payload = json.loads(payload_text.split("\n## 참고 후보")[0])
    assert not payload.get("no_relevant_content", False)
