"""JWT + bcrypt 유틸 — Auth v2 핵심.

Phase 9 (KMS-Plus).

- ``hash_password`` / ``verify_password`` — passlib bcrypt context.
- ``create_access_token`` / ``create_refresh_token`` — python-jose HS256.
- ``decode_token`` — 만료/서명 실패는 ``InvalidToken`` 으로 통일.

env 변수:
- ``KMS_JWT_SECRET`` (default: dev-secret-change-in-prod) — prod 배포 시 반드시 override.
- ``KMS_JWT_ACCESS_TTL_HOURS`` (default: 168 = 7일).
- ``KMS_JWT_REFRESH_TTL_HOURS`` (default: 720 = 30일).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt


JWT_SECRET = os.environ.get("KMS_JWT_SECRET", "dev-secret-change-in-prod")
JWT_ALG = "HS256"
ACCESS_TOKEN_TTL_HOURS = int(os.environ.get("KMS_JWT_ACCESS_TTL_HOURS", "168"))   # 7 일
REFRESH_TOKEN_TTL_HOURS = int(os.environ.get("KMS_JWT_REFRESH_TTL_HOURS", "720"))  # 30 일


# bcrypt 한계 — 72 byte 초과는 ValueError (bcrypt 5.x). 명시적 truncate 로 일관 처리.
# passlib 1.7.4 + bcrypt 5.x 조합은 init 자체에 호환 버그 → bcrypt 라이브러리 직접 사용.
_BCRYPT_MAX_BYTES = 72


def _truncate_for_bcrypt(plain: str) -> bytes:
    """plain 을 utf-8 인코딩 후 72 byte 이하로 줄인 bytes 반환."""
    encoded = (plain or "").encode("utf-8")
    if len(encoded) <= _BCRYPT_MAX_BYTES:
        return encoded
    return encoded[:_BCRYPT_MAX_BYTES]


class InvalidToken(Exception):
    """JWT 디코딩 실패 (서명 불일치/만료/포맷 오류) 통합 예외."""


def hash_password(plain: str) -> str:
    """bcrypt 해시. 동일 plain 도 매번 다른 해시 (salt 임베디드).

    72 byte 초과는 자동 truncate (bcrypt 한계). 반환은 utf-8 str.
    """
    import bcrypt  # 지연 import — 모듈 로드 시 호환 검사 회피.

    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_truncate_for_bcrypt(plain), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """bcrypt verify. hashed 가 None/빈 문자열이면 False (legacy 계정)."""
    if not hashed:
        return False
    import bcrypt

    try:
        return bcrypt.checkpw(_truncate_for_bcrypt(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # 깨진 hash 또는 잘못된 input — False 로 통일.
        return False


def create_access_token(
    *,
    subject: str,
    tenant_id: str | None = None,
    role: str = "member",
    ttl_hours: int = ACCESS_TOKEN_TTL_HOURS,
    extra: dict[str, Any] | None = None,
) -> str:
    """JWT access token 발급.

    Claims:
    - ``sub`` — subject (account id 또는 email).
    - ``tenant_id`` — 활성 테넌트 (None 이면 personal 미지정).
    - ``role`` — owner / admin / member / viewer.
    - ``iat``, ``exp`` — UNIX timestamp (UTC).
    - ``type`` — "access" (refresh 와 구분).
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
        "type": "access",
    }
    if extra:
        # extra 는 reserved claim 을 덮어쓰지 않도록 update 가 아닌 setdefault.
        for k, v in extra.items():
            payload.setdefault(k, v)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def create_refresh_token(
    subject: str, ttl_hours: int = REFRESH_TOKEN_TTL_HOURS
) -> str:
    """JWT refresh token. access 와 분리된 type 으로 발급."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict[str, Any]:
    """JWT decode. 만료/서명 실패는 ``InvalidToken`` 로 변환."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError as e:
        raise InvalidToken(str(e)) from e
