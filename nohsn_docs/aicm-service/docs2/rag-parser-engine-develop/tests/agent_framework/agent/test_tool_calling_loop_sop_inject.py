"""#76 (2026-05-19) — ToolCallingLoop SOP RAG inject 검증.

사용자 발견: SOP repo 등록해도 ToolCallingLoop path 의 system_prompt 에
inject 안 됨. 본 라운드 fix 는 agent_context 가 들어오면 binding policy +
SOP context 를 system 메시지에 prepend (단일 system role).

테스트 시나리오:
- agent_context=None: 기존 동작 byte-equal (회귀 0).
- agent_context + SOP chunks (mock): system 에 [SOP CONTEXT] 포함.
- agent_context + sop_repo_ids=[]: SOP block 없음, binding_policy 만 prepend.
- SOP search exception: fail-open (기존 prompt 로 fallback).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.agent_framework.agent.tool_calling_loop import ToolCallingLoop
from src.agent_framework.tools.registry import ToolRegistry


@dataclass
class _AgentCtxStub:
    """AgentContext minimal stub (테스트 전용)."""

    agent_id: UUID = field(default_factory=uuid4)
    tenant_id: UUID = field(default_factory=uuid4)
    name: str = "테스트 봇"
    goal: str = "테스트 목적"
    guidelines_md: str = ""
    primary_repo_ids: list = field(default_factory=list)
    fallback_repo_ids: list = field(default_factory=list)
    sop_repo_ids: list = field(default_factory=list)
    allowed_tools: list = field(default_factory=list)
    knowledge_isolation: str = "priority"
    kind: str = "role"
    is_admin: bool = False
    done_when: str | None = None

    def to_binding_policy_block(self, *, sop_rag_mode: bool = False) -> str:
        # 단순 stub — 실 동작은 agent_context.py 의 단위테스트 별도 cover.
        return f"[BINDING POLICY — {self.name}]\nguidelines test\n[/BINDING POLICY]"


@pytest.fixture(autouse=True)
def _disable_sop_for_isolation():
    """각 테스트마다 env 초기화 (다른 테스트 leak 방지)."""
    original = os.environ.get("FEATURE_SOP_RAG")
    yield
    if original is None:
        os.environ.pop("FEATURE_SOP_RAG", None)
    else:
        os.environ["FEATURE_SOP_RAG"] = original


@pytest.mark.asyncio
async def test_no_agent_context_byte_equal_legacy():
    """agent_context=None → 기존 동작 (binding/SOP 미주입). 회귀 0."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    events = []
    async for e in loop.run(
        "test", phone="010-1", tenant_id="t1", agent_context=None
    ):
        events.append(e)

    # LLM 의 system prompt 확인.
    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_msg = next(m for m in called_messages if m["role"] == "system")
    # binding/SOP marker 가 *없어야* 함.
    assert "BINDING POLICY" not in sys_msg["content"]
    assert "SOP CONTEXT" not in sys_msg["content"]


