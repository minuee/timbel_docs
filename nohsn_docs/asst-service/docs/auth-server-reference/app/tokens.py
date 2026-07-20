"""JWT 발급/검증. (RS256, kid 헤더 포함)"""

import time
import uuid
from dataclasses import dataclass

import jwt

from .config import Settings
from .errors import InvalidGrant
from .keys import KeyRing


def now_ts() -> int:
    return int(time.time())


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: int

    @property
    def expires_in(self) -> int:
        return max(0, self.expires_at - now_ts())


class TokenService:
    def __init__(self, settings: Settings, keyring: KeyRing):
        self._settings = settings
        self._keyring = keyring

    def issue(self, *, typ: str, sub: str, sid: str, ttl: int, claims: dict | None = None) -> IssuedToken:
        issued_at = now_ts()
        expires_at = issued_at + ttl
        jti = uuid.uuid4().hex
        payload = {
            "iss": self._settings.jwt_issuer,
            "aud": self._settings.jwt_audience,
            "sub": sub,
            "sid": sid,  # 세션(패밀리) ID — rotation 계보를 묶는 키
            "typ": typ,  # "access" | "refresh"
            "jti": jti,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
            **(claims or {}),
        }
        token = jwt.encode(
            payload,
            self._keyring.private_pem,
            algorithm="RS256",
            headers={"kid": self._keyring.kid},
        )
        return IssuedToken(token=token, jti=jti, expires_at=expires_at)

    def decode(self, token: str, *, expected_typ: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidGrant("토큰 형식이 올바르지 않습니다.") from exc

        public_key = self._keyring.public_key_for(header.get("kid"))
        if public_key is None:
            raise InvalidGrant("알 수 없는 서명 키(kid)입니다.")

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidGrant("refresh 토큰이 만료되었습니다.") from exc
        except jwt.PyJWTError as exc:
            raise InvalidGrant("토큰 검증에 실패했습니다.") from exc

        # access 토큰을 refresh 로 들이미는 혼용을 막는다.
        if payload.get("typ") != expected_typ:
            raise InvalidGrant(f"'{expected_typ}' 토큰이 아닙니다.")
        return payload
