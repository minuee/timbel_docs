"""Fernet 암호화 단위 테스트 — agent_channels config_encrypted."""
import json
import os
import pytest
from cryptography.fernet import Fernet, InvalidToken

from src.common.crypto.fernet import (
    encrypt_bytes,
    decrypt_bytes,
    encrypt_dict,
    decrypt_dict,
    is_available,
    AgentChannelKeyMissing,
    reset_for_tests,
)


@pytest.fixture
def test_key():
    """테스트용 Fernet 키 생성."""
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture(autouse=True)
def setup_key(monkeypatch, test_key):
    """각 테스트마다 AGENT_CHANNEL_KEY 설정."""
    monkeypatch.setenv("AGENT_CHANNEL_KEY", test_key)
    reset_for_tests()
    yield
    reset_for_tests()


class TestEncryptDecryptBytes:
    """바이트 레벨 암호화/복호화."""

    def test_roundtrip_bytes(self):
        """평문 바이트 → 암호화 → 복호화 → 원본."""
        plaintext = b"bot_token=xoxb-12345:abcdef"
        ciphertext = encrypt_bytes(plaintext)
        assert isinstance(ciphertext, bytes)
        assert ciphertext != plaintext
        decrypted = decrypt_bytes(ciphertext)
        assert decrypted == plaintext

    def test_empty_bytes_raises(self):
        """빈 바이트는 거부."""
        with pytest.raises(ValueError, match="비어있음"):
            encrypt_bytes(b"")

    def test_non_bytes_raises(self):
        """바이트가 아닌 타입 거부."""
        with pytest.raises(TypeError, match="must be bytes-like"):
            encrypt_bytes("not bytes")  # type: ignore

    def test_invalid_ciphertext_raises(self):
        """손상된 ciphertext 복호화 실패."""
        with pytest.raises(ValueError, match="invalid"):
            decrypt_bytes(b"not-a-valid-fernet-token")

    def test_non_bytes_ciphertext_raises(self):
        """바이트가 아닌 ciphertext 타입 거부."""
        with pytest.raises(TypeError, match="must be bytes-like"):
            decrypt_bytes("not bytes")  # type: ignore


class TestEncryptDecryptDict:
    """딕셔너리 레벨 암호화/복호화 (JSON 직렬화)."""

    def test_roundtrip_dict(self):
        """dict → JSON → 암호화 → 복호화 → dict."""
        payload = {
            "kind": "telegram",
            "external_id": "123456789",
            "bot_token": "xoxb-12345:abcdef",
            "webhook_secret": "secret_xyz",
            "allowed_chat_ids": [1, 2, 3],
            "metadata": {"name": "봇 이름", "owner": "user@example.com"},
        }
        ciphertext = encrypt_dict(payload)
        assert isinstance(ciphertext, bytes)
        decrypted = decrypt_dict(ciphertext)
        assert decrypted == payload

    def test_unicode_dict(self):
        """한글 포함 딕셔너리."""
        payload = {
            "description": "병원 전화 상담 봇 — 24시간 운영",
            "webhook_url": "https://example.com/webhook",
            "tags": ["한글", "테스트"],
        }
        ciphertext = encrypt_dict(payload)
        decrypted = decrypt_dict(ciphertext)
        assert decrypted == payload

    def test_nested_dict(self):
        """중첩된 딕셔너리."""
        payload = {
            "channel": {
                "id": "ch-001",
                "config": {
                    "auth": {"token": "abc", "secret": "xyz"},
                    "webhooks": [
                        {"url": "https://a.com", "events": ["message"]},
                        {"url": "https://b.com", "events": ["reaction"]},
                    ],
                },
            },
            "is_active": True,
        }
        ciphertext = encrypt_dict(payload)
        decrypted = decrypt_dict(ciphertext)
        assert decrypted == payload

    def test_invalid_ciphertext_raises(self):
        """손상된 ciphertext 복호화 실패."""
        with pytest.raises(ValueError, match="invalid"):
            decrypt_dict(b"not-a-valid-token")

    def test_json_decode_error(self, test_key):
        """암호는 복호화되지만 JSON 파싱 실패."""
        # 유효한 Fernet 토큰이지만 JSON이 아닌 내용
        cipher = Fernet(test_key.encode("utf-8"))
        invalid_json = b"{not valid json"
        ciphertext = cipher.encrypt(invalid_json)

        with pytest.raises(json.JSONDecodeError):
            decrypt_dict(ciphertext)


