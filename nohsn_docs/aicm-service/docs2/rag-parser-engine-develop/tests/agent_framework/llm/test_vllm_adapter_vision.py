"""Task 24.5 — VLLMAdapter 멀티모달 user content 처리."""
from unittest.mock import AsyncMock, patch

import pytest

from src.agent_framework.llm.vllm_adapter import VLLMAdapter


@pytest.mark.asyncio
async def test_complete_string_user_uses_router():
    """일반 텍스트는 기존 llm_router 경로 유지."""
    adapter = VLLMAdapter()
    fake_resp = type("R", (), {"text": "안녕"})()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        out = await adapter.complete("sys", "hi")
    assert out == "안녕"
    mr.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_list_user_bypasses_router_uses_vllm_direct():
    """멀티모달 content list 는 llm_router 우회 → vLLM OpenAI API 직접."""
    adapter = VLLMAdapter()
    user_content = [
        {"type": "text", "text": "이 사진 뭐?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA="}},
    ]
    fake_json = {"choices": [{"message": {"content": "고양이 사진입니다"}}]}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return fake_json

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None):
            return _Resp()

    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr, patch(
        "src.agent_framework.llm.vllm_adapter.httpx.AsyncClient", _Client
    ):
        mr.route = AsyncMock()
        out = await adapter.complete("sys", user_content)

    assert "고양이" in out
    mr.route.assert_not_awaited()  # list 라서 router 호출 안 됨


@pytest.mark.asyncio
async def test_complete_str_user_with_model_override_bypasses_router():
    """D28 §3 — str user + model override → llm_router 우회 → vLLM 직접 호출.

    `_use_router_path = isinstance(user, str) and model is None` 분기의
    str+override 경로 회귀 가드. router 의 LLMRequest 가 model 필드를 안 가지므로
    override 시는 항상 direct path.
    """
    adapter = VLLMAdapter()
    fake_json = {"choices": [{"message": {"content": "안녕 (12B)"}}]}
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return fake_json

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None):
            captured["payload"] = json
            return _Resp()

    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr, patch(
        "src.agent_framework.llm.vllm_adapter.httpx.AsyncClient", _Client
    ):
        mr.route = AsyncMock()
        out = await adapter.complete("sys", "hi", model="gemma-4-12b")

    assert "안녕" in out
    mr.route.assert_not_awaited()  # str + model override → router 우회
    assert captured["payload"]["model"] == "gemma-4-12b"


@pytest.mark.asyncio
async def test_stream_list_user_yields_tokens():
    """stream 도 list 지원 — SSE 파싱 토큰 생성."""
    adapter = VLLMAdapter()
    user_content = [{"type": "text", "text": "hi"}]

    class _StreamResp:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"안"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"녕"}}]}'
            yield "data: [DONE]"

    class _StreamCtx:
        async def __aenter__(self):
            return _StreamResp()

        async def __aexit__(self, *a):
            return None

    class _StreamClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def stream(self, *a, **kw):
            return _StreamCtx()

    with patch(
        "src.agent_framework.llm.vllm_adapter.httpx.AsyncClient", _StreamClient
    ):
        tokens = []
        async for t in adapter.stream("sys", user_content):
            tokens.append(t)
    assert "".join(tokens) == "안녕"
