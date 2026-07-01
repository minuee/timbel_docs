"""AES-GCM 기반 간이 시크릿 박스. v1 용. v2 는 vault 로 교체.

- 환경변수 KMS_CONNECTOR_MASTER_KEY 에서 32바이트 base64 키 읽음
- encrypt_secret(dict) → "aes-gcm:v1:<base64 nonce + ciphertext + tag>"
- decrypt_secret(str) → 원본 dict, 변조 시 SecretBoxError
"""
from __future__ import annotations
import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "aes-gcm:v1:"
_NONCE_LEN = 12


class SecretBoxError(Exception):
    pass


def _key() -> bytes:
    raw = os.environ.get("KMS_CONNECTOR_MASTER_KEY")
    if not raw:
        raise SecretBoxError("KMS_CONNECTOR_MASTER_KEY not set")
    try:
        key = base64.b64decode(raw)
    except Exception as e:
        raise SecretBoxError(f"invalid key base64: {e}") from e
    if len(key) != 32:
        raise SecretBoxError(f"key must be 32 bytes, got {len(key)}")
    return key


def encrypt_secret(payload: dict) -> str:
    aes = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    pt = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ct = aes.encrypt(nonce, pt, associated_data=None)
    return _PREFIX + base64.b64encode(nonce + ct).decode()


def decrypt_secret(blob: str) -> dict:
    if not blob.startswith(_PREFIX):
        raise SecretBoxError("unknown secret format")
    try:
        raw = base64.b64decode(blob[len(_PREFIX):])
    except Exception as e:
        raise SecretBoxError(f"invalid base64: {e}") from e
    if len(raw) < _NONCE_LEN + 16:
        raise SecretBoxError("blob too short")
    nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    try:
        pt = AESGCM(_key()).decrypt(nonce, ct, associated_data=None)
    except Exception as e:
        raise SecretBoxError(f"decrypt failed: {e}") from e
    return json.loads(pt.decode())
