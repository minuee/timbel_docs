"""Phase 4 T4.6 — Swagger 운영 보안 정책 테스트.

env 변수 4 시나리오:
1) ENABLE_SWAGGER=false → /docs, /openapi.json 모두 404
2) SWAGGER_AUTH_MODE=basic + 미인증 → 401 + WWW-Authenticate
3) SWAGGER_AUTH_MODE=jwt + 미인증 → 401
4) SWAGGER_IP_ALLOWLIST 미부합 → 403
5) 모든 정책 통과 → 200 (sanity)

각 테스트는 monkeypatch 로 env 격리 + FastAPI 인스턴스를 매번 새로 만든다.
실제 main_kms / main 의 무거운 의존성을 끌어들이지 않기 위해 *최소 FastAPI*
를 사용 — 단, configure_swagger 의 동작은 동일하다 (env-driven, app 인자).
"""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.swagger_policy import configure_swagger


def _make_app() -> FastAPI:
    return FastAPI(
        title="swagger-policy-test",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )


# ---------------------------------------------------------------------------
# 1) ENABLE_SWAGGER=false → 404
# ---------------------------------------------------------------------------

def test_swagger_disabled_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SWAGGER", "false")
    monkeypatch.delenv("SWAGGER_AUTH_MODE", raising=False)
    monkeypatch.delenv("SWAGGER_IP_ALLOWLIST", raising=False)

    app = _make_app()
    configure_swagger(app, product="kms")
    client = TestClient(app)

    # /docs, /redoc, /openapi.json 모두 404 — FastAPI 가 route 자체를 mount 안 함.
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404

    # app attribute 도 None 으로 갱신.
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


# ---------------------------------------------------------------------------
# 2) SWAGGER_AUTH_MODE=basic + 미인증 → 401
# ---------------------------------------------------------------------------

def test_swagger_basic_missing_auth_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SWAGGER", "true")
    monkeypatch.setenv("SWAGGER_AUTH_MODE", "basic")
    monkeypatch.setenv("SWAGGER_BASIC_USER", "admin")
    monkeypatch.setenv("SWAGGER_BASIC_PASSWORD", "secret")
    monkeypatch.delenv("SWAGGER_IP_ALLOWLIST", raising=False)

    app = _make_app()
    configure_swagger(app, product="kms")
    client = TestClient(app)

    resp = client.get("/docs")
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
    assert resp.headers["WWW-Authenticate"].lower().startswith("basic")

    # 잘못된 credential 도 401.
    bad = base64.b64encode(b"admin:wrong").decode()
    resp_bad = client.get("/docs", headers={"Authorization": f"Basic {bad}"})
    assert resp_bad.status_code == 401

    # 올바른 credential 은 통과 (200 OK + Swagger UI HTML).
    good = base64.b64encode(b"admin:secret").decode()
    resp_ok = client.get("/docs", headers={"Authorization": f"Basic {good}"})
    assert resp_ok.status_code == 200


# ---------------------------------------------------------------------------
# 3) SWAGGER_AUTH_MODE=jwt + 미인증 → 401
# ---------------------------------------------------------------------------

def test_swagger_jwt_missing_bearer_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SWAGGER", "true")
    monkeypatch.setenv("SWAGGER_AUTH_MODE", "jwt")
    monkeypatch.delenv("SWAGGER_IP_ALLOWLIST", raising=False)

    app = _make_app()
    configure_swagger(app, product="kms")
    client = TestClient(app)

    resp = client.get("/docs")
    assert resp.status_code == 401

    # bearer 토큰 *존재* 만 검증 (값 검증은 보안 망 분리에 위임).
    resp_ok = client.get("/docs", headers={"Authorization": "Bearer fake.token.value"})
    assert resp_ok.status_code == 200

    # openapi.json 도 동일.
    resp_oa = client.get("/openapi.json")
    assert resp_oa.status_code == 401


# ---------------------------------------------------------------------------
# 4) SWAGGER_IP_ALLOWLIST 미부합 → 403
# ---------------------------------------------------------------------------

def test_swagger_ip_allowlist_mismatch_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SWAGGER", "true")
    monkeypatch.setenv("SWAGGER_AUTH_MODE", "none")
    # 10.x 만 허용 — TestClient 는 127.0.0.1 로 명시해 미부합.
    monkeypatch.setenv("SWAGGER_IP_ALLOWLIST", "10.0.0.0/8")

    app = _make_app()
    configure_swagger(app, product="kms")
    # TestClient default client 는 ('testclient', 50000) — IP 가 아니다.
    # 명시 IP 로 override 해 IP 검사가 정확히 동작하는지 확인.
    client = TestClient(app, client=("127.0.0.1", 50000))

    resp = client.get("/docs")
    assert resp.status_code == 403

    # 부합하는 CIDR 추가 시 통과 — 별도 app 으로 검증.
    monkeypatch.setenv("SWAGGER_IP_ALLOWLIST", "127.0.0.0/8")
    app2 = _make_app()
    configure_swagger(app2, product="kms")
    client2 = TestClient(app2, client=("127.0.0.1", 50000))
    resp_ok = client2.get("/docs")
    assert resp_ok.status_code == 200


# ---------------------------------------------------------------------------
# 5) 모든 정책 통과 — sanity
# ---------------------------------------------------------------------------

def test_swagger_default_dev_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENV=dev (또는 미설정) + 인증/allowlist 없음 → swagger 활성 + 200."""
    monkeypatch.delenv("ENABLE_SWAGGER", raising=False)
    monkeypatch.delenv("SWAGGER_AUTH_MODE", raising=False)
    monkeypatch.delenv("SWAGGER_IP_ALLOWLIST", raising=False)
    monkeypatch.setenv("ENV", "dev")

    app = _make_app()
    configure_swagger(app, product="full")
    client = TestClient(app)

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_swagger_prod_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENV=prod + ENABLE_SWAGGER 미설정 → default off."""
    monkeypatch.delenv("ENABLE_SWAGGER", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENV", "prod")

    app = _make_app()
    configure_swagger(app, product="full")
    client = TestClient(app)

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
