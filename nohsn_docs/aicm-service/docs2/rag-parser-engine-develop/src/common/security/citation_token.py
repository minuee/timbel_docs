"""HMAC signed token for citation HTML landing page (Telegram guest path).

D41 Phase 1 — Telegram bot 사용자가 JWT 없이도 `[N]` link 로 들어왔을 때
HMAC 서명 token + 만료시간으로 인증한다. tenant_id 는 token payload 안에
들어 있어 cross-tenant guess 차단.

GPT-5 phase 0 v3 P0 fix (spec §4 변경 5):
- 서명 검증 *먼저*, 만료 평가 *나중* — 만료 오라클 차단.
- tenant_id canonical UUID 검증 — 길이/문자 제한.
- token ver prefix (`v1`) — 미래 알고리즘 교체 대비.
- exp 상한 (30 days) — 영구 token 차단.
- secret 길이 < 32 byte → RuntimeError (`_ensure_secret`).
- block_id 도 UUID 검증 (path tampering 차단).
- compare_digest 사용 (constant-time).

token format: ``v1.<base64url_tenant_id>.<hmac_sha256_hex>``
URL: ``/api/v1/citations/{block_id}?t=<token>&exp=<unix_ts>``
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

from src.common.config import settings

_TOKEN_VER = "v1"
_MAX_TTL_SECS = 30 * 24 * 3600   # 30 days (hard cap — spec §9 영구 token 차단)
_MIN_TTL_SECS = 300              # 5 minutes (hard floor)
_DEFAULT_TTL_SECS = 12 * 3600    # 12 hours (GPT-5 phase 0 v2 권장)


def _resolved_default_ttl() -> int:
    """settings.CITATION_HMAC_TTL_SECS override + 가드.

    하드코딩 회피 — .env / settings 로 운영자가 조정 가능. 범위는 5분 ~ 30일
    강제 (override 도 가드).
    """
    raw = getattr(settings, "CITATION_HMAC_TTL_SECS", None)
    if raw is None:
        return _DEFAULT_TTL_SECS
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SECS
    return max(_MIN_TTL_SECS, min(val, _MAX_TTL_SECS))


@dataclass(frozen=True)
class VerifyResult:
    """citation token 검증 결과.

    Attributes:
        tenant_id: 검증 통과 시 token payload 의 tenant_id (UUID).
        signature_invalid: 서명 검증 실패 (또는 format invalid). True 시 401.
        expired: 서명은 valid 했지만 만료. True 시 410.
    """

    tenant_id: uuid.UUID | None = None
    signature_invalid: bool = False
    expired: bool = False


def _ensure_secret() -> bytes:
    """HMAC secret 길이 검증. < 32 byte 면 RuntimeError.

    startup hook 에서 1회 호출 → 운영 실수 즉시 탐지 (GPT-5 phase 0 v3 권장).
    sign / verify 시점에도 매번 호출되지만, .env load 후 secret 누락은
    드물어 비용 무시 가능.
    """
    raw = (getattr(settings, "CITATION_HMAC_SECRET", "") or "").encode()
    if len(raw) < 32:
        raise RuntimeError(
            "CITATION_HMAC_SECRET must be >= 32 bytes (set in .env). "
            "Generate via: `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`"
        )
    return raw


def sign_citation_token(
    block_id: str,
    tenant_id: str | uuid.UUID,
    *,
    ttl_secs: int | None = None,
) -> tuple[str, int]:
    """Telegram 링크 build 시점 token 생성.

    Args:
        block_id: citation 의 block UUID (str).
        tenant_id: token payload 의 tenant UUID (str | UUID).
        ttl_secs: TTL 초. None 이면 settings.CITATION_HMAC_TTL_SECS (default 12h).
            범위는 5분 ~ 30일 강제 (override 도 가드).

    Returns:
        ``(token, exp)`` — token = ``v1.<b64_tid>.<hmac_hex>``, exp = unix ts.

    Raises:
        ValueError: tenant_id / block_id 가 UUID 아님.
        RuntimeError: CITATION_HMAC_SECRET < 32 byte.
    """
    if ttl_secs is None:
        ttl_secs = _resolved_default_ttl()
    ttl_secs = max(_MIN_TTL_SECS, min(int(ttl_secs), _MAX_TTL_SECS))
    # UUID canonical 검증 + 정규화 (GPT-5 phase 1 pre P1):
    # 비-하이픈 UUID 또는 대문자 입력이 와도 한 가지 canonical form 만 token
    # payload 에 들어가도록 정규화. 동일 logical UUID → 동일 token.
    tid_str = str(uuid.UUID(str(tenant_id)))
    block_id = str(uuid.UUID(str(block_id)))
    exp = int(time.time()) + ttl_secs
    payload = f"{_TOKEN_VER}:{block_id}:{tid_str}:{exp}".encode()
    secret = _ensure_secret()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    tid_b64 = base64.urlsafe_b64encode(tid_str.encode()).rstrip(b"=").decode()
    token = f"{_TOKEN_VER}.{tid_b64}.{sig}"
    return token, exp


def verify_citation_token(
    *,
    block_id: str,
    token: str,
    exp: int,
) -> VerifyResult:
    """token 검증. signature_invalid / expired 분리 반환.

    GPT-5 phase 0 v3 P0: 서명 검증 *먼저*, 만료 평가 *나중* — 만료 오라클 차단.
    공격자가 임의 t 값에 과거 exp 보내도 401 (만료 410 아님).

    Args:
        block_id: path 의 block UUID (str).
        token: query param ``t=`` 값.
        exp: query param ``exp=`` 값 (unix ts).

    Returns:
        ``VerifyResult``. caller (router) 가 cross-tenant DB 검증 별도 수행.
    """
    # 0) basic shape
    if not token or not isinstance(token, str):
        return VerifyResult(signature_invalid=True)
    if len(token) > 512:  # DoS / 길이 제한
        return VerifyResult(signature_invalid=True)
    parts = token.split(".")
    if len(parts) != 3:
        return VerifyResult(signature_invalid=True)
    ver, tid_b64, sig_hex = parts
    if ver != _TOKEN_VER:
        return VerifyResult(signature_invalid=True)

    # 1) decode tenant_id + canonical UUID 검증
    try:
        pad = "=" * (-len(tid_b64) % 4)
        tid_str = base64.urlsafe_b64decode(tid_b64 + pad).decode()
        tenant_uuid = uuid.UUID(tid_str)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return VerifyResult(signature_invalid=True)

    # 2) block_id UUID 검증 + 정규화 (path 측 — 호출자가 이미 검증했지만 방어).
    # GPT-5 phase 1 post P1 — sign 측 canonical form 과 동일하게 verify 도 정규화.
    # path 가 uppercase UUID 같은 변형이어도 valid token 매칭.
    try:
        block_id_canon = str(uuid.UUID(str(block_id)))
    except (ValueError, TypeError):
        return VerifyResult(signature_invalid=True)
    # tenant_id 도 canonical (P2 — 안전 차원, signer 가 이미 canonical 이지만 명시).
    tid_str = str(tenant_uuid)

    # 3) exp basic 검증
    if not isinstance(exp, int) or exp < 0:
        return VerifyResult(signature_invalid=True)
    now = int(time.time())
    # exp 가 너무 미래 (30 days+ 우회 token) → 무효.
    if exp - now > _MAX_TTL_SECS:
        return VerifyResult(signature_invalid=True)

    # 4) **HMAC 서명 검증 먼저** (GPT-5 P0 — 만료 오라클 차단)
    try:
        secret = _ensure_secret()
    except RuntimeError:
        # secret 미설정 시 모든 token 무효 (운영 실수 → startup hook 이 catch).
        return VerifyResult(signature_invalid=True)
    expected_payload = f"{_TOKEN_VER}:{block_id_canon}:{tid_str}:{exp}".encode()
    expected_sig = hmac.new(secret, expected_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig_hex):
        return VerifyResult(signature_invalid=True)

    # 5) 서명 OK → 만료 평가
    if now > exp:
        return VerifyResult(expired=True)

    # 6) 통과
    return VerifyResult(tenant_id=tenant_uuid)


__all__ = [
    "VerifyResult",
    "sign_citation_token",
    "verify_citation_token",
    "_ensure_secret",  # startup hook + test 용
    "_resolved_default_ttl",
]
