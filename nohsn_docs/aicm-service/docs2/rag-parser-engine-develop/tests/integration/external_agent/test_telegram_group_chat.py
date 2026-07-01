"""Phase 1.5A Task 8f — Telegram chat_id binding 회귀 테스트.

검증 시나리오:
1. private chat: from.id == chat.id — 그대로 동작 (회귀 X).
2. group chat: from.id != chat.id — 응답이 chat.id 로 발송 (mock send 가 캡처).
3. forum supergroup: message_thread_id 보존 + 응답 payload 에 포함.
4. (router-level) group chat default deny — group_enabled=false 면 응답 안 함.
   여기서는 adapter 단위까지만 검증 (router level 은 별도 통합 테스트).

InboundMessage 표준 필드:
- ``from_user_id`` = 실 user.id (audit + mapping binding key).
- ``chat_id`` = 응답 발송 대상 (sendMessage routing).
- ``chat_type`` = "private" | "group" | "supergroup" | "channel".
- ``message_thread_id`` = forum supergroup 토픽 ID.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.integration.external_agent.telegram_adapter import TelegramAdapter


@pytest.fixture
def adapter():
    return TelegramAdapter()


def _request(headers: dict | None = None, body: dict | None = None):
    req = MagicMock()
    req.headers = headers or {"X-Telegram-Bot-Api-Secret-Token": "s"}
    req.json = AsyncMock(return_value=body or {})
    return req


# ---------------------------------------------------------------------------
# 시나리오 1 — private chat: from.id == chat.id (기존 동작 회귀 보호)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_private_chat_routing_unchanged(adapter):
    """private DM — from.id == chat.id 케이스. 기존 1:1 시연 path 회귀 X."""
    req = _request(body={
        "update_id": 1,
        "message": {
            "from": {"id": 12345, "first_name": "Ricky"},
            "chat": {"id": 12345, "type": "private"},
            "text": "안녕",
        },
    })
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is not None
    assert res.message.from_user_id == "12345"  # 실 user.id
    assert res.message.chat_id == "12345"        # 응답 대상 (== from)
    assert res.message.chat_type == "private"
    assert res.message.message_thread_id is None


# ---------------------------------------------------------------------------
# 시나리오 2 — group chat: from.id != chat.id (Task 8f 핵심 결함)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_chat_separates_user_and_chat(adapter):
    """group — from_user_id 와 chat_id 분리.

    결함 (수정 전): from_user_id 가 chat.id 였거나 from.id 였거나 일관성 X.
    응답이 잘못된 chat 으로 가거나 발송 실패.

    수정 후: from_user_id = 실 user.id (5001) — audit/mapping 용.
            chat_id      = -100123 — 응답 발송 대상.
    """
    req = _request(body={
        "update_id": 2,
        "message": {
            "from": {"id": 5001, "first_name": "GroupUser"},
            "chat": {"id": -100123, "type": "group", "title": "Sales Team"},
            "text": "오늘 일정",
        },
    })
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is not None
    assert res.message.from_user_id == "5001"
    assert res.message.chat_id == "-100123"
    assert res.message.chat_type == "group"


@pytest.mark.asyncio
async def test_group_chat_send_outbound_uses_chat_id(adapter):
    """group — send_outbound 가 chat.id 로 sendMessage 발송."""
    captured: dict = {}

    async def fake_post(self, url, json):
        captured["url"] = url
        captured["payload"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        resp.json = lambda: {"ok": True}
        resp.headers = {}
        return resp

    # group chat_id 로 발송 (router 가 inbound.chat_id 전달하는 시뮬레이션).
    with patch("httpx.AsyncClient.post", new=fake_post):
        await adapter.send_outbound(
            {"bot_token": "T"}, "-100123", "응답 본문"
        )

    # chat_id 가 numeric 으로 변환되어 payload 에 들어감.
    assert captured["payload"]["chat_id"] == -100123
    # message_thread_id 는 미전달 → payload 에 없음.
    assert "message_thread_id" not in captured["payload"]


# ---------------------------------------------------------------------------
# 시나리오 3 — forum supergroup: message_thread_id 보존 + 응답 propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forum_topic_preserves_thread_id(adapter):
    """forum supergroup — message_thread_id 가 inbound 와 metadata 양쪽 보존."""
    req = _request(body={
        "update_id": 3,
        "message": {
            "from": {"id": 7001, "first_name": "TopicUser"},
            "chat": {"id": -1001234, "type": "supergroup", "is_forum": True},
            "text": "토픽 안의 질문",
            "message_thread_id": 42,
        },
    })
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is not None
    assert res.message.from_user_id == "7001"
    assert res.message.chat_id == "-1001234"
    assert res.message.chat_type == "supergroup"
    assert res.message.message_thread_id == 42
    # metadata 에도 보존 (legacy caller 호환).
    assert res.message.metadata["message_thread_id"] == 42


@pytest.mark.asyncio
async def test_forum_topic_send_outbound_includes_thread_id(adapter):
    """forum 응답 — sendMessage payload 에 message_thread_id 포함.

    누락 시 응답이 General 채널로 새서 사용자가 응답을 못 본다.
    """
    captured: dict = {}

    async def fake_post(self, url, json):
        captured["payload"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        resp.json = lambda: {"ok": True}
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        await adapter.send_outbound(
            {"bot_token": "T"}, "-1001234", "응답", message_thread_id=42
        )

    assert captured["payload"]["chat_id"] == -1001234
    assert captured["payload"]["message_thread_id"] == 42


# ---------------------------------------------------------------------------
# 시나리오 4 — channel post: from 부재 시 chat.id 로 fallback (안전 동작)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_post_from_missing_uses_chat_id_for_user(adapter):
    """channel post — message.from 없으면 from_user_id = chat.id (audit 식별 유지)."""
    req = _request(body={
        "update_id": 4,
        "message": {
            # from 없음 — 익명 channel post.
            "chat": {"id": -100555, "type": "channel"},
            "text": "공지",
        },
    })
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is not None
    # from 부재 → chat.id 로 fallback. chat_id 는 동일.
    assert res.message.from_user_id == "-100555"
    assert res.message.chat_id == "-100555"
    assert res.message.chat_type == "channel"
