"""PR-Z11A — 메일 계정 자격증명 Fernet 암호화 모듈.

DB 의 ``user_mail_accounts.password_encrypted`` 컬럼은 Fernet 암호화된 BYTEA.
키는 환경변수 ``MAIL_CRED_KEY`` (urlsafe base64 32 bytes) 에서 로드.

원칙:
- 평문 비밀번호는 *DB 에 절대 저장 안 함* — 암호화된 ciphertext 만.
- 메모리 노출 최소화 — polling 직전 복호화 후 IMAP 연결 즉시 사용 + 폐기.
- 키 회전 — ``MAIL_CRED_KEY`` 변경 시 모든 계정 password 재암호화 필요. CLI script.
- 키 미설정 시 메일 기능 *graceful 비활성* (404/501 응답, crash X).

키 생성:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

env 추가:
    MAIL_CRED_KEY=<생성된 key>
"""
from __future__ import annotations

import os
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

from src.common.logging import get_logger

log = get_logger(__name__)


_ENV_VAR: Final[str] = "MAIL_CRED_KEY"
_cipher: Fernet | None = None
_init_attempted: bool = False


class MailCredKeyMissing(RuntimeError):
    """MAIL_CRED_KEY env 가 미설정. 메일 기능 비활성 사유."""


def _init_cipher() -> Fernet | None:
    """싱글턴 Fernet 인스턴스. 실패 시 None — 호출자가 graceful 처리."""
    global _cipher, _init_attempted
    if _init_attempted:
        return _cipher
    _init_attempted = True

    key = os.environ.get(_ENV_VAR, "").strip()
    if not key:
        log.warning(
            "mail_cred_key_missing",
            hint="MAIL_CRED_KEY env 미설정 — 메일 계정 기능 비활성화. "
            f"키 생성: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
        )
        return None
    try:
        _cipher = Fernet(key.encode("utf-8"))
        log.info("mail_cred_cipher_initialized")
    except (ValueError, TypeError) as e:
        log.error(
            "mail_cred_key_invalid",
            error=str(e),
            hint="MAIL_CRED_KEY 가 urlsafe base64 32-byte 형식이 아님. 재생성 필요.",
        )
        _cipher = None
    return _cipher


def is_available() -> bool:
    """메일 자격증명 암호화 사용 가능 여부. False 면 메일 API 도 비활성."""
    return _init_cipher() is not None


def encrypt(plaintext: str) -> bytes:
    """평문 비밀번호 → ciphertext bytes. 키 없으면 RuntimeError."""
    cipher = _init_cipher()
    if cipher is None:
        raise MailCredKeyMissing(
            "MAIL_CRED_KEY env 미설정 — 메일 계정 자격증명 암호화 불가"
        )
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be str")
    if not plaintext:
        raise ValueError("plaintext password 비어있음")
    return cipher.encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """ciphertext bytes → 평문. 키 없거나 ciphertext 손상 시 예외."""
    cipher = _init_cipher()
    if cipher is None:
        raise MailCredKeyMissing("MAIL_CRED_KEY env 미설정 — 복호화 불가")
    if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
        raise TypeError("ciphertext must be bytes-like")
    try:
        return cipher.decrypt(bytes(ciphertext)).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "ciphertext invalid — 키 회전 후 미재암호화 또는 데이터 손상"
        ) from e


def reset_for_tests() -> None:
    """테스트 fixture 용 — 모듈 싱글턴 reset."""
    global _cipher, _init_attempted
    _cipher = None
    _init_attempted = False
