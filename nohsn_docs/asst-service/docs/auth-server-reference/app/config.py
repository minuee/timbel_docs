"""인증서버 설정.

수명(TTL)·쿠키·세션 정책은 전부 여기 설정값이다.
정책이 바뀌면 코드가 아니라 .env 만 바꾼다. (PPT 부록 C)
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── JWT 서명 ────────────────────────────────────────────────
    jwt_issuer: str = "timbel-portal"
    jwt_audience: str = "timbel-apps"
    jwt_kid: str = "timbel-on-premise-v1"
    jwt_private_key_path: str = "keys/private.pem"
    # 키 회전 중 이전 공개키를 JWKS에 함께 노출한다. "kid:경로,kid2:경로2" 형식.
    jwt_retired_public_keys: str = ""

    # ── 수명 정책 ───────────────────────────────────────────────
    # 현행 정책값은 access 60분 / refresh 14일이나 실측은 20분 / 65분이었다.
    # 아래 값이 실제로 적용되는 유일한 지점이 되도록 한다.
    access_ttl_seconds: int = 600  # 10분 (권장 5~15분)
    refresh_ttl_seconds: int = 86400  # 1일 (권장 1~3일)

    # 앱 간 동시 갱신 경합 보호. 이 시간 안에 같은 refresh 가 다시 오면
    # 재사용(탈취)이 아니라 경합으로 보고 "직전에 발급한 동일 토큰 쌍"을 그대로 돌려준다.
    refresh_grace_seconds: int = 20  # 권장 10~30초

    # 0 이면 미적용
    session_idle_timeout_seconds: int = 1800  # 무조작 30분 → 재로그인 (공용 상담석)
    session_absolute_ttl_seconds: int = 43200  # 로그인 후 12시간 → 무조건 재로그인

    # ── 쿠키 ───────────────────────────────────────────────────
    # 인증서버가 직접 Set-Cookie 할지 여부. False 면 JSON 응답만 주고
    # 각 앱 백엔드가 쿠키를 굽는다. (PPT 슬라이드 25 - 6번 협의 항목)
    cookie_enabled: bool = True
    cookie_access_name: str = "access_token"
    cookie_refresh_name: str = "refresh_token"
    cookie_csrf_name: str = "csrf_token"
    cookie_secure: bool = False  # 운영 HTTPS 필수 ON / 개발기 HTTP+IP 는 불가
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None  # 단일 서버라 보통 None (포트 무관 공유)
    # False = 세션 쿠키(브라우저 닫으면 폐기) / True = 지속 쿠키
    cookie_persistent: bool = False

    # 쿠키로 refresh 가 전달될 때만 적용되는 double-submit CSRF 검증
    csrf_enabled: bool = True

    # ── 인프라 ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "auth"
    # 쿠키를 쓰려면 반드시 정확한 오리진 목록 + allow_credentials 가 필요하다(와일드카드 불가)
    cors_allow_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
