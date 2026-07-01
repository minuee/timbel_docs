"""webhook_caller — call_custom_tool() 단위 테스트.

httpx + DB 세션을 mock 처리. AGENT_CHANNEL_KEY 를 테스트용으로 설정해
Fernet 암호화/복호화도 실제로 검증.

참고: tests/agent_framework/tools/conftest.py 의 autouse fixture 가 Redis 를
      필요로 하므로 _flush_all_mocks 를 여기서 patch 해 Redis 연결 없이 실행.
"""
from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

# AGENT_CHANNEL_KEY 를 테스트용으로 설정 — Fernet.generate_key() 호환 base64 32-byte.
# 모듈 임포트 전에 설정해야 싱글턴 초기화가 올바르게 됨.
_TEST_KEY = "XkVERMzJbEZ0Mhk0yJ_aSZyLFaLqn8WS7UXJJAZ-kms="
os.environ.setdefault("AGENT_CHANNEL_KEY", _TEST_KEY)

# conftest autouse 의 Redis flush 를 no-op 으로 대체 — 이 모듈은 Redis 미사용.
@pytest.fixture(autouse=True)
def _no_redis_flush(monkeypatch):
    """_flush_all_mocks 를 no-op async 로 교체해 Redis 연결 불필요하게 만듦."""
    async def _noop():
        return None
    monkeypatch.setattr(
        "src.agent_framework.tools._redis_store._flush_all_mocks",
        _noop,
    )

from src.common.crypto.fernet import encrypt_dict, reset_for_tests  # noqa: E402
from src.agent_framework.tools.webhook_caller import (  # noqa: E402
    CustomToolCallError,
    CustomToolNotFound,
    call_custom_tool,
    register_custom_tools_for_tenant,
)


TENANT_ID = uuid.uuid4()
TOOL_NAME = "custom.weather_test"
TOOL_ID = uuid.uuid4()


def _make_tool(
    name: str = TOOL_NAME,
    method: str = "POST",
    auth_headers: dict | None = None,
    is_active: bool = True,
):
    """FakeCustomTool — ORM 모델 없이 attribute 흉내."""
    tool = MagicMock()
    tool.name = name
    tool.method = method
    tool.endpoint_url = "https://api.example.com/weather"
    tool.is_active = is_active
    tool.config_encrypted = encrypt_dict({"auth_headers": auth_headers or {}})
    return tool


def _make_db(tool_or_none) -> AsyncMock:
    """scalars.scalar_one_or_none 을 흉내내는 AsyncSession mock."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = tool_or_none
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# call_custom_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_not_found_raises():
    """DB 조회 결과 None → CustomToolNotFound."""
    db = _make_db(None)
    with pytest.raises(CustomToolNotFound, match="not found"):
        await call_custom_tool(db, TENANT_ID, "custom.missing", {})


@pytest.mark.asyncio
async def test_post_success(respx_mock=None):
    """POST 성공 — ok=True, data 반환."""
    tool = _make_tool(auth_headers={"Authorization": "Bearer secret"})
    db = _make_db(tool)

    fake_response = httpx.Response(
        200,
        json={"temperature": 22, "unit": "celsius"},
    )

    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake_response)):
        result = await call_custom_tool(
            db, TENANT_ID, TOOL_NAME, {"city": "Seoul"}
        )

    assert result["ok"] is True
    assert result["tool"] == TOOL_NAME
    assert result["status_code"] == 200
    assert result["data"]["temperature"] == 22


@pytest.mark.asyncio
async def test_get_method_uses_params():
    """GET method → params 로 전달."""
    tool = _make_tool(method="GET")
    db = _make_db(tool)

    fake_response = httpx.Response(200, json={"ok": True})

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)) as mock_get:
        result = await call_custom_tool(
            db, TENANT_ID, TOOL_NAME, {"q": "rain"}, timeout_s=10.0
        )

    assert result["ok"] is True
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args
    assert call_kwargs.kwargs["params"] == {"q": "rain"}


@pytest.mark.asyncio
async def test_4xx_raises_call_error():
    """4xx → CustomToolCallError."""
    tool = _make_tool()
    db = _make_db(tool)

    fake_response = httpx.Response(403, text="Forbidden")

    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake_response)):
        with pytest.raises(CustomToolCallError, match="403"):
            await call_custom_tool(db, TENANT_ID, TOOL_NAME, {})


@pytest.mark.asyncio
async def test_timeout_raises_call_error():
    """httpx TimeoutException → CustomToolCallError."""
    tool = _make_tool()
    db = _make_db(tool)

    with patch(
        "httpx.AsyncClient.request",
        new=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
    ):
        with pytest.raises(CustomToolCallError, match="timeout"):
            await call_custom_tool(db, TENANT_ID, TOOL_NAME, {}, timeout_s=1.0)


@pytest.mark.asyncio
async def test_non_json_response_returns_raw_text():
    """응답이 JSON 이 아니면 raw_text 로 래핑."""
    tool = _make_tool()
    db = _make_db(tool)

    fake_response = httpx.Response(200, text="plain text response")

    with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=fake_response)):
        result = await call_custom_tool(db, TENANT_ID, TOOL_NAME, {})

    assert result["ok"] is True
    assert result["data"] == {"raw_text": "plain text response"}


@pytest.mark.asyncio
async def test_auth_headers_injected():
    """config_encrypted 에 저장된 auth_headers 가 실제 요청 헤더로 주입."""
    tool = _make_tool(auth_headers={"X-Api-Key": "mykey123"})
    db = _make_db(tool)

    fake_response = httpx.Response(200, json={"ok": True})
    captured_headers: dict = {}

    async def _fake_request(self, method, url, *, json=None, headers=None, **kw):
        captured_headers.update(headers or {})
        return fake_response

    with patch("httpx.AsyncClient.request", new=_fake_request):
        await call_custom_tool(db, TENANT_ID, TOOL_NAME, {})

    assert captured_headers.get("X-Api-Key") == "mykey123"


# ---------------------------------------------------------------------------
# register_custom_tools_for_tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_custom_tools_registers_all_active():
    """활성 custom tool 전부 ToolRegistry 에 등록."""
    from src.agent_framework.tools.registry import ToolRegistry

    tool_a = _make_tool(name="custom.tool_a")
    tool_b = _make_tool(name="custom.tool_b")

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [tool_a, tool_b]
    db.execute = AsyncMock(return_value=result_mock)

    registry = ToolRegistry()
    count = await register_custom_tools_for_tenant(db, TENANT_ID, registry)

    assert count == 2
    assert "custom.tool_a" in registry.list_names()
    assert "custom.tool_b" in registry.list_names()