@pytest.mark.asyncio
async def test_agent_context_binding_policy_injected():
    """agent_context 있으면 binding policy 가 system 에 prepend."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    ctx = _AgentCtxStub(sop_repo_ids=[])
    async for _ in loop.run(
        "test", phone="010-1", tenant_id="t1", agent_context=ctx
    ):
        pass

    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_msgs = [m for m in called_messages if m["role"] == "system"]
    # 단일 system message (GPT-5.5 권고 3).
    assert len(sys_msgs) == 1
    assert "BINDING POLICY" in sys_msgs[0]["content"]
    assert "테스트 봇" in sys_msgs[0]["content"]
    # static base 는 보존.
    assert "tool" in sys_msgs[0]["content"].lower()


@pytest.mark.asyncio
async def test_sop_chunks_injected_when_available():
    """SOP search 가 chunks 반환하면 [SOP CONTEXT] block 이 system 에 포함."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')

    # kms_sop.search 가 chunk 반환하도록 mock.
    async def fake_kms_sop_search(args):
        return {
            "success": True,
            "chunks": [
                {
                    "text": "월-금 09:00-18:00, 슬롯 30분",
                    "score": 0.9,
                    "repo_id": str(uuid4()),
                    "document_id": str(uuid4()),
                    "chunk_index": 0,
                    "heading": "예약 가능 시간",
                }
            ],
            "total": 1,
        }

    registry = ToolRegistry({"kms_sop.search": fake_kms_sop_search})
    loop = ToolCallingLoop(llm, registry)

    ctx = _AgentCtxStub(sop_repo_ids=[uuid4()])
    async for _ in loop.run(
        "예약 가능한가",
        phone="010-1",
        tenant_id=str(ctx.tenant_id),
        agent_context=ctx,
    ):
        pass

    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_msgs = [m for m in called_messages if m["role"] == "system"]
    assert len(sys_msgs) == 1, "단일 system role message"
    sys_content = sys_msgs[0]["content"]
    assert "[SOP CONTEXT" in sys_content
    assert "월-금 09:00-18:00" in sys_content
    # binding policy 도 함께 prepend.
    assert "BINDING POLICY" in sys_content
    # precedence note 포함 (GPT-5.5 권고 3).
    assert "우선한다" in sys_content


@pytest.mark.asyncio
async def test_sop_search_exception_fail_open():
    """SOP search 가 exception 던져도 chat 진행 (fail-open)."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')

    async def broken_kms_sop_search(args):
        raise RuntimeError("KMS down")

    registry = ToolRegistry({"kms_sop.search": broken_kms_sop_search})
    loop = ToolCallingLoop(llm, registry)

    ctx = _AgentCtxStub(sop_repo_ids=[uuid4()])
    events = []
    async for e in loop.run(
        "test",
        phone="010-1",
        tenant_id=str(ctx.tenant_id),
        agent_context=ctx,
    ):
        events.append(e)

    # done 이벤트 도달 — chat 정상 종료 (fail-open 동작).
    assert events[-1]["type"] == "done"
    # SOP block 은 없어야 함 (search 실패).
    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_content = next(
        m["content"] for m in called_messages if m["role"] == "system"
    )
    assert "[SOP CONTEXT" not in sys_content
    # 그러나 binding_policy 는 살아 있음 (독립 가드).
    assert "BINDING POLICY" in sys_content


@pytest.mark.asyncio
async def test_sop_empty_result_no_block():
    """SOP search 가 chunks=[] 반환하면 [SOP CONTEXT] block 안 들어감."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')

    async def empty_kms_sop_search(args):
        return {"success": True, "chunks": [], "total": 0}

    registry = ToolRegistry({"kms_sop.search": empty_kms_sop_search})
    loop = ToolCallingLoop(llm, registry)

    ctx = _AgentCtxStub(sop_repo_ids=[uuid4()])
    async for _ in loop.run(
        "test",
        phone="010-1",
        tenant_id=str(ctx.tenant_id),
        agent_context=ctx,
    ):
        pass

    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_content = next(
        m["content"] for m in called_messages if m["role"] == "system"
    )
    assert "[SOP CONTEXT" not in sys_content


