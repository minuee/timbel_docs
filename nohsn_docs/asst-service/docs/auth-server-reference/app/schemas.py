"""요청/응답 스키마.

응답 키는 현행 포털이 쓰는 camelCase(accessToken/refreshToken)를 유지한다.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(..., description="로그인 계정")
    password: str = Field(..., description="비밀번호")


class RefreshRequest(BaseModel):
    """앱 백엔드가 서버 간 호출로 갱신할 때 사용.

    비우면 쿠키(refresh_token)에서 읽는다.
    """

    refreshToken: str | None = None


class TokenResponse(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "Bearer"
    expiresIn: int = Field(..., description="access 토큰 잔여 수명(초)")
    refreshExpiresIn: int = Field(..., description="refresh 토큰 잔여 수명(초)")
    csrfToken: str
    #: grace 윈도우로 직전 발급 쌍을 그대로 돌려준 경우 true (경합 관측용)
    replayed: bool = False


class ErrorResponse(BaseModel):
    error: str = Field(..., description="invalid_grant · token_reuse_detected 등 고정 코드")
    message: str
