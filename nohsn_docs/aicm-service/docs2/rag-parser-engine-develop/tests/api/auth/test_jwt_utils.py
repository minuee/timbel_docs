"""Auth v2 jwt_utils 단위 테스트 — Phase 9 (KMS-Plus).

5 케이스:
1. hash + verify (왕복).
2. encode + decode (왕복).
3. expired token → InvalidToken.
4. wrong signature → InvalidToken.
5. role claim 보존.
"""
from __future__ import annotations

import os
import time

import pytest

from src.api.auth import jwt_utils
from src.api.auth.jwt_utils import (
    InvalidToken,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_roundtrip():
    h = hash_password("MySecret123!")
    assert h != "MySecret123!"
    assert verify_password("MySecret123!", h) is True
    assert verify_password("wrong", h) is False
    # 빈 hash → False (legacy 계정).
    assert verify_password("MySecret123!", "") is False
    assert verify_password("MySecret123!", None) is False  # type: ignore[arg-type]


def test_access_token_encode_decode_roundtrip():
    token = create_access_token(
        subject="acct-123", tenant_id="tnt-1", role="admin"
    )
    payload = decode_token(token)
    assert payload["sub"] == "acct-123"
    assert payload["tenant_id"] == "tnt-1"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert payload["iat"] <= payload["exp"]


def test_expired_token_raises():
    # ttl=0h → 즉시 만료. iat==exp 인 토큰. jose 가 exp <= now 면 거부.
    token = create_access_token(subject="x", ttl_hours=0)
    # 안전하게 1초 sleep — exp 가 정확히 같은 초이거나 1초 지난 후 만료 보장.
    time.sleep(1)
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_wrong_signature_rejected(monkeypatch):
    """다른 SECRET 으로 발급된 토큰은 decode 시 InvalidToken."""
    # 지금 SECRET 으로 발급.
    good = create_access_token(subject="x", role="member")
    # SECRET 을 다른 값으로 바꾸고 같은 토큰 디코드 시도.
    monkeypatch.setattr(jwt_utils, "JWT_SECRET", "TOTALLY-DIFFERENT-SECRET")
    with pytest.raises(InvalidToken):
        decode_token(good)


def test_role_claim_preserved_for_each_role():
    for role in ("viewer", "member", "admin", "owner"):
        t = create_access_token(subject="u", role=role)
        p = decode_token(t)
        assert p["role"] == role


def test_refresh_token_has_distinct_type():
    t = create_refresh_token("u-1")
    p = decode_token(t)
    assert p["type"] == "refresh"
    assert p["sub"] == "u-1"
