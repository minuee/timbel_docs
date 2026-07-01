"""Phase 13 — SecurityHeadersMiddleware smoke test.

Mini FastAPI 앱에 미들웨어를 attach 해 응답 헤더를 검증.
- 기본 5개 헤더 부착
- HSTS 는 HTTPS 또는 X-Forwarded-Proto: https 에서만
- HTTP 응답에는 HSTS 없음
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.security_headers import SecurityHeadersMiddleware


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app)


def test_security_headers_present(client):
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = r.headers.get("Content-Security-Policy") or ""
    assert "default-src 'self'" in csp
    assert "img-src 'self' data: https:" in csp


def test_hsts_only_on_https_via_forwarded_proto(client):
    """plain HTTP 요청 → HSTS 없음 / X-Forwarded-Proto: https → HSTS 있음."""
    r_http = client.get("/ping")
    assert "Strict-Transport-Security" not in r_http.headers

    r_https = client.get("/ping", headers={"X-Forwarded-Proto": "https"})
    hsts = r_https.headers.get("Strict-Transport-Security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts


def test_csp_connect_src_overridable(monkeypatch):
    """KMS_CSP_CONNECT_SRC env 로 connect-src 변경 가능."""
    monkeypatch.setenv("KMS_CSP_CONNECT_SRC", "'self' https://api.example.com")
    import importlib

    import src.api.middleware.security_headers as sh

    sh = importlib.reload(sh)

    app = FastAPI()
    app.add_middleware(sh.SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "https://api.example.com" in csp
