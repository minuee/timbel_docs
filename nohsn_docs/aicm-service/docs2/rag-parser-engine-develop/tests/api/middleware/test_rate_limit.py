"""Phase 13 — slowapi rate limit middleware smoke test.

전체 main app 대신 mini FastAPI 앱에 limiter 를 attach 해 동작만 검증.
- default(60/minute) 한도 미만 → 200
- chat-style 핸들러 (3/minute) 4번째 호출 → 429
- admin token 일치 → bypass (4번 모두 200)
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_limiter_state(monkeypatch):
    """각 테스트마다 limiter 의 메모리 storage 를 초기화 — counter 누수 방지."""
    monkeypatch.setenv("KMS_RATE_LIMIT_ENABLED", "true")
    # admin bypass 환경변수도 깨끗하게
    monkeypatch.delenv("KMS_ADMIN_TOKEN", raising=False)
    yield


def _build_app(default_limit: str, chat_limit: str, admin_token: str | None = None):
    """Module reload 로 ENV 반영된 fresh limiter 확보."""
    import importlib

    os.environ["KMS_RATE_LIMIT_DEFAULT"] = default_limit
    os.environ["KMS_RATE_LIMIT_CHAT"] = chat_limit
    if admin_token:
        os.environ["KMS_ADMIN_TOKEN"] = admin_token
    else:
        os.environ.pop("KMS_ADMIN_TOKEN", None)

    import src.api.middleware.rate_limit as rl

    rl = importlib.reload(rl)

    app = FastAPI()
    rl.setup_rate_limit(app)

    @app.get("/ping")
    @rl.limiter.limit(default_limit)
    async def ping(request: Request):
        return {"ok": True}

    @app.get("/chat-like")
    @rl.limiter.limit(chat_limit)
    async def chat_like(request: Request):
        return {"ok": True}

    return app, rl


def test_default_limit_allows_under_quota():
    app, _ = _build_app("10/minute", "5/minute")
    client = TestClient(app)
    for _ in range(3):
        r = client.get("/ping")
        assert r.status_code == 200, r.text


def test_chat_limit_blocks_over_quota():
    app, _ = _build_app("60/minute", "3/minute")
    client = TestClient(app)
    # 같은 IP 로 4번 호출 → 4번째 429
    statuses = [client.get("/chat-like").status_code for _ in range(4)]
    assert statuses[:3] == [200, 200, 200], statuses
    assert statuses[3] == 429, statuses


def test_admin_token_bypasses_limit():
    app, _ = _build_app("60/minute", "2/minute", admin_token="adm-secret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer adm-secret"}
    # 한도(2) 보다 많이 호출해도 모두 200
    for _ in range(5):
        r = client.get("/chat-like", headers=headers)
        assert r.status_code == 200, r.text


def test_disabled_via_env(monkeypatch):
    """KMS_RATE_LIMIT_ENABLED=false 면 setup_rate_limit no-op → limiter 미부착.

    no-op 시 app.state.limiter 가 설정되지 않아 데코레이터가 동작하려면 limiter
    attribute 가 있어야 한다.  no-op 분기에서 attach 자체를 건너뛰는지 검증.
    """
    monkeypatch.setenv("KMS_RATE_LIMIT_ENABLED", "false")
    import importlib

    import src.api.middleware.rate_limit as rl

    rl = importlib.reload(rl)
    app = FastAPI()
    rl.setup_rate_limit(app)
    assert not hasattr(app.state, "limiter") or getattr(app.state, "limiter", None) is None
