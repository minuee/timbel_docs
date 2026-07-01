import os
import pytest
from src.common.crypto.secret_box import encrypt_secret, decrypt_secret, SecretBoxError


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("KMS_CONNECTOR_MASTER_KEY",
                       "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")


def test_roundtrip():
    payload = {"token": "sk-abc", "expires_at": 1700000000}
    blob = encrypt_secret(payload)
    assert blob.startswith("aes-gcm:v1:")
    assert decrypt_secret(blob) == payload


def test_tamper_detection():
    blob = encrypt_secret({"x": 1})
    tampered = blob[:-4] + "AAAA"
    with pytest.raises(SecretBoxError):
        decrypt_secret(tampered)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("KMS_CONNECTOR_MASTER_KEY", raising=False)
    with pytest.raises(SecretBoxError):
        encrypt_secret({"x": 1})
