"""외부 채널 webhook 라우터 단위 테스트 (mock-based).

Phase 1 Task 6 — /api/v1/external-agent/{kind}/{external_id}/webhook.

DB / 실제 Telegram 없이 실행 가능. 모든 외부 의존은 unittest.mock 으로 대체.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CHANNEL_KIND = "telegram"
EXTERNAL_ID = "bot123456789"
AGENT_ID = uuid4()
CHANNEL_ID = uuid4()


def _mock_agent(is_active: bool = True):
    from src.core.models.agent import Agent

    a = MagicMock(spec=Agent)
    a.id = AGENT_ID
    a.tenant_id = uuid4()
    a.name = "Test Agent"
    a.goal = "help users"
    a.guidelines_md = "be helpful"
    a.primary_repo_ids = []
    a.fallback_repo_ids = []
    a.knowledge_isolation = "priority"
    a.allowed_tools = []
    a.done_when = None
    a.is_active = is_active
    return a


def _mock_channel(is_active: bool = True):
    from src.core.models.agent import AgentChannel

    c = MagicMock(spec=AgentChannel)
    c.id = CHANNEL_ID
    c.kind = CHANNEL_KIND
    c.external_id = EXTERNAL_ID
    c.agent_id = AGENT_ID
    c.is_active = is_active
    c.config_encrypted = b"dummy_ciphertext"
    return c


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper — patch 경로 상수
# ---------------------------------------------------------------------------

_WH_PATH = "src.api.routers.external_agent_v1"
_CHAT_PATH = "src.api.routers.chat_v1"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_webhook_unsupported_kind(client):
    """지원하지 않는 채널 kind → 400."""
    resp = client.post("/api/v1/external-agent/fax/1234/webhook", json={})
    assert resp.status_code == 400
    assert "unsupported" in resp.text.lower()


def test_webhook_channel_not_found(client):
    """channel 없음 → 204 (Telegram 재시도 방지)."""
    with (
        patch("src.integration.external_agent.registry.get_adapter", return_value=MagicMock()),
        patch("src.common.crypto.fernet.decrypt_dict", return_value={}),
        patch(
            f"{_WH_PATH}.AsyncSession",
        ) as mock_sess_cls,
    ):
        # DB 조회 → None
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_sess_cls.return_value = mock_db

        resp = client.post(f"/api/v1/external-agent/{CHANNEL_KIND}/{EXTERNAL_ID}/webhook", json={})
    # 채널 없으면 204 (내부에서 early return)
    assert resp.status_code == 204


def test_webhook_decrypt_failure_returns_204(client):
    """config decrypt 실패 → 204 (재시도 무의미)."""
    mock_channel = _mock_channel()

    async def _raise(*a, **kw):
        raise ValueError("bad ciphertext")

    with (
        patch("src.integration.external_agent.registry.get_adapter", return_value=MagicMock()),
        patch(f"{_WH_PATH}.AsyncSession") as mock_sess_cls,
        patch("src.common.crypto.fernet.decrypt_dict", side_effect=ValueError("bad")),
    ):
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=mock_channel)
            )
        )
        mock_sess_cls.return_value = mock_db

        resp = client.post(
            f"/api/v1/external-agent/{CHANNEL_KIND}/{EXTERNAL_ID}/webhook", json={}
        )
    assert resp.status_code == 204


def test_webhook_parse_inbound_none_returns_204(client):
    """parse_inbound 가 None (서명 실패 / 비-메시지) → 204."""
    mock_channel = _mock_channel()
    mock_adapter = MagicMock()
    mock_adapter.parse_inbound = AsyncMock(return_value=None)

    with (
        patch("src.integration.external_agent.registry.get_adapter", return_value=mock_adapter),
        patch("src.common.crypto.fernet.decrypt_dict", return_value={"webhook_secret": "sec"}),
        patch(f"{_WH_PATH}.AsyncSession") as mock_sess_cls,
    ):
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=mock_channel)
            )
        )
        mock_db.begin = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_db), __aexit__=AsyncMock(return_value=False)))
        mock_db.flush = AsyncMock()
        mock_sess_cls.return_value = mock_db

        resp = client.post(
            f"/api/v1/external-agent/{CHANNEL_KIND}/{EXTERNAL_ID}/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"message": {"text": "hi", "chat": {}, "from": {}}},
        )
    assert resp.status_code == 204


def test_webhook_happy_path_calls_send_outbound(client):
    """정상 흐름 → 204 + adapter.send_outbound 호출."""
    from src.integration.external_agent.base import InboundMessage

    mock_channel = _mock_channel()
    mock_agent = _mock_agent()

    mock_adapter = MagicMock()
    inbound = InboundMessage(
        from_user_id="111222333",
        from_user_name="Tester",
        text="안녕",
        metadata={"chat_id": 111222333},
    )
    mock_adapter.parse_inbound = AsyncMock(return_value=inbound)
    mock_adapter.collect_response = AsyncMock(return_value=("응답 텍스트", []))
    mock_adapter.send_outbound = AsyncMock(return_value=None)

    async def _fake_handle(**kwargs):
        # yield 한 개 — collect_response 가 소비함
        if False:  # pragma: no cover
            yield {}

    with (
        patch("src.integration.external_agent.registry.get_adapter", return_value=mock_adapter),
        patch("src.common.crypto.fernet.decrypt_dict", return_value={"bot_token": "tok", "webhook_secret": "sec"}),
        patch(f"{_WH_PATH}.AsyncSession") as mock_sess_cls,
        patch(f"{_WH_PATH}._wh_get_agent", new=AsyncMock(return_value=mock_agent)),
        patch("src.api.routers.chat_v1._handle_external_agent_message", new=_fake_handle),
        patch(f"{_WH_PATH}._wh_upsert_user_mapping", new=AsyncMock(return_value=MagicMock(internal_user_id=None))),
    ):
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=mock_channel)
            )
        )
        mock_db.begin = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_db),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_db.flush = AsyncMock()
        mock_sess_cls.return_value = mock_db

        resp = client.post(
            f"/api/v1/external-agent/{CHANNEL_KIND}/{EXTERNAL_ID}/webhook",
            json={},
        )

    assert resp.status_code == 204
    mock_adapter.send_outbound.assert_awaited_once()


def test_webhook_inactive_agent_returns_204(client):
    """비활성 agent → 204 (silent drop)."""
    from src.integration.external_agent.base import InboundMessage

    mock_channel = _mock_channel()
    mock_agent = _mock_agent(is_active=False)

    mock_adapter = MagicMock()
    inbound = InboundMessage(
        from_user_id="111",
        from_user_name="U",
        text="hello",
        metadata={},
    )
    mock_adapter.parse_inbound = AsyncMock(return_value=inbound)
    mock_adapter.send_outbound = AsyncMock()

    with (
        patch("src.integration.external_agent.registry.get_adapter", return_value=mock_adapter),
        patch("src.common.crypto.fernet.decrypt_dict", return_value={"webhook_secret": "s"}),
        patch(f"{_WH_PATH}.AsyncSession") as mock_sess_cls,
        patch(f"{_WH_PATH}._wh_upsert_user_mapping", new=AsyncMock(return_value=MagicMock())),
        patch(f"{_WH_PATH}._wh_get_agent", new=AsyncMock(return_value=mock_agent)),
    ):
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=mock_channel)
            )
        )
        mock_db.begin = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_db),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_db.flush = AsyncMock()
        mock_sess_cls.return_value = mock_db

        resp = client.post(
            f"/api/v1/external-agent/{CHANNEL_KIND}/{EXTERNAL_ID}/webhook",
            json={},
        )

    assert resp.status_code == 204
    mock_adapter.send_outbound.assert_not_awaited()
