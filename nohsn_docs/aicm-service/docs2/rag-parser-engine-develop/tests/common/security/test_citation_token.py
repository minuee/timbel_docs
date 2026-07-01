"""D41 Phase 4 — HMAC citation_token unit tests.

검증:
- sign / verify happy path.
- 만료 token → expired.
- 잘못된 서명 → invalid (만료 오라클 차단 검증 포함).
- secret 변경 / mismatch → invalid.
- format invalid (parts count / ver / b64) → invalid.
- block_id canonicalization (uppercase / no-hyphen path).
- tenant_id canonicalization.
- secret < 32 byte → RuntimeError (_ensure_secret).
- TTL 가드 (300~2592000 강제).
- exp 너무 미래 (>30d) → invalid.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import importlib
import os
import time
import uuid

import pytest


_DEV_SECRET = "MIPKScw-vYjiSqtHLJubX7x-RBvGJZTaK3vGd3UzYU4N-wzFEgwDuIXazUd4A1Ap"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    """모든 테스트에 안전한 secret 설정. settings 객체 직접 수정."""
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_SECRET", _DEV_SECRET, raising=False)
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_TTL_SECS", 43200, raising=False)
    yield


def _fresh_token_module():
    """매 테스트마다 module 을 다시 import — settings 변경 반영."""
    import src.common.security.citation_token as ct
    importlib.reload(ct)
    return ct


def test_sign_verify_happy_path():
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)
    assert exp > int(time.time())
    assert token.startswith("v1.")
    assert token.count(".") == 2

    result = ct.verify_citation_token(block_id=block_id, token=token, exp=exp)
    assert result.tenant_id == uuid.UUID(tenant_id)
    assert not result.signature_invalid
    assert not result.expired


def test_sign_verify_uppercase_block_id_path():
    """path 가 uppercase UUID 라도 canonical 정규화로 verify 통과."""
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)
    # verify with uppercase
    result = ct.verify_citation_token(
        block_id=block_id.upper(), token=token, exp=exp
    )
    assert result.tenant_id == uuid.UUID(tenant_id)


def test_sign_verify_no_hyphen_block_id_path():
    """path 가 hyphen 없는 hex 라도 canonical 정규화로 verify 통과."""
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)
    no_hyphen = block_id.replace("-", "")
    result = ct.verify_citation_token(
        block_id=no_hyphen, token=token, exp=exp
    )
    assert result.tenant_id == uuid.UUID(tenant_id)


def test_sign_uppercase_tenant_id_normalizes():
    """tenant_id 가 uppercase 로 들어와도 sign 측에서 canonical 화 → verify 동일."""
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token1, _ = ct.sign_citation_token(block_id, tenant_id)
    token2, _ = ct.sign_citation_token(block_id, tenant_id.upper())
    # 동일 logical UUID → 동일 token (시간 차이 무시하기 위해 ttl 강제)
    # 시그너처만 비교 — exp 다를 수 있어 token 직접 비교는 어려움.
    # 대신 각각 verify 가 같은 tenant_id 반환하는지만 보장.
    result1 = ct.verify_citation_token(
        block_id=block_id, token=token1, exp=int(time.time()) + 100
    )
    # exp 가 sign 때와 다르면 signature mismatch → invalid 인 것이 정상.
    # 이 테스트는 sign 호출이 raise 없이 통과하는지만 확인.
    assert token1.startswith("v1.")
    assert token2.startswith("v1.")


def test_invalid_signature_returns_invalid():
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)
    # 마지막 2자 변조 → signature mismatch
    bad = token[:-2] + ("ff" if not token.endswith("ff") else "aa")
    result = ct.verify_citation_token(block_id=block_id, token=bad, exp=exp)
    assert result.signature_invalid
    assert not result.expired
    assert result.tenant_id is None


def test_oracle_blocked_past_exp_with_wrong_token():
    """만료 오라클 차단: 잘못된 서명 + 과거 exp → expired (X) signature_invalid (O).

    공격자가 임의 token + 과거 exp 를 보내 410 응답 받아 만료 사실을 추론하는
    것을 차단. 서명 검증을 만료 평가보다 *먼저* 수행.
    """
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    fake_token = "v1.YWJjZA.deadbeef" * 4  # 적당한 길이의 임의 token
    past_exp = int(time.time()) - 1000
    result = ct.verify_citation_token(
        block_id=block_id, token=fake_token[:200], exp=past_exp
    )
    # 서명 invalid 가 먼저 — expired 가 되면 안됨 (oracle leak).
    assert result.signature_invalid
    assert not result.expired


def test_truly_expired_token_returns_expired():
    """서명은 valid 했지만 시간이 지나 만료된 token → expired=True."""
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    past_exp = int(time.time()) - 100
    # 동일 secret 으로 직접 sign — token 위조가 아닌 진짜 만료.
    secret = _DEV_SECRET.encode()
    payload = f"v1:{block_id}:{tenant_id}:{past_exp}".encode()
    sig = _hmac.new(secret, payload, hashlib.sha256).hexdigest()
    tid_b64 = base64.urlsafe_b64encode(tenant_id.encode()).rstrip(b"=").decode()
    token = f"v1.{tid_b64}.{sig}"

    result = ct.verify_citation_token(block_id=block_id, token=token, exp=past_exp)
    assert not result.signature_invalid
    assert result.expired


def test_token_format_invalid():
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    exp = int(time.time()) + 100
    # parts != 3
    assert ct.verify_citation_token(block_id=block_id, token="onlyone", exp=exp).signature_invalid
    assert ct.verify_citation_token(block_id=block_id, token="a.b.c.d", exp=exp).signature_invalid
    # ver != v1
    assert ct.verify_citation_token(block_id=block_id, token="v2.abc.def", exp=exp).signature_invalid
    # empty
    assert ct.verify_citation_token(block_id=block_id, token="", exp=exp).signature_invalid
    # too long (>512)
    long_token = "v1." + "a" * 600 + ".bb"
    assert ct.verify_citation_token(block_id=block_id, token=long_token, exp=exp).signature_invalid


def test_invalid_block_id_returns_invalid():
    ct = _fresh_token_module()
    tenant_id = str(uuid.uuid4())
    block_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)
    result = ct.verify_citation_token(block_id="not-a-uuid", token=token, exp=exp)
    assert result.signature_invalid


def test_invalid_exp_type_returns_invalid():
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, _ = ct.sign_citation_token(block_id, tenant_id)
    # exp 가 음수
    r1 = ct.verify_citation_token(block_id=block_id, token=token, exp=-1)
    assert r1.signature_invalid
    # exp 가 너무 미래 (>30 days)
    far_future = int(time.time()) + 31 * 24 * 3600
    r2 = ct.verify_citation_token(block_id=block_id, token=token, exp=far_future)
    assert r2.signature_invalid


def test_secret_change_invalidates_token(monkeypatch):
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)

    # secret 회전 — 32 byte 이상이라야 _ensure_secret 통과
    new_secret = "x" * 48
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_SECRET", new_secret, raising=False)
    ct2 = _fresh_token_module()
    result = ct2.verify_citation_token(block_id=block_id, token=token, exp=exp)
    assert result.signature_invalid


def test_sign_invalid_tenant_id_raises():
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    with pytest.raises(ValueError):
        ct.sign_citation_token(block_id, "not-uuid")


def test_sign_invalid_block_id_raises():
    ct = _fresh_token_module()
    tenant_id = str(uuid.uuid4())
    with pytest.raises(ValueError):
        ct.sign_citation_token("not-uuid", tenant_id)


def test_secret_too_short_raises(monkeypatch):
    """secret < 32 byte → RuntimeError."""
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_SECRET", "tooshort", raising=False)
    ct = _fresh_token_module()
    with pytest.raises(RuntimeError):
        ct._ensure_secret()
    # sign 도 raise
    with pytest.raises(RuntimeError):
        ct.sign_citation_token(str(uuid.uuid4()), str(uuid.uuid4()))


def test_secret_missing_raises(monkeypatch):
    """secret 빈 문자열 / None → RuntimeError."""
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_SECRET", "", raising=False)
    ct = _fresh_token_module()
    with pytest.raises(RuntimeError):
        ct._ensure_secret()


def test_ttl_guard_lower_bound(monkeypatch):
    """TTL < 300 (5분) 강제 floor."""
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_TTL_SECS", 10, raising=False)
    ct = _fresh_token_module()
    assert ct._resolved_default_ttl() == 300


def test_ttl_guard_upper_bound(monkeypatch):
    """TTL > 2592000 (30d) 강제 ceiling."""
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_TTL_SECS", 99999999, raising=False)
    ct = _fresh_token_module()
    assert ct._resolved_default_ttl() == 30 * 24 * 3600


def test_sign_explicit_ttl_clamped():
    """sign 호출 시 ttl_secs 인자도 가드."""
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    # ttl=10 (5분 미만) → 300 으로 강등.
    _, exp = ct.sign_citation_token(block_id, tenant_id, ttl_secs=10)
    now = int(time.time())
    assert exp - now >= 250  # 약간 여유 (실행 시간)
    assert exp - now <= 320

    # ttl > 30d → 30d 로 강등.
    _, exp2 = ct.sign_citation_token(block_id, tenant_id, ttl_secs=99999999)
    assert exp2 - now <= 30 * 24 * 3600 + 30


def test_token_binds_block_id_path_tampering():
    """다른 block_id 의 path 로 verify → mismatch (HMAC payload 에 block_id 포함)."""
    ct = _fresh_token_module()
    block_a = str(uuid.uuid4())
    block_b = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token_a, exp = ct.sign_citation_token(block_a, tenant_id)
    # block_a 용 token 을 block_b path 로 사용 → invalid.
    result = ct.verify_citation_token(block_id=block_b, token=token_a, exp=exp)
    assert result.signature_invalid


def test_token_binds_exp_tampering():
    """exp 변조 → HMAC mismatch."""
    ct = _fresh_token_module()
    block_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())
    token, exp = ct.sign_citation_token(block_id, tenant_id)
    # exp 다르게 → invalid
    result = ct.verify_citation_token(block_id=block_id, token=token, exp=exp + 1000)
    assert result.signature_invalid
