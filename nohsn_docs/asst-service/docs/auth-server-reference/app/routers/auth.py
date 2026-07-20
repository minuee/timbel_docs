"""POST /auth/login · /auth/refresh · /auth/logout"""

from fastapi import APIRouter, Request, Response

from ..config import Settings
from ..cookies import clear_auth_cookies, set_auth_cookies, verify_csrf
from ..errors import InvalidGrant
from ..schemas import ErrorResponse, LoginRequest, RefreshRequest, TokenResponse
from ..service import AuthService, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])

_ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


def _service(request: Request) -> AuthService:
    return request.app.state.auth_service


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _to_response(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        accessToken=pair.access_token,
        refreshToken=pair.refresh_token,
        expiresIn=pair.access_expires_in,
        refreshExpiresIn=pair.refresh_expires_in,
        csrfToken=pair.csrf_token,
        replayed=pair.replayed,
    )


@router.post("/login", response_model=TokenResponse, responses=_ERRORS)
async def login(body: LoginRequest, request: Request, response: Response) -> TokenResponse:
    """ID/PW 로 최초 세션을 발급한다. 이 쿠키 하나로 모든 앱이 SSO 된다."""
    pair = await _service(request).login(body.account, body.password)
    set_auth_cookies(response, pair, _settings(request))
    return _to_response(pair)


@router.post("/refresh", response_model=TokenResponse, responses=_ERRORS)
async def refresh(
    request: Request, response: Response, body: RefreshRequest | None = None
) -> TokenResponse:
    """refresh 토큰으로 새 access+refresh 를 발급한다 (rotation).

    토큰 출처는 두 가지다.
      1. body.refreshToken — 앱 백엔드의 서버 간 호출
      2. refresh_token 쿠키 — 브라우저 직접 호출 (이때만 CSRF 검증)

    구 refresh 는 즉시 폐기된다. 폐기된 것이 grace(기본 20초) 밖에서 다시 오면
    탈취로 간주하고 세션 전체를 무효화한다.
    """
    settings = _settings(request)
    token = body.refreshToken if body else None
    if not token:
        token = request.cookies.get(settings.cookie_refresh_name)
        if token:
            verify_csrf(request, settings)

    if not token:
        raise InvalidGrant("refresh 토큰이 없습니다.")

    pair = await _service(request).refresh(token)
    set_auth_cookies(response, pair, settings)
    return _to_response(pair)


@router.post("/logout", status_code=204, response_class=Response)
async def logout(request: Request, body: RefreshRequest | None = None) -> Response:
    """세션 계보 전체를 무효화하고 쿠키를 제거한다."""
    settings = _settings(request)
    token = (body.refreshToken if body else None) or request.cookies.get(settings.cookie_refresh_name)
    await _service(request).logout(token)
    # 쿠키 삭제 헤더가 살아있도록 응답 객체에 직접 세팅해서 반환한다.
    response = Response(status_code=204)
    clear_auth_cookies(response, settings)
    return response
