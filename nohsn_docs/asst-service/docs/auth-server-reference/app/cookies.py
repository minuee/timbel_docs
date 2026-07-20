"""httpOnly 쿠키 세팅 + CSRF 검증.

쿠키 직접형: access·refresh 를 httpOnly 쿠키에 그대로 담는다.
세션ID 방식이 아닌 이유 — 세션ID는 발급한 앱만 해석할 수 있어 다른 앱이 못 푼다 = SSO 불가.

cookie_persistent=False 면 max-age 를 붙이지 않는다 = 세션 쿠키(브라우저 닫으면 폐기).
운영 전환은 코드가 아니라 설정값만 바꾸면 된다. (PPT 부록 C)
"""

import hmac

from fastapi import Request, Response

from .config import Settings
from .errors import CsrfFailed
from .service import TokenPair


def set_auth_cookies(response: Response, pair: TokenPair, settings: Settings) -> None:
    if not settings.cookie_enabled:
        return

    def _set(key: str, value: str, max_age: int | None, http_only: bool) -> None:
        response.set_cookie(
            key=key,
            value=value,
            max_age=max_age if settings.cookie_persistent else None,
            path="/",
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            httponly=http_only,
            samesite=settings.cookie_samesite,
        )

    _set(settings.cookie_access_name, pair.access_token, pair.access_expires_in, True)
    _set(settings.cookie_refresh_name, pair.refresh_token, pair.refresh_expires_in, True)
    # CSRF 토큰만 JS 가 읽어 헤더에 실어야 하므로 httpOnly 가 아니다(double-submit).
    # 이 값은 토큰이 아니라서 유출돼도 인증에 쓸 수 없다.
    _set(settings.cookie_csrf_name, pair.csrf_token, pair.refresh_expires_in, False)


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name in (settings.cookie_access_name, settings.cookie_refresh_name, settings.cookie_csrf_name):
        response.delete_cookie(
            key=name,
            path="/",
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
        )


def verify_csrf(request: Request, settings: Settings) -> None:
    """double-submit 검증. 브라우저가 쿠키로 refresh 를 보낼 때만 의미가 있다.

    앱 백엔드가 서버 간 호출로 body 에 refresh 를 실어 보내는 경로는 대상이 아니다
    (브라우저가 자동으로 붙여주는 자격증명이 없으므로 CSRF 가 성립하지 않는다).
    """
    if not settings.csrf_enabled:
        return
    cookie_value = request.cookies.get(settings.cookie_csrf_name)
    header_value = request.headers.get("X-CSRF-Token")
    if not cookie_value or not header_value or not hmac.compare_digest(cookie_value, header_value):
        raise CsrfFailed()
