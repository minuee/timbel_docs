"""Telegram webhook 보안 보강 회귀 가드 — Phase 1 (idempotency).

covers:
- update_id → InboundMessage.idempotency_key 추출 (parse_inbound).
- update_id 미포함 시 None 안전.
- send_outbound 에러 코드 분류 (429 / 401 / 403 / 400 / 5xx).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.integration.external_agent.telegram_adapter import (
    TelegramAdapter, TelegramSendError,
)


@pytest.fixture
def adapter():
    return TelegramAdapter()


@pytest.mark.asyncio
async def test_parse_inbound_idempotency_key_extracted(adapter):
    """정상 텍스트 메시지 — update_id 가 idempotency_key 로 보존."""
    req = MagicMock()
    req.headers = {"X-Telegram-Bot-Api-Secret-Token": "s"}
    req.json = AsyncMock(return_value={
        "update_id": 4242,
        "message": {
            "from": {"id": 99, "first_name": "U"},
            "chat": {"id": 99},
            "text": "hi",
            "message_id": 1,
        },
    })
    inbound = await adapter.parse_inbound(req, {"webhook_secret": "s"})
    assert inbound is not None
    assert inbound.idempotency_key == "4242"


@pytest.mark.asyncio
async def test_parse_inbound_idempotency_key_absent_safe(adapter):
    """update_id 가 누락된 비정상 payload — idempotency_key None 안전."""
    req = MagicMock()
    req.headers = {"X-Telegram-Bot-Api-Secret-Token": "s"}
    req.json = AsyncMock(return_value={
        "message": {
            "from": {"id": 1}, "chat": {"id": 1},
            "text": "ok",
        },
    })
    inbound = await adapter.parse_inbound(req, {"webhook_secret": "s"})
    assert inbound is not None
    assert inbound.idempotency_key is None


# --------------------------------------------------------------------------
# send_outbound — 에러 코드 분류
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_outbound_429_retry_after_then_succeed(adapter):
    """429 → retry_after sleep → 재시도 → 200 succeed (raise 없음)."""
    call_count = {"n": 0}

    async def fake_post(self, url, json):
        call_count["n"] += 1
        resp = MagicMock()
        if call_count["n"] == 1:
            resp.status_code = 429
            resp.text = '{"ok":false,"parameters":{"retry_after":1}}'
            resp.json = lambda: {"ok": False, "parameters": {"retry_after": 1}}
            resp.headers = {}
        else:
            resp.status_code = 200
            resp.text = "ok"
            resp.json = lambda: {"ok": True}
            resp.headers = {}
        return resp

    sleep_calls = []

    async def fake_sleep(secs):
        sleep_calls.append(secs)

    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "asyncio.sleep", new=fake_sleep
    ):
        await adapter.send_outbound({"bot_token": "T"}, "1", "hi")

    assert call_count["n"] == 2
    assert sleep_calls == [1]


@pytest.mark.asyncio
async def test_send_outbound_429_exhausts_retries(adapter):
    """429 가 끝까지 → TelegramSendError(429, retryable=True) raise."""
    call_count = {"n": 0}

    async def fake_post(self, url, json):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 429
        resp.text = '{"ok":false,"parameters":{"retry_after":1}}'
        resp.json = lambda: {"ok": False, "parameters": {"retry_after": 1}}
        resp.headers = {}
        return resp

    async def fake_sleep(secs):
        pass

    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "asyncio.sleep", new=fake_sleep
    ):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send_outbound({"bot_token": "T"}, "1", "hi")

    assert exc_info.value.status_code == 429
    assert exc_info.value.retryable is True
    # 최초 1회 + retry 3회 = 4 attempts
    assert call_count["n"] == 4


@pytest.mark.asyncio
async def test_send_outbound_401_token_revoked_permanent(adapter):
    async def fake_post(self, url, json):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = '{"ok":false,"description":"Unauthorized"}'
        resp.json = lambda: {"ok": False, "description": "Unauthorized"}
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send_outbound({"bot_token": "T"}, "1", "hi")

    assert exc_info.value.status_code == 401
    assert exc_info.value.retryable is False
    assert exc_info.value.permanent_reason == "token_revoked"


@pytest.mark.asyncio
async def test_send_outbound_403_bot_blocked_permanent(adapter):
    async def fake_post(self, url, json):
        resp = MagicMock()
        resp.status_code = 403
        resp.text = '{"ok":false,"description":"Forbidden: bot was blocked by the user"}'
        resp.json = lambda: {
            "ok": False, "description": "Forbidden: bot was blocked by the user"
        }
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send_outbound({"bot_token": "T"}, "1", "hi")

    assert exc_info.value.status_code == 403
    assert exc_info.value.retryable is False
    assert exc_info.value.permanent_reason == "bot_blocked"


@pytest.mark.asyncio
async def test_send_outbound_403_kicked_permanent(adapter):
    async def fake_post(self, url, json):
        resp = MagicMock()
        resp.status_code = 403
        resp.text = '{"ok":false,"description":"Forbidden: bot was kicked from the supergroup chat"}'
        resp.json = lambda: {
            "ok": False, "description": "Forbidden: bot was kicked from the supergroup chat"
        }
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send_outbound({"bot_token": "T"}, "-100", "hi")

    assert exc_info.value.permanent_reason == "bot_kicked"


@pytest.mark.asyncio
async def test_send_outbound_500_transient_retryable(adapter):
    async def fake_post(self, url, json):
        resp = MagicMock()
        resp.status_code = 502
        resp.text = "Bad Gateway"
        resp.json = lambda: {}
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send_outbound({"bot_token": "T"}, "1", "hi")

    assert exc_info.value.status_code == 502
    assert exc_info.value.retryable is True
    assert exc_info.value.permanent_reason is None


@pytest.mark.asyncio
async def test_send_outbound_400_chat_not_found_permanent(adapter):
    async def fake_post(self, url, json):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = '{"ok":false,"description":"Bad Request: chat not found"}'
        resp.json = lambda: {
            "ok": False, "description": "Bad Request: chat not found"
        }
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send_outbound({"bot_token": "T"}, "1", "hi")

    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False
    assert exc_info.value.permanent_reason == "chat_not_found"


# --------------------------------------------------------------------------
# get_me / get_webhook_info — 운영 도구
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_success(adapter):
    async def fake_get(self, url):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        resp.json = lambda: {
            "ok": True, "result": {"id": 12345, "is_bot": True, "username": "mybot"}
        }
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        me = await adapter.get_me("TOKEN")

    assert me["id"] == 12345
    assert me["is_bot"] is True


@pytest.mark.asyncio
async def test_get_me_401_token_revoked(adapter):
    async def fake_get(self, url):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        resp.json = lambda: {"ok": False, "description": "Unauthorized"}
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.get_me("BAD")

    assert exc_info.value.status_code == 401
    assert exc_info.value.permanent_reason == "token_revoked"


@pytest.mark.asyncio
async def test_get_webhook_info_success(adapter):
    async def fake_get(self, url):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        resp.json = lambda: {
            "ok": True, "result": {
                "url": "https://api.example.com/wh",
                "pending_update_count": 5,
                "last_error_date": 0,
            },
        }
        resp.headers = {}
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        info = await adapter.get_webhook_info("TOKEN")

    assert info["pending_update_count"] == 5
    assert info["url"] == "https://api.example.com/wh"


# --------------------------------------------------------------------------
# parse_inbound_v2 — ParseInboundError 분류 + group routing + thread_id
# --------------------------------------------------------------------------


from src.integration.external_agent.base import (
    ParseInboundError as _PE, ParseInboundResult,
)


def _make_request(*, headers=None, body=None, body_raises=False):
    req = MagicMock()
    req.headers = headers or {}
    if body_raises:
        req.json = AsyncMock(side_effect=ValueError("invalid json"))
    else:
        req.json = AsyncMock(return_value=body)
    return req


@pytest.mark.asyncio
async def test_parse_inbound_v2_secret_missing(adapter):
    req = _make_request(headers={"X-Telegram-Bot-Api-Secret-Token": "x"}, body={})
    res = await adapter.parse_inbound_v2(req, {})  # webhook_secret 키 없음
    assert isinstance(res, ParseInboundResult)
    assert res.message is None
    assert res.error == _PE.SECRET_MISSING


@pytest.mark.asyncio
async def test_parse_inbound_v2_signature_failure(adapter):
    req = _make_request(
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        body={"message": {"text": "hi"}},
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "right"})
    assert res.message is None
    assert res.error == _PE.SIGNATURE_FAILURE


@pytest.mark.asyncio
async def test_parse_inbound_v2_payload_invalid(adapter):
    req = _make_request(
        headers={"X-Telegram-Bot-Api-Secret-Token": "s"}, body_raises=True
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is None
    assert res.error == _PE.PAYLOAD_INVALID


@pytest.mark.asyncio
async def test_parse_inbound_v2_body_too_large(adapter):
    req = _make_request(
        headers={
            "X-Telegram-Bot-Api-Secret-Token": "s",
            "content-length": str(2 * 1024 * 1024),
        },
        body={},
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.error == _PE.BODY_TOO_LARGE


@pytest.mark.asyncio
async def test_parse_inbound_v2_healthcheck_only(adapter):
    """my_chat_member / edited_message 같은 ack-only 이벤트."""
    req = _make_request(
        headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
        body={
            "update_id": 100,
            "my_chat_member": {"chat": {"id": 1, "type": "private"}},
        },
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.error == _PE.HEALTHCHECK_ONLY
    assert res.event_label and "my_chat_member" in res.event_label


@pytest.mark.asyncio
async def test_parse_inbound_v2_unsupported_event_photo(adapter):
    """photo 메시지 — UNSUPPORTED_EVENT 분류."""
    req = _make_request(
        headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
        body={
            "update_id": 100,
            "message": {
                "from": {"id": 1}, "chat": {"id": 1, "type": "private"},
                "photo": [{}],
            },
        },
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.error == _PE.UNSUPPORTED_EVENT
    assert "photo" in (res.event_label or "")


@pytest.mark.asyncio
async def test_parse_inbound_v2_group_uses_chat_id(adapter):
    """group 채팅 — chat_id 와 from_user_id 분리 (Task 8f).

    from_user_id = 실 user.id (5001) — audit / mapping binding.
    chat_id      = -100123 — 응답 발송 대상 (sendMessage 가 *반드시* 이 chat).
    """
    req = _make_request(
        headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
        body={
            "update_id": 1,
            "message": {
                "from": {"id": 5001, "first_name": "GroupUser"},
                "chat": {"id": -100123, "type": "group"},
                "text": "안녕",
            },
        },
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is not None
    # from_user_id = 실 user.id — group 에서도 user 단위 audit / mapping.
    assert res.message.from_user_id == "5001"
    # chat_id = 응답 발송 대상 (sendMessage routing) — chat.id.
    assert res.message.chat_id == "-100123"
    assert res.message.chat_type == "group"
    assert res.message.metadata["from_id"] == 5001


@pytest.mark.asyncio
async def test_parse_inbound_v2_supergroup_forum_thread_id(adapter):
    """forum supergroup — message_thread_id 보존 (dataclass field + metadata)."""
    req = _make_request(
        headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
        body={
            "update_id": 1,
            "message": {
                "from": {"id": 1}, "chat": {"id": -1009, "type": "supergroup"},
                "text": "topic msg",
                "message_thread_id": 7,
            },
        },
    )
    res = await adapter.parse_inbound_v2(req, {"webhook_secret": "s"})
    assert res.message is not None
    assert res.message.message_thread_id == 7
    assert res.message.metadata["message_thread_id"] == 7
    assert res.message.chat_id == "-1009"
    assert res.message.chat_type == "supergroup"


@pytest.mark.asyncio
async def test_send_outbound_message_thread_id_propagated(adapter):
    """forum supergroup 응답 — message_thread_id 가 payload 에 포함."""
    captured = {}

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
            {"bot_token": "T"}, "-100", "hi", message_thread_id=7
        )

    assert captured["payload"]["message_thread_id"] == 7
