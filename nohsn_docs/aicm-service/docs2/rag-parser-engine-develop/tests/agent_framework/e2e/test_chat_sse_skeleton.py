"""Task 7 에서 도입된 SSE 스켈레톤 테스트.

Task 14 부터는 /agent/chat 이 실제 AgentEngine 에 연결된다. 본 테스트는
외부 의존성 (Redis/vLLM) 을 타지 않고 SSE 헤더 + 첫 이벤트만 검증하는
범위이므로, DI 싱글턴을 스텁 엔진으로 바꿔치기한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from src.agent_framework.api.dependencies import get_agent_engine
from src.api.main import app


class _StubEngine:
    async def turn(
        self, session_id: str, tenant_id: str, user_message: str, **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "ack", "data": {"session_id": session_id}}
        yield {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_agent_chat_returns_sse_headers():
    app.dependency_overrides[get_agent_engine] = lambda: _StubEngine()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            async with c.stream(
                "POST",
                "/agent/chat",
                json={"session_id": "s1", "tenant_id": "t1", "message": "hello"},
            ) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                first_chunk = await anext(resp.aiter_raw())
                assert b"event:" in first_chunk
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)
