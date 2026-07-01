"""Fernet 암호화 — agent_channels config_encrypted, 향후 기타 민감 데이터.

DB 의 ``agent_channels.config_encrypted`` 컬럼은 Fernet 암호화된 BYTEA.
키는 환경변수 ``AGENT_CHANNEL_KEY`` (urlsafe base64 32 bytes) 에서 로드.

원칙:
- 평문 설정 (bot token, webhook secret, credentials 등) 은 *DB 에 절대 저장 안 함* — 암호화된 ciphertext 만.
- 메모리 노출 최소화 — decrypt 후 사용 즉시 사용 + 폐기.
- 키 회전 — ``AGENT_CHANNEL_KEY`` 변경 시 모든 채널 config 재암호화 필요. CLI script.
- 키 미설정 시 graceful 비활성 (agent 기능 비활성, crash X).

키 생성:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

env 추가:
    AGENT_CHANNEL_KEY=<생성된 key>
"""
from __future__ import annotations

import json
import os
from typing import Any, Final

from cryptography.fernet import Fernet, InvalidToken

from src.common.logging import get_logger

log = get_logger(__name__)


_ENV_VAR: Final[str] = "AGENT_CHANNEL_KEY"
_cipher: Fernet | None = None
_init_attempted: bool = False


class AgentChannelKeyMissing(RuntimeError):
    """AGENT_CHANNEL_KEY env 가 미설정. 에이전트 채널 기능 비활성 사유."""


def _init_cipher() -> Fernet | None:
    """싱글턴 Fernet 인스턴스. 실패 시 None — 호출자가 graceful 처리."""
    global _cipher, _init_attempted
    if _init_attempted:
        return _cipher
    _init_attempted = True

    key = os.environ.get(_ENV_VAR, "").strip()
    if not key:
        log.warning(
            "agent_channel_key_missing",
            hint="AGENT_CHANNEL_KEY env 미설정 — 에이전트 채널 기능 비활성화. "
            f"키 생성: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
        )
        return None
    try:
        _cipher = Fernet(key.encode("utf-8"))
        log.info("agent_channel_cipher_initialized")
    except (ValueError, TypeError) as e:
        log.error(
            "agent_channel_key_invalid",
            error=str(e),
            hint="AGENT_CHANNEL_KEY 가 urlsafe base64 32-byte 형식이 아님. 재생성 필요.",
        )
        _cipher = None
    return _cipher


def is_available() -> bool:
    """에이전트 채널 암호화 사용 가능 여부. False 면 에이전트 기능도 비활성."""
    return _init_cipher() is not None


def encrypt_bytes(plaintext: bytes) -> bytes:
    """평문 바이트 → ciphertext bytes. 키 없으면 RuntimeError."""
    cipher = _init_cipher()
    if cipher is None:
        raise AgentChannelKeyMissing(
            "AGENT_CHANNEL_KEY env 미설정 — 채널 설정 암호화 불가"
        )
    if not isinstance(plaintext, (bytes, bytearray, memoryview)):
        raise TypeError("plaintext must be bytes-like")
    if not plaintext:
        raise ValueError("plaintext 비어있음")
    return cipher.encrypt(bytes(plaintext))


def decrypt_bytes(ciphertext: bytes) -> bytes:
    """ciphertext bytes → 평문 바이트. 키 없거나 ciphertext 손상 시 예외."""
    cipher = _init_cipher()
    if cipher is None:
        raise AgentChannelKeyMissing("AGENT_CHANNEL_KEY env 미설정 — 복호화 불가")
    if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
        raise TypeError("ciphertext must be bytes-like")
    try:
        return cipher.decrypt(bytes(ciphertext))
    except InvalidToken as e:
        raise ValueError(
            "ciphertext invalid — 키 회전 후 미재암호화 또는 데이터 손상"
        ) from e


def encrypt_dict(payload: dict[str, Any]) -> bytes:
    """dict → JSON → ciphertext bytes. 키 없으면 RuntimeError."""
    json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return encrypt_bytes(json_bytes)


def decrypt_dict(ciphertext: bytes) -> dict[str, Any]:
    """ciphertext bytes → JSON → dict. 키 없거나 손상 시 예외."""
    plaintext = decrypt_bytes(ciphertext)
    return json.loads(plaintext.decode("utf-8"))


def reset_for_tests() -> None:
    """테스트 fixture 용 — 모듈 싱글턴 reset."""
    global _cipher, _init_attempted
    _cipher = None
    _init_attempted = False