class TestAvailability:
    """키 설정 상태 확인."""

    def test_available_with_key(self):
        """AGENT_CHANNEL_KEY 설정 시 available."""
        assert is_available() is True

    def test_unavailable_without_key(self, monkeypatch):
        """AGENT_CHANNEL_KEY 미설정 시 unavailable."""
        monkeypatch.delenv("AGENT_CHANNEL_KEY", raising=False)
        reset_for_tests()
        assert is_available() is False


class TestMissingKey:
    """키 미설정 시 동작."""

    def test_encrypt_without_key_raises(self, monkeypatch):
        """AGENT_CHANNEL_KEY 미설정 시 encrypt 실패."""
        monkeypatch.delenv("AGENT_CHANNEL_KEY", raising=False)
        reset_for_tests()
        with pytest.raises(AgentChannelKeyMissing):
            encrypt_bytes(b"test")

    def test_decrypt_without_key_raises(self, monkeypatch):
        """AGENT_CHANNEL_KEY 미설정 시 decrypt 실패."""
        monkeypatch.delenv("AGENT_CHANNEL_KEY", raising=False)
        reset_for_tests()
        with pytest.raises(AgentChannelKeyMissing):
            decrypt_bytes(b"anything")

    def test_encrypt_dict_without_key_raises(self, monkeypatch):
        """AGENT_CHANNEL_KEY 미설정 시 encrypt_dict 실패."""
        monkeypatch.delenv("AGENT_CHANNEL_KEY", raising=False)
        reset_for_tests()
        with pytest.raises(AgentChannelKeyMissing):
            encrypt_dict({"x": 1})

    def test_decrypt_dict_without_key_raises(self, monkeypatch):
        """AGENT_CHANNEL_KEY 미설정 시 decrypt_dict 실패."""
        monkeypatch.delenv("AGENT_CHANNEL_KEY", raising=False)
        reset_for_tests()
        with pytest.raises(AgentChannelKeyMissing):
            decrypt_dict(b"anything")


class TestInvalidKey:
    """잘못된 키 형식."""

    def test_invalid_base64_key(self, monkeypatch):
        """base64가 아닌 키 — cipher 초기화 실패."""
        monkeypatch.setenv("AGENT_CHANNEL_KEY", "not-valid-base64!!!")
        reset_for_tests()
        assert is_available() is False

    def test_wrong_length_key(self, monkeypatch):
        """길이가 맞지 않는 키."""
        import base64
        wrong_key = base64.urlsafe_b64encode(b"short").decode("utf-8")
        monkeypatch.setenv("AGENT_CHANNEL_KEY", wrong_key)
        reset_for_tests()
        assert is_available() is False


class TestRealWorldScenarios:
    """실제 사용 사례."""

    def test_telegram_bot_config(self):
        """Telegram 봇 설정 암호화."""
        payload = {
            "kind": "telegram",
            "external_id": "123456789",
            "bot_token": "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
            "webhook_secret": "my-webhook-secret-xyz",
        }
        ciphertext = encrypt_dict(payload)
        decrypted = decrypt_dict(ciphertext)
        assert decrypted == payload

    def test_slack_webhook_config(self):
        """Slack webhook 설정 암호화."""
        payload = {
            "kind": "slack",
            "external_id": "workspace-id-123",
            "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXX",
            "signing_secret": "xxxxxxxxxxxxxxxxxxxx",
            "allowed_channels": ["#general", "#support"],
        }
        ciphertext = encrypt_dict(payload)
        decrypted = decrypt_dict(ciphertext)
        assert decrypted == payload

    def test_discord_bot_config(self):
        """Discord 봇 설정 암호화."""
        payload = {
            "kind": "discord",
            "external_id": "guild-id-123",
            "bot_token": "MTk4NjIyNDgzNDU3MjkyNzY4.Clwa7A.wulxz8rzplwqdKrwqXQK5g2g34Q",
            "intents": 32767,
            "prefix": "!",
        }
        ciphertext = encrypt_dict(payload)
        decrypted = decrypt_dict(ciphertext)
        assert decrypted == payload

    def test_key_rotation_safe(self):
        """키 회전 시나리오 — 메타데이터는 평문, secrets 는 암호."""
        channel_metadata = {
            "id": "ch-001",
            "kind": "telegram",
            "external_id": "123456789",
            "created_at": "2026-05-06T12:00:00Z",
        }
        config_secrets = {
            "bot_token": "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
            "webhook_secret": "secret-xyz",
        }

        # 설정만 암호화되고 메타는 평문 저장
        encrypted_config = encrypt_dict(config_secrets)

        # 복호화 시 원래대로 복원
        decrypted_config = decrypt_dict(encrypted_config)
        assert decrypted_config == config_secrets
        # 메타는 변경 안 됨
        assert channel_metadata["kind"] == "telegram"
