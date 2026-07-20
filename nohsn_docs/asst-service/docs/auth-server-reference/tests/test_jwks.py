"""JWKS 로 각 앱 백엔드가 자체 검증할 수 있는지 확인한다 (= SSO 성립 조건).

여기 테스트가 하는 일이 곧 어드바이저·AICM·TA·QA 백엔드가 할 일이다.
"""

import jwt
import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_jwks_엔드포인트는_공개키를_노출한다(client, settings):
    response = await client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    assert "max-age" in response.headers["cache-control"]

    keys = response.json()["keys"]
    assert len(keys) == 1
    key = keys[0]
    assert key["kid"] == settings.jwt_kid
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["use"] == "sig"
    assert "d" not in key, "개인키 성분이 새어나가면 안 된다"


async def test_앱_백엔드는_JWKS_공개키만으로_access_를_검증할_수_있다(client, settings):
    tokens = await login(client)
    jwks = (await client.get("/.well-known/jwks.json")).json()

    # 앱 백엔드가 하는 그대로: 토큰 헤더의 kid 로 공개키를 고른다
    kid = jwt.get_unverified_header(tokens["accessToken"])["kid"]
    jwk = next(k for k in jwks["keys"] if k["kid"] == kid)
    public_key = jwt.PyJWK.from_dict(jwk).key

    payload = jwt.decode(
        tokens["accessToken"],
        public_key,
        algorithms=["RS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )

    assert payload["typ"] == "access"
    assert payload["acc"] == "agent01"
    assert payload["role"] == "agent"
    # 클레임 최소화 — 소속/개인정보는 토큰에 없다
    assert "password" not in payload and "defaultPassword" not in payload


async def test_refresh_토큰에는_신원_클레임이_없다(client):
    tokens = await login(client)
    payload = jwt.decode(tokens["refreshToken"], options={"verify_signature": False})
    assert payload["typ"] == "refresh"
    assert "role" not in payload and "acc" not in payload
