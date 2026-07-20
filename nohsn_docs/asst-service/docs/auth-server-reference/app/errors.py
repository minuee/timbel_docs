"""인증 에러 코드.

각 앱 백엔드가 코드로 분기할 수 있게 error 문자열을 고정한다.
"""


class AuthError(Exception):
    status_code = 401

    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class InvalidCredentials(AuthError):
    def __init__(self, message: str = "아이디 또는 비밀번호가 올바르지 않습니다."):
        super().__init__("invalid_credentials", message)


class InvalidGrant(AuthError):
    """refresh 토큰이 위조·만료·미등록(이미 폐기된 세션)."""

    def __init__(self, message: str = "유효하지 않은 refresh 토큰입니다. 재로그인이 필요합니다."):
        super().__init__("invalid_grant", message)


class TokenReuseDetected(AuthError):
    """폐기된 refresh 가 grace 이후 재등장 = 탈취 의심 → 세션 전체 무효화."""

    def __init__(self) -> None:
        super().__init__(
            "token_reuse_detected",
            "이미 폐기된 refresh 토큰이 재사용되어 세션 전체를 무효화했습니다. 재로그인이 필요합니다.",
        )


class SessionIdleTimeout(AuthError):
    def __init__(self) -> None:
        super().__init__("session_idle_timeout", "장시간 미사용으로 세션이 만료되었습니다.")


class SessionAbsoluteTimeout(AuthError):
    def __init__(self) -> None:
        super().__init__("session_absolute_timeout", "세션 최대 유지 시간이 만료되었습니다.")


class CsrfFailed(AuthError):
    def __init__(self) -> None:
        super().__init__("csrf_failed", "CSRF 토큰이 유효하지 않습니다.", status_code=403)