@pytest.mark.asyncio
async def test_env_kill_switch_disables_sop():
    """FEATURE_SOP_RAG=false → SOP block 미주입 (kill-switch).

    GPT-5.5 post-commit verdict §1: helper 진입부에서 flag 체크 → SOP
    search 가 chunks 반환해도 system prompt 에 [SOP CONTEXT] 안 들어감.
    binding_policy 는 ToolCallingLoop 의 *항상-on* prepend (flag 와 별개).
    """
    os.environ["FEATURE_SOP_RAG"] = "false"

    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')

    # SOP search 가 chunk 반환해도 — flag off 면 inject 안 됨.
    search_call_count = {"n": 0}

    async def fake_kms_sop_search(args):
        search_call_count["n"] += 1
        return {
            "success": True,
            "chunks": [
                {
                    "text": "should not appear in system prompt",
                    "score": 0.9,
                    "repo_id": str(uuid4()),
                    "document_id": str(uuid4()),
                    "chunk_index": 0,
                    "heading": "blocked",
                }
            ],
            "total": 1,
        }

    registry = ToolRegistry({"kms_sop.search": fake_kms_sop_search})
    loop = ToolCallingLoop(llm, registry)
    ctx = _AgentCtxStub(sop_repo_ids=[uuid4()])

    async for _ in loop.run(
        "test",
        phone="010-1",
        tenant_id=str(ctx.tenant_id),
        agent_context=ctx,
    ):
        pass

    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_content = next(
        m["content"] for m in called_messages if m["role"] == "system"
    )
    # kill-switch 동작: SOP block 안 들어감.
    assert "[SOP CONTEXT" not in sys_content
    assert "should not appear" not in sys_content
    # search 자체도 호출 안 됨 (early return).
    assert search_call_count["n"] == 0
    # binding_policy 는 살아 있음 (독립 가드).
    assert "BINDING POLICY" in sys_content


@pytest.mark.asyncio
async def test_empty_scope_skips_search():
    """sop_repo_ids/primary/fallback 모두 빈 시 search 호출 안 됨.

    GPT-5.5 post-commit verdict §5: knowledge isolation 안전.
    """
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')

    search_call_count = {"n": 0}

    async def fake_kms_sop_search(args):
        search_call_count["n"] += 1
        return {"success": True, "chunks": [], "total": 0}

    registry = ToolRegistry({"kms_sop.search": fake_kms_sop_search})
    loop = ToolCallingLoop(llm, registry)
    # 모든 scope 빈 (sop_repo_ids=[], primary=[], fallback=[]).
    ctx = _AgentCtxStub(
        sop_repo_ids=[], primary_repo_ids=[], fallback_repo_ids=[]
    )

    async for _ in loop.run(
        "test",
        phone="010-1",
        tenant_id=str(ctx.tenant_id),
        agent_context=ctx,
    ):
        pass

    # search 호출 0 — scope 비면 즉시 return.
    assert search_call_count["n"] == 0
    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_content = next(
        m["content"] for m in called_messages if m["role"] == "system"
    )
    assert "[SOP CONTEXT" not in sys_content


@pytest.mark.asyncio
async def test_prefetch_timeout_fail_open(monkeypatch):
    """prefetch 가 hang 해도 total timeout 안 fail-open.

    GPT-5.5 post-commit verdict §2: prefetch + fetch *전체* 작업에 single
    timeout 적용 — prefetch hang 도 chat 진행에 영향 0.
    """
    # timeout 짧게 (50ms) — hang 빠르게 catch.
    monkeypatch.setenv("SOP_INJECT_TIMEOUT_MS", "50")

    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"hi"}')

    import asyncio as _aio

    async def slow_kms_sop_search(args):
        # 1초 sleep — timeout 보다 훨씬 길게.
        await _aio.sleep(1.0)
        return {"success": True, "chunks": [{"text": "x", "score": 1.0,
                                              "repo_id": str(uuid4()),
                                              "document_id": str(uuid4()),
                                              "chunk_index": 0,
                                              "heading": "x"}],
                "total": 1}

    registry = ToolRegistry({"kms_sop.search": slow_kms_sop_search})
    loop = ToolCallingLoop(llm, registry)
    ctx = _AgentCtxStub(sop_repo_ids=[uuid4()])

    events = []
    async for e in loop.run(
        "test",
        phone="010-1",
        tenant_id=str(ctx.tenant_id),
        agent_context=ctx,
    ):
        events.append(e)

    # chat 정상 종료 (timeout 후 fail-open).
    assert events[-1]["type"] == "done"
    called_messages = llm.chat_completion_json.call_args.kwargs.get(
        "messages"
    ) or llm.chat_completion_json.call_args.args[0]
    sys_content = next(
        m["content"] for m in called_messages if m["role"] == "system"
    )
    # SOP block 안 들어감 (timeout fail-open).
    assert "[SOP CONTEXT" not in sys_content
