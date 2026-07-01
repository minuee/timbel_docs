"""Tool-calling loop (JSON 모드 클라이언트 파싱) 단위 테스트.

Task 26-B 에서 vLLM tool-call parser 의존을 버리고 Gemma 가 JSON 하나만
출력하도록 강제하는 구조로 바뀌면서 테스트 기반도 교체됨.
"""
import json
from unittest.mock import AsyncMock

import pytest

from src.agent_framework.agent.tool_calling_loop import ToolCallingLoop
from src.agent_framework.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_loop_direct_response_no_tool():
    """LLM 이 tool 없이 바로 {response: ...} 로 답하는 경우."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"안녕하세요!"}')
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    events = []
    async for e in loop.run("안녕", phone="010-1", tenant_id="010-1"):
        events.append(e)

    assert events[-1]["type"] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "안녕하세요" in text


@pytest.mark.asyncio
async def test_loop_single_tool_then_response():
    """1회 tool 호출 → 결과 주입 → 최종 자연어 응답."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(
        side_effect=[
            '{"tool":{"name":"schedule.list","arguments":{"phone":"010-1"}}}',
            '{"response":"일정 2건 있어요."}',
        ]
    )

    async def fake_list(args):
        return {"items": [{"title": "A"}, {"title": "B"}]}

    registry = ToolRegistry({"schedule.list": fake_list})
    loop = ToolCallingLoop(llm, registry)

    events = []
    async for e in loop.run("내 일정 뭐 있어", phone="010-1", tenant_id="010-1"):
        events.append(e)

    tc_req = [e for e in events if e["type"] == "tool_call_request"]
    assert len(tc_req) == 1
    assert tc_req[0]["name"] == "schedule.list"
    tc_res = [e for e in events if e["type"] == "tool_call_result"]
    assert len(tc_res) == 1
    assert tc_res[0]["result"]["items"]

    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "일정" in text


@pytest.mark.asyncio
async def test_loop_unknown_tool_error():
    """존재하지 않는 tool 이름 → error 결과를 반환하고 다음 턴 진행."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(
        side_effect=[
            '{"tool":{"name":"bogus.tool","arguments":{}}}',
            '{"response":"처리 못 했어요."}',
        ]
    )
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    events = []
    async for e in loop.run("x", phone="p", tenant_id="t"):
        events.append(e)

    tc_res = [e for e in events if e["type"] == "tool_call_result"]
    assert tc_res, "tool_call_result 이벤트 없음"
    assert "error" in tc_res[0]["result"]


@pytest.mark.asyncio
async def test_loop_bad_json_bails():
    """JSON 파싱 실패 시 형식 오류 안내 후 종료."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value="not json at all")
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    events = []
    async for e in loop.run("x", phone="p", tenant_id="t"):
        events.append(e)

    assert events[-1]["type"] == "done"
    tokens = [e.get("text", "") for e in events if e["type"] == "token"]
    assert any("형식 오류" in t for t in tokens), tokens


@pytest.mark.asyncio
async def test_loop_max_rounds():
    """LLM 이 계속 tool 만 호출하면 max_rounds 에서 차단."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(
        return_value='{"tool":{"name":"schedule.list","arguments":{"phone":"p"}}}'
    )

    async def fake(args):
        return {"items": []}

    loop = ToolCallingLoop(
        llm, ToolRegistry({"schedule.list": fake}), max_rounds=2
    )
    events = []
    async for e in loop.run("loop", phone="p", tenant_id="t"):
        events.append(e)

    tc_req = [e for e in events if e["type"] == "tool_call_request"]
    assert len(tc_req) == 2
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_loop_history_in_messages():
    """이전 turn history 가 messages 에 포함되는지 확인."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value='{"response":"네"}')
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    history = [
        {"role": "user", "content": "첫"},
        {"role": "assistant", "content": "응답1"},
    ]
    async for _ in loop.run("두번째", phone="p", tenant_id="t", history=history):
        pass

    call_kwargs = llm.chat_completion_json.await_args.kwargs
    msgs = call_kwargs["messages"]
    assert msgs[0]["role"] == "system"
    contents = [m["content"] for m in msgs]
    assert "첫" in contents
    assert "두번째" in contents


@pytest.mark.asyncio
async def test_loop_markdown_fenced_json_parses():
    """Gemma 가 ```json ... ``` 으로 감싸도 extract_json 이 벗겨내서 파싱."""
    llm = AsyncMock()
    fenced = '```json\n{"response":"네 도와드릴게요."}\n```'
    llm.chat_completion_json = AsyncMock(return_value=fenced)
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    events = []
    async for e in loop.run("안녕", phone="p", tenant_id="t"):
        events.append(e)

    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "도와드릴게요" in text


# ---------------------------------------------------------------------------
# Wave D (KMS-Plus, 2026-04-25) — fallback_composer wire-up.
# LLM/tool 외부 호출 실패 시 자연 안내 텍스트가 사용자에게 노출되는지 검증.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_llm_failure_uses_fallback_composer():
    """LLM JSON call 실패 시 단순 'X' 가 아니라 fallback_composer 자연 안내 발화."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(
        side_effect=TimeoutError("upstream slow")
    )
    loop = ToolCallingLoop(llm, ToolRegistry({}))

    events = []
    async for e in loop.run("x", phone="p", tenant_id="t"):
        events.append(e)

    tokens = [e.get("text", "") for e in events if e["type"] == "token"]
    text = "".join(tokens)
    # FallbackComposer 의 timeout 템플릿에서 등장하는 핵심 어구.
    assert "응답 생성" in text or "응답이 늦어" in text or "다시 시도" in text, text
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_loop_tool_failure_attaches_user_message():
    """tool 호출이 raise 하면 result 에 user_message (fallback) 가 동봉된다.

    LLM 의 다음 턴 결정에 의도적 user-friendly 메시지가 컨텍스트로 들어감.
    """
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(
        side_effect=[
            '{"tool":{"name":"schedule.list","arguments":{"phone":"p"}}}',
            '{"response":"실패 안내 후 마무리"}',
        ]
    )

    async def boom(_args):
        raise ConnectionError("503 service")

    loop = ToolCallingLoop(llm, ToolRegistry({"schedule.list": boom}))

    events = []
    async for e in loop.run("내 일정", phone="p", tenant_id="t"):
        events.append(e)

    tc_res = [e for e in events if e["type"] == "tool_call_result"]
    assert tc_res
    result = tc_res[0]["result"]
    assert "error" in result
    assert "user_message" in result, result
    assert result.get("error_kind") in {"service_down", "unknown"}
    # 사용자에 친화 텍스트가 포함되어 있어야 함.
    assert "schedule list" in result["user_message"] or "schedule" in result["user_message"]
