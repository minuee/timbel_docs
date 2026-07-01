"""D34 §4 — 라우트 응답 헤더 검증 unit test.

목적: middleware 가 모든 router 응답에 X-RLS-Scope / X-RLS-Tenant-Id /
X-RLS-Agent-Id 헤더를 *non-prod 환경* 에서 자동 주입하는지 검증.

검증:
1. 200 응답 — JWT 인증 + admin scope → X-RLS-Scope='admin'.
2. 401 응답 (인증 실패) — middleware 는 status code 무관 헤더 emit → X-RLS-Scope=''.
3. 422 응답 (validation 실패) — 동일.
4. websocket 은 본 §4 에서 제외 (헤더 메커니즘 부재).
5. APP_ENV=production 환경에서는 헤더 비노출 (정보 누출 방지).

GPT-5 phase 0 §4 GO + 권고 — APP_ENV 강제 set, 401/403 도 헤더 emit, SSE/Stream 도
http.response.start 시점에 헤더 주입.

본 test 는 *경량* — full FastAPI app 빌드 대신 middleware 만 직접 테스트
(다른 router import 의 무거운 의존성 회피).
"""
from __future__ import annotations

from typing import Any

import pytest

from src.api.middleware.rls_context import (
    RLSContext,
    get_rls_context,
)
from src.api.middleware.rls_context_middleware import RLSContextMiddleware


def _build_asgi_scope(
    *,
    method: str = "GET",
    path: str = "/api/v1/test",
    headers: list[tuple[bytes, bytes]] | None = None,
    typ: str = "http",
) -> dict:
    """ASGI scope dict 빌드 (test fixture)."""
    return {
        "type": typ,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "server": ("test", 8000),
        "client": ("127.0.0.1", 12345),
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
    }


class _FakeApp:
    """가짜 ASGI app — 200 응답을 emit. 응답 헤더 주입 검증용."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.received_headers: list[tuple[bytes, bytes]] | None = None

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        # http.response.start 직전 RLSContext 검사 가능.
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})


def _capture_send():
    """send() 호출 capture — start message 의 headers 추출.

    D37 §3 보강 — body message dict 자체도 ``bodies`` 키로 저장 (headers 키
    부재 검증 등 엄격 단언용).
    """
    captured: dict = {"start": None, "body": [], "bodies": []}

    async def send(message: dict) -> None:
        if message.get("type") == "http.response.start":
            captured["start"] = message
        elif message.get("type") == "http.response.body":
            captured["body"].append(message.get("body", b""))
            captured["bodies"].append(message)

    return captured, send


def _get_header(captured: dict, name: bytes) -> bytes | None:
    start = captured.get("start") or {}
    for k, v in start.get("headers", []):
        if k.lower() == name.lower():
            return v
    return None


@pytest.mark.asyncio
async def test_unauth_request_emits_empty_scope_header(monkeypatch) -> None:
    """JWT 부재 + non-prod → X-RLS-Scope='' (default-deny) 헤더 emit."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    app = _FakeApp(status=200)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    val = _get_header(captured, b"x-rls-scope")
    assert val == b"", f"unauth → empty scope expected, got {val!r}"


@pytest.mark.asyncio
async def test_404_response_still_emits_header(monkeypatch) -> None:
    """404 응답에도 X-RLS-Scope 헤더 emit (status code 무관)."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    app = _FakeApp(status=404)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    assert captured["start"]["status"] == 404
    val = _get_header(captured, b"x-rls-scope")
    assert val == b""


@pytest.mark.asyncio
async def test_401_response_still_emits_header(monkeypatch) -> None:
    """401 응답에도 헤더 emit (GPT-5 §4 권고 — 인증 실패 path도 검증)."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    app = _FakeApp(status=401)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    assert captured["start"]["status"] == 401
    val = _get_header(captured, b"x-rls-scope")
    assert val == b""


# D37 §2 — 404/405/500/422 등 다양한 status code 에 대한 헤더 주입 정합 보강.
# fake app status emit 으로 ASGI 스펙 (http.response.start 시점 헤더 주입) 검증.


