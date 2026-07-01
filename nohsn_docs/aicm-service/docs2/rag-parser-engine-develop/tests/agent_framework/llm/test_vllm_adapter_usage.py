"""Task 3 (M7) — VLLMAdapter.complete_with_usage() cached_tokens 노출 검증."""
from unittest.mock import AsyncMock, patch

import pytest

from src.agent_framework.llm.vllm_adapter import VLLMAdapter


# ---------------------------------------------------------------------------
# str-user 경로 (llm_router → QwenLLMClient → LLMResponse.usage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_tokens_extracted_str_user():
    """str user 경로: llm_router 가 반환한 LLMResponse.usage 의 cached_tokens 노출."""
    fake_resp = type(
        "LLMResponse",
        (),
        {
            "text": "{}",
            "usage": {
                "input_tokens": 8000,
                "output_tokens": 50,
                "cached_tokens": 6500,
            },
        },
    )()
    adapter = VLLMAdapter()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        text, usage = await adapter.complete_with_usage("system", "user")
    assert text == "{}"
    assert usage["cached_tokens"] == 6500


@pytest.mark.asyncio
async def test_cached_tokens_absent_str_user():
    """구버전 vLLM 처럼 cached_tokens 키 없으면 None 명시."""
    fake_resp = type(
        "LLMResponse",
        (),
        {
            "text": "ok",
            "usage": {"input_tokens": 100, "output_tokens": 10},
        },
    )()
    adapter = VLLMAdapter()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        _, usage = await adapter.complete_with_usage("s", "u")
    assert usage.get("cached_tokens") is None  # 부재 시 None 명시


# ---------------------------------------------------------------------------
# list-user 경로 (vLLM httpx 직접 호출)
# ---------------------------------------------------------------------------


class _FakeResp:
    status_code = 200

    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


class _FakeClient:
    def __init__(self, data: dict) -> None:
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, json=None):
        return _FakeResp(self._data)


@pytest.mark.asyncio
async def test_cached_tokens_extracted_list_user():
    """list user 경로: vLLM 응답의 usage.prompt_tokens_details.cached_tokens 노출."""
    fake_data = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {
            "prompt_tokens": 8000,
            "completion_tokens": 50,
            "total_tokens": 8050,
            "prompt_tokens_details": {"cached_tokens": 6500},
        },
    }
    adapter = VLLMAdapter()
    with patch(
        "src.agent_framework.llm.vllm_adapter.httpx.AsyncClient",
        lambda **kw: _FakeClient(fake_data),
    ):
        text, usage = await adapter.complete_with_usage(
            "system", [{"type": "text", "text": "hi"}]
        )
    assert text == "hello"
    assert usage["cached_tokens"] == 6500


@pytest.mark.asyncio
async def test_cached_tokens_absent_list_user():
    """list user 경로: prompt_tokens_details 없으면 cached_tokens = None."""
    fake_data = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    }
    adapter = VLLMAdapter()
    with patch(
        "src.agent_framework.llm.vllm_adapter.httpx.AsyncClient",
        lambda **kw: _FakeClient(fake_data),
    ):
        _, usage = await adapter.complete_with_usage("s", [{"type": "text", "text": "q"}])
    assert usage["cached_tokens"] is None


# ---------------------------------------------------------------------------
# complete() 기존 동작 불변 검증 — 추가로 확인
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_still_returns_str():
    """complete() 는 여전히 str 반환 — complete_with_usage 추가로 영향 없음."""
    fake_resp = type("R", (), {"text": "unchanged", "usage": {}})()
    adapter = VLLMAdapter()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        result = await adapter.complete("sys", "hello")
    assert isinstance(result, str)
    assert result == "unchanged"


@pytest.mark.asyncio
async def test_complete_list_user_still_returns_str():
    """refactor 후에도 complete() 의 list-user (multimodal) path 가 str 반환."""
    fake_data = {
        "choices": [{"message": {"content": "응답"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    }
    adapter = VLLMAdapter()
    with patch(
        "src.agent_framework.llm.vllm_adapter.httpx.AsyncClient",
        lambda **kw: _FakeClient(fake_data),
    ):
        result = await adapter.complete("system", [{"type": "text", "text": "user"}])
    assert isinstance(result, str)
    assert result == "응답"
