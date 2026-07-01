"""Telegram retry policy 회귀 테스트 (2026-05-07).

OOS-guard-and-telegram-retry-fix — _send_outbound_with_retry helper:
- transient (5xx / network / timeout) → 1s → 2s → 4s sleep 후 retry, 모두 실패시 raise.
- 429 → wrapper 재시도 X (어댑터가 이미 retry, 이중 retry 회피).
- permanent (chat_not_found / bot_blocked / token_revoked) → 즉시 fail (retry X).

retry helper 단독으로 검증 — channel_webhook 핸들러 통합은 별도 e2e 가 다룸.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.routers.external_agent_v1 import _send_outbound_with_retry
from src.integration.external_agent.telegram_adapter import TelegramSendError


@pytest.mark.asyncio
async def test_retry_first_attempt_success(monkeypatch):
    """첫 시도 성공 — sleep 0회, attempt=0 반환."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(return_value=None)
    sleep_calls: list[float] = []

    async def _fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    result = await _send_outbound_with_retry(
        adapter,
        config={"bot_token": "x"},
        to="123",
        text="hi",
    )
    assert result == 0
    assert sleep_calls == []
    assert adapter.send_outbound.await_count == 1


@pytest.mark.asyncio
async def test_retry_permanent_chat_not_found_immediate_fail(monkeypatch):
    """permanent (chat_not_found) → 즉시 raise, retry 0회."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 400: chat not found",
            status_code=400,
            retryable=False,
            permanent_reason="chat_not_found",
        )
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="99888001",  # 가짜 chat_id
            text="hi",
        )
    assert ei.value.permanent_reason == "chat_not_found"
    assert ei.value.retryable is False
    assert sleep_calls == [], "permanent fail 에서 sleep 발생하면 안 됨"
    assert adapter.send_outbound.await_count == 1


@pytest.mark.asyncio
async def test_retry_permanent_token_revoked_immediate_fail(monkeypatch):
    """permanent (token_revoked) → 즉시 raise."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 401: unauthorized",
            status_code=401,
            retryable=False,
            permanent_reason="token_revoked",
        )
    )

    async def _fake_sleep(s):
        pass

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="123",
            text="hi",
        )
    assert ei.value.permanent_reason == "token_revoked"
    assert adapter.send_outbound.await_count == 1


@pytest.mark.asyncio
async def test_retry_429_no_double_retry(monkeypatch):
    """429 → wrapper 재시도 X (어댑터가 이미 retry). 즉시 raise."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 429 retry_after=3",
            status_code=429,
            retryable=True,
        )
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="123",
            text="hi",
        )
    assert ei.value.status_code == 429
    assert sleep_calls == [], "429 면 wrapper 가 sleep 하면 안 됨 (어댑터 책임)"
    assert adapter.send_outbound.await_count == 1


@pytest.mark.asyncio
async def test_retry_transient_5xx_3_retries_then_fail(monkeypatch):
    """5xx → 1s/2s/4s 3회 retry 후 모두 실패시 raise."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 502", status_code=502, retryable=True,
        )
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="123",
            text="hi",
        )
    assert ei.value.status_code == 502
    assert adapter.send_outbound.await_count == 4, "1 + 3 retry = 4 시도"
    assert len(sleep_calls) == 3, "1s/2s/4s = 3회 sleep"
    # jitter ±0.25s 허용.
    assert 0.75 <= sleep_calls[0] <= 1.25
    assert 1.75 <= sleep_calls[1] <= 2.25
    assert 3.75 <= sleep_calls[2] <= 4.25


@pytest.mark.asyncio
async def test_retry_transient_network_then_success(monkeypatch):
    """network 실패 (status_code=null) 1회 → 2번째 시도 성공."""
    adapter = MagicMock()
    call_count = {"n": 0}

    async def _flaky_send(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TelegramSendError(
                "timeout", status_code=None, retryable=True,
            )
        return None

    adapter.send_outbound = _flaky_send
    sleep_calls: list[float] = []

    async def _fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    result = await _send_outbound_with_retry(
        adapter,
        config={"bot_token": "x"},
        to="123",
        text="hi",
    )
    assert result == 1, "1회 retry 후 (attempt=1) 성공"
    assert call_count["n"] == 2
    assert len(sleep_calls) == 1
    assert 0.75 <= sleep_calls[0] <= 1.25, "첫 retry 1s ± 0.25 jitter"


@pytest.mark.asyncio
async def test_retry_attempts_made_attached_to_exception(monkeypatch):
    """GPT-5 P1 — exception.attempts_made 에 실제 시도 횟수가 부착돼야 한다."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 502", status_code=502, retryable=True,
        )
    )

    async def _fake_sleep(s):
        pass

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="123",
            text="hi",
        )
    # 4번째 시도 (attempt=3, 1-indexed=4) 후 실패 — attempts_made=4.
    assert getattr(ei.value, "attempts_made", None) == 4


@pytest.mark.asyncio
async def test_retry_429_attempts_made_is_1(monkeypatch):
    """GPT-5 P1 — 429 즉시 raise 시 attempts_made=1 (wrapper 가 retry X)."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 429 retry_after=3",
            status_code=429,
            retryable=True,
        )
    )

    async def _fake_sleep(s):
        pass

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="123",
            text="hi",
        )
    assert getattr(ei.value, "attempts_made", None) == 1


@pytest.mark.asyncio
async def test_retry_permanent_attempts_made_is_1(monkeypatch):
    """GPT-5 P1 — permanent fail 즉시 attempts_made=1."""
    adapter = MagicMock()
    adapter.send_outbound = AsyncMock(
        side_effect=TelegramSendError(
            "HTTP 400: chat not found",
            status_code=400,
            retryable=False,
            permanent_reason="chat_not_found",
        )
    )

    async def _fake_sleep(s):
        pass

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    with pytest.raises(TelegramSendError) as ei:
        await _send_outbound_with_retry(
            adapter,
            config={"bot_token": "x"},
            to="99888001",
            text="hi",
        )
    assert getattr(ei.value, "attempts_made", None) == 1


@pytest.mark.asyncio
async def test_retry_legacy_typeerror_fallback(monkeypatch):
    """어댑터가 message_thread_id / response 키워드 미지원 → legacy 호출."""
    adapter = MagicMock()
    legacy_called = {"n": 0}

    async def _legacy_send(*args, **kwargs):
        # 신 시그니처 (message_thread_id) 면 TypeError, 평문 (text=) 면 성공.
        if "message_thread_id" in kwargs or "response" in kwargs:
            raise TypeError("legacy adapter")
        legacy_called["n"] += 1
        return None

    adapter.send_outbound = _legacy_send

    async def _fake_sleep(s):
        pass

    monkeypatch.setattr(
        "src.api.routers.external_agent_v1.asyncio.sleep", _fake_sleep
    )

    result = await _send_outbound_with_retry(
        adapter,
        config={"bot_token": "x"},
        to="123",
        response={"some": "envelope"},
        text="hi",
        message_thread_id=42,
    )
    assert result == 0
    assert legacy_called["n"] == 1, "legacy fallback 한 번 호출"