@pytest.mark.asyncio
async def test_405_method_not_allowed_emits_header(monkeypatch) -> None:
    """status=405 응답에도 X-RLS-Scope 헤더 emit (404 와 동일 ASGI 패턴)."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    app = _FakeApp(status=405)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope(method="POST")
    await middleware(scope, lambda: None, send)

    assert captured["start"]["status"] == 405
    val = _get_header(captured, b"x-rls-scope")
    assert val == b""


@pytest.mark.asyncio
async def test_500_response_still_emits_header(monkeypatch) -> None:
    """5xx 에러 응답에도 X-RLS-Scope 헤더 emit — middleware status 무관.

    Note: 본 test 는 *명시* status=500 emit (정상 ASGI 종료 path).
    unhandled exception 으로 start 이전에 앱이 crash 하는 path 는 본 경량 패턴
    범위 밖 (별도 Starlette 통합 test 필요 — 본 D37 범위 외).
    """
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    app = _FakeApp(status=500)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    assert captured["start"]["status"] == 500
    val = _get_header(captured, b"x-rls-scope")
    assert val == b""


@pytest.mark.asyncio
async def test_422_validation_error_emits_header(monkeypatch) -> None:
    """status=422 응답에도 X-RLS-Scope 헤더 emit (Pydantic validation 실패 case).

    D34 spec 의 \"401/403/422 모두 헤더 노출\" 명시 — D37 §2 에서 보강.
    """
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    app = _FakeApp(status=422)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    assert captured["start"]["status"] == 422
    val = _get_header(captured, b"x-rls-scope")
    assert val == b""


@pytest.mark.asyncio
async def test_production_env_no_header_leak(monkeypatch) -> None:
    """APP_ENV=production 에서 X-RLS-* 헤더 비노출 (정보 누출 방지)."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "production", raising=False
    )

    app = _FakeApp(status=200)
    middleware = RLSContextMiddleware(app)

    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    val_scope = _get_header(captured, b"x-rls-scope")
    val_tenant = _get_header(captured, b"x-rls-tenant-id")
    val_agent = _get_header(captured, b"x-rls-agent-id")
    assert val_scope is None, f"prod should NOT leak X-RLS-Scope, got {val_scope!r}"
    assert val_tenant is None
    assert val_agent is None


@pytest.mark.asyncio
async def test_dispatcher_scope_change_reflected_in_header(monkeypatch) -> None:
    """dispatcher 가 agent scope 로 wrap 한 경우 응답 헤더에 agent scope 반영."""
    from src.api.middleware.rls_context import bind_agent_scope
    from uuid import uuid4

    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    aid = str(uuid4())
    tid = str(uuid4())

    class _DispatcherApp:
        """app 실행 중 bind_agent_scope 로 RLSContext 를 agent 로 전환."""

        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            async with bind_agent_scope(aid, tid):
                # response.start 시점에 contextvar 가 agent scope 임을 검증.
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"ok"})

    middleware = RLSContextMiddleware(_DispatcherApp())
    captured, send = _capture_send()
    scope = _build_asgi_scope()
    await middleware(scope, lambda: None, send)

    val_scope = _get_header(captured, b"x-rls-scope")
    val_agent = _get_header(captured, b"x-rls-agent-id")
    assert val_scope == b"agent", f"agent scope expected, got {val_scope!r}"
    assert val_agent == aid.encode()


@pytest.mark.asyncio
async def test_websocket_scope_no_response_headers(monkeypatch) -> None:
    """websocket 은 응답 헤더 주입 X (라이프사이클 다름)."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    received_in_ctx = {"scope": None}

    class _WsApp:
        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            # ws path 에서 RLSContext 자체는 등록되어 있어야 함.
            ctx = get_rls_context()
            received_in_ctx["scope"] = ctx
            # ws 는 응답 X — 그냥 종료.

    middleware = RLSContextMiddleware(_WsApp())
    scope = _build_asgi_scope(typ="websocket", path="/ws/test")
    await middleware(scope, lambda: None, lambda m: None)

    # WS path 에도 RLSContext 자체는 등록 (default-deny scope='').
    assert received_in_ctx["scope"] is not None
    assert isinstance(received_in_ctx["scope"], RLSContext)
    assert received_in_ctx["scope"].scope == ""


@pytest.mark.asyncio
async def test_lifespan_event_skipped(monkeypatch) -> None:
    """lifespan event 는 RLSContext 적용 X (DB 접근 없음 가정)."""
    called = {"n": 0}

    class _LifespanApp:
        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            called["n"] += 1

    middleware = RLSContextMiddleware(_LifespanApp())
    scope = {"type": "lifespan"}
    await middleware(scope, lambda: None, lambda m: None)

    assert called["n"] == 1


# D37 §3 — SSE / StreamingResponse 응답 헤더 검증.
# rag_assist `/api/v1/rag/assist-stream`, chat_v1 SSE, agents_v1 test-chat SSE,
# external_agent_v1 SSE 모두 StreamingResponse — 첫 send 가 http.response.start.
# middleware 가 status code/stream 무관 헤더 inject 정합 검증.


class _StreamingApp:
    """가짜 ASGI streaming app — http.response.start (text/event-stream) +
    다중 http.response.body chunk emit.

    SSE / StreamingResponse 시뮬레이션:
    - 첫 send 가 http.response.start (status, content-type=text/event-stream).
    - 후속 send 가 다중 http.response.body (chunk + more_body).
    - 마지막 chunk 는 more_body=False.
    """

    def __init__(self, *, status: int = 200, n_chunks: int = 3) -> None:
        self.status = status
        self.n_chunks = n_chunks

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                    (b"cache-control", b"no-cache, no-transform"),
                ],
            }
        )
        for i in range(self.n_chunks):
            await send(
                {
                    "type": "http.response.body",
                    "body": f"data: chunk-{i}\n\n".encode("utf-8"),
                    "more_body": i < self.n_chunks - 1,
                }
            )


@pytest.mark.asyncio
async def test_sse_streaming_response_emits_scope_header(monkeypatch) -> None:
    """SSE/StreamingResponse 의 첫 http.response.start 에 X-RLS-Scope 헤더 주입."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    middleware = RLSContextMiddleware(_StreamingApp(status=200, n_chunks=3))

    captured, send = _capture_send()
    scope = _build_asgi_scope(path="/api/v1/rag/assist-stream")
    await middleware(scope, lambda: None, send)

    val_scope = _get_header(captured, b"x-rls-scope")
    assert val_scope == b"", (
        f"unauth SSE 도 default-deny scope 헤더 emit, got {val_scope!r}"
    )
    # body chunks 정상 전달.
    assert len(captured["body"]) == 3
    # 기존 content-type 헤더 보존 — middleware 가 추가만, 기존은 그대로.
    val_ct = _get_header(captured, b"content-type")
    assert val_ct == b"text/event-stream"
    # tenant/agent 는 없음 (unauth).
    assert _get_header(captured, b"x-rls-tenant-id") is None
    assert _get_header(captured, b"x-rls-agent-id") is None


