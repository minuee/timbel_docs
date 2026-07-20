"""PPT 요청사항 1·2·3·4번이 실제로 동작하는지 검증한다."""

import asyncio

import jwt
import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_login_은_토큰과_httponly_쿠키를_함께_준다(client, settings):
    response = await client.post("/auth/login", json={"account": "agent01", "password": "password"})
    assert response.status_code == 200

    body = response.json()
    assert body["accessToken"] and body["refreshToken"]
    assert body["expiresIn"] <= settings.access_ttl_seconds

    cookies = response.headers.get_list("set-cookie")
    access_cookie = next(c for c in cookies if c.startswith(settings.cookie_access_name))
    assert "HttpOnly" in access_cookie
    # 세션 쿠키 정책(cookie_persistent=false)이면 만료가 붙지 않아야 한다
    assert "Max-Age" not in access_cookie
    # CSRF 토큰만 JS 가 읽어야 하므로 httpOnly 가 아니다
    csrf_cookie = next(c for c in cookies if c.startswith(settings.cookie_csrf_name))
    assert "HttpOnly" not in csrf_cookie


async def test_잘못된_비밀번호는_401(client):
    response = await client.post("/auth/login", json={"account": "agent01", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_credentials"


async def test_refresh_는_회전한다_새_토큰_발급_구토큰_폐기(client):
    tokens = await login(client)

    response = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 200
    rotated = response.json()

    assert rotated["refreshToken"] != tokens["refreshToken"]
    assert rotated["accessToken"] != tokens["accessToken"]
    assert rotated["replayed"] is False

    # 같은 세션(sid)에 머문다 — 재로그인이 아니다
    old = jwt.decode(tokens["refreshToken"], options={"verify_signature": False})
    new = jwt.decode(rotated["refreshToken"], options={"verify_signature": False})
    assert old["sid"] == new["sid"]
    assert new["typ"] == "refresh"


async def test_grace_안에_같은_refresh_가_또_오면_동일_토큰쌍을_준다(client):
    """앱 A·B 가 동시에 갱신을 시도한 경우 — 오탐으로 세션을 끊으면 안 된다."""
    tokens = await login(client)

    first = (await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})).json()
    second_response = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})

    assert second_response.status_code == 200
    second = second_response.json()
    assert second["replayed"] is True
    assert second["accessToken"] == first["accessToken"]
    assert second["refreshToken"] == first["refreshToken"]


async def test_grace_밖에서_폐기된_refresh_재등장은_탈취로_보고_세션_전체를_끊는다(client, settings):
    tokens = await login(client)
    rotated = (await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})).json()

    await asyncio.sleep(settings.refresh_grace_seconds + 1)

    reuse = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert reuse.status_code == 401
    assert reuse.json()["error"] == "token_reuse_detected"

    # 핵심: 정상 사용자가 들고 있던 최신 refresh 까지 함께 죽어야 한다 (계보 전체 무효화)
    after = await client.post("/auth/refresh", json={"refreshToken": rotated["refreshToken"]})
    assert after.status_code == 401
    assert after.json()["error"] == "invalid_grant"


async def test_동시에_들어온_같은_refresh_는_한_번만_회전한다(client):
    tokens = await login(client)

    responses = await asyncio.gather(
        *[client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]}) for _ in range(5)]
    )

    assert [r.status_code for r in responses] == [200] * 5
    issued = {r.json()["refreshToken"] for r in responses}
    assert len(issued) == 1, "동시 요청인데 refresh 가 여러 개 발급됐다"


async def test_로그아웃하면_세션이_무효화된다(client):
    tokens = await login(client)

    assert (await client.post("/auth/logout", json={"refreshToken": tokens["refreshToken"]})).status_code == 204

    after = await client.post("/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert after.status_code == 401


async def test_access_토큰을_refresh_로_들이밀_수_없다(client):
    tokens = await login(client)
    response = await client.post("/auth/refresh", json={"refreshToken": tokens["accessToken"]})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_grant"


async def test_쿠키만으로도_갱신된다(client, settings):
    """브라우저 경로 — body 없이 쿠키만 자동 첨부되는 상황."""
    await login(client)  # AsyncClient 가 쿠키를 보관한다
    response = await client.post("/auth/refresh")
    assert response.status_code == 200
    assert response.json()["accessToken"]