@pytest.mark.asyncio
async def test_sse_dispatcher_scope_change_reflected(monkeypatch) -> None:
    """dispatcher 가 bind_agent_scope 로 streaming app 을 wrap 한 case —
    응답 시작 시점에 agent scope 헤더 반영 (D34 dispatcher pattern)."""
    from uuid import uuid4

    from src.api.middleware.rls_context import bind_agent_scope

    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    aid = str(uuid4())
    tid = str(uuid4())

    class _DispatcherStreamingApp:
        async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
            async with bind_agent_scope(aid, tid):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/event-stream")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"data: x\n\n",
                        "more_body": False,
                    }
                )

    middleware = RLSContextMiddleware(_DispatcherStreamingApp())
    captured, send = _capture_send()
    scope = _build_asgi_scope(path="/api/v1/chat/stream")
    await middleware(scope, lambda: None, send)

    val_scope = _get_header(captured, b"x-rls-scope")
    val_agent = _get_header(captured, b"x-rls-agent-id")
    val_tenant = _get_header(captured, b"x-rls-tenant-id")
    assert val_scope == b"agent", (
        f"agent scope expected in SSE start, got {val_scope!r}"
    )
    assert val_agent == aid.encode()
    assert val_tenant == tid.encode()


@pytest.mark.asyncio
async def test_sse_long_stream_no_double_header(monkeypatch) -> None:
    """다중 body chunk 에 X-RLS-Scope 헤더가 중복 inject 되지 않음 보장.

    middleware 의 _send_with_headers 가 http.response.start 만 가공 — body chunks
    는 unchanged 통과. body 메시지 dict 에 headers 키 자체 부재 검증
    (GPT-5 §3 §4 권고 — _capture_send bodies 보강).
    """
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "development", raising=False
    )

    middleware = RLSContextMiddleware(_StreamingApp(status=200, n_chunks=10))
    captured, send = _capture_send()
    scope = _build_asgi_scope(path="/api/v1/rag/assist-stream")
    await middleware(scope, lambda: None, send)

    # 첫 start 헤더는 X-RLS-Scope 정확히 1회만.
    start_headers = (captured["start"] or {}).get("headers", [])
    scope_count = sum(1 for k, _ in start_headers if k.lower() == b"x-rls-scope")
    assert scope_count == 1, (
        f"X-RLS-Scope 헤더가 정확히 1회 inject 기대, got {scope_count}"
    )
    # body chunks 의 message dict 에 headers 키 자체 부재 (ASGI body spec).
    assert all("headers" not in m for m in captured["bodies"]), (
        "body message 에 headers 키 inject 됨 — middleware 가 body 까지 가공 (회귀)"
    )
    assert len(captured["body"]) == 10  # 10 chunks 정상 전달.


@pytest.mark.asyncio
async def test_sse_production_env_no_header_leak(monkeypatch) -> None:
    """APP_ENV=production 에서 SSE 응답도 X-RLS-* 헤더 비노출 (정보 누출 차단)."""
    monkeypatch.setattr(
        "src.common.config.settings.APP_ENV", "production", raising=False
    )

    middleware = RLSContextMiddleware(_StreamingApp(status=200, n_chunks=2))
    captured, send = _capture_send()
    scope = _build_asgi_scope(path="/api/v1/rag/assist-stream")
    await middleware(scope, lambda: None, send)

    val_scope = _get_header(captured, b"x-rls-scope")
    val_tenant = _get_header(captured, b"x-rls-tenant-id")
    val_agent = _get_header(captured, b"x-rls-agent-id")
    assert val_scope is None, (
        f"prod SSE should NOT leak X-RLS-Scope, got {val_scope!r}"
    )
    assert val_tenant is None
    assert val_agent is None
    assert len(captured["body"]) == 2  # body 는 정상 흐름.
