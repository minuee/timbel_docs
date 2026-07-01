"""webhook flow account_id_hint 주입 회귀 가드.

증상:
    텔레그램 webhook 에서 admin agent (Locus) 가 mail.send 호출 →
    "account_id required (engine 자동 주입 미설정)" 실패.

뿌리:
    chat_v1._handle_external_agent_message 가 engine.turn 호출 시
    ``account_id_hint`` 를 전달하지 않아, mapping.internal_account_id
    가 set 인 admin 사용자 케이스에서도 sess.account_id 가 None
    으로 남았다. mail.send / diary / expense 등 user-scoped 도구가
    args["account_id"] 를 자동 주입 받지 못해 즉시 fail.

수정:
    external_agent_v1.channel_webhook → _handle_external_agent_message
    호출 시 ``account_id_hint=str(internal_account_id) if ... else None``
    전달. _handle_external_agent_message 는 이를 그대로 engine.turn 에
    forward.

본 테스트:
    LLM/Redis/DB 미의존 — engine 을 MagicMock 으로 대체해
    ``engine.turn`` 의 ``account_id_hint`` kwarg 만 검증한다.
    (mapping set → 그 값 전달 / mapping NULL → None 전달)
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.api.routers.chat_v1 import _handle_external_agent_message


class _StubEngine:
    """engine.turn 만 흉내 — kwargs 캡처 후 빈 stream 반환."""

    def __init__(self) -> None:
        self.last_call_kwargs: dict[str, Any] | None = None
        self.last_call_args: tuple[Any, ...] | None = None

    def turn(self, *args, **kwargs):  # noqa: ANN001
        self.last_call_args = args
        self.last_call_kwargs = kwargs

        async def _empty():
            if False:  # pragma: no cover
                yield {}

        return _empty()


class _StubAgentContext:
    """to_prompt_section 만 구현."""

    def to_prompt_section(self) -> str:
        return ""


@pytest.mark.asyncio
async def test_handle_external_agent_message_forwards_account_id_hint(monkeypatch):
    """internal_account_id 가 set → engine.turn 에 account_id_hint 그 값 전달."""
    # _ensure_channel_session / _insert_chat_message_user / _insert_chat_message_assistant
    # 는 DB 의존이라 NOOP 으로 stub.
    fake_chat_sid = uuid4()
    monkeypatch.setattr(
        "src.api.routers.chat_v1._ensure_channel_session",
        AsyncMock(return_value=fake_chat_sid),
    )
    monkeypatch.setattr(
        "src.api.routers.chat_v1._insert_chat_message_user",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.api.routers.chat_v1._insert_chat_message_assistant",
        AsyncMock(return_value=None),
    )

    engine = _StubEngine()
    tenant_id = uuid4()
    account_id = uuid4()
    channel_id = uuid4()
    agent_id = uuid4()

    stream = _handle_external_agent_message(
        text="메일 보내줘",
        agent_context=_StubAgentContext(),
        tenant_id=tenant_id,
        session_id="wh-test-1",
        engine=engine,
        internal_account_id=account_id,
        channel_kind="telegram",
        channel_id=channel_id,
        external_user_id="tg-12345",
        agent_id=agent_id,
        sender=None,
        account_id_hint=str(account_id),
    )

    async for _ in stream:
        pass

    assert engine.last_call_kwargs is not None
    assert engine.last_call_kwargs.get("account_id_hint") == str(account_id), (
        "engine.turn 호출 시 account_id_hint 가 mapping.internal_account_id 값으로 전달돼야 함"
    )


@pytest.mark.asyncio
async def test_handle_external_agent_message_guest_passes_none(monkeypatch):
    """internal_account_id 가 None (guest mapping) → account_id_hint=None 전달.

    guest tier 는 accounts 행이 없으므로 hint 도 None — mail.send 등은
    "계정 정보 설정 미비" 로 적절히 응답해야 한다 (보안: 권한 누설 방지).
    """
    # internal_account_id None 이면 _ensure_channel_session/INSERT 미호출이지만
    # 안전하게 stub.
    monkeypatch.setattr(
        "src.api.routers.chat_v1._ensure_channel_session",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "src.api.routers.chat_v1._insert_chat_message_user",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.api.routers.chat_v1._insert_chat_message_assistant",
        AsyncMock(return_value=None),
    )

    engine = _StubEngine()
    tenant_id = uuid4()

    stream = _handle_external_agent_message(
        text="hi",
        agent_context=_StubAgentContext(),
        tenant_id=tenant_id,
        session_id="wh-test-2",
        engine=engine,
        internal_account_id=None,
        channel_kind="telegram",
        channel_id=uuid4(),
        external_user_id="tg-99999",
        agent_id=uuid4(),
        sender=None,
        account_id_hint=None,
    )

    async for _ in stream:
        pass

    assert engine.last_call_kwargs is not None
    assert engine.last_call_kwargs.get("account_id_hint") is None, (
        "guest mapping (internal_account_id=NULL) 은 account_id_hint=None 이어야 함"
    )


@pytest.mark.asyncio
async def test_handle_external_agent_message_default_account_id_hint_none(monkeypatch):
    """account_id_hint kwarg 미전달 → None default (후방호환)."""
    monkeypatch.setattr(
        "src.api.routers.chat_v1._ensure_channel_session",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "src.api.routers.chat_v1._insert_chat_message_user",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.api.routers.chat_v1._insert_chat_message_assistant",
        AsyncMock(return_value=None),
    )

    engine = _StubEngine()

    stream = _handle_external_agent_message(
        text="hi",
        agent_context=_StubAgentContext(),
        tenant_id=uuid4(),
        session_id="wh-test-3",
        engine=engine,
        # internal_account_id / channel_* 도 미전달 — 모두 default.
    )

    async for _ in stream:
        pass

    assert engine.last_call_kwargs is not None
    assert "account_id_hint" in engine.last_call_kwargs, (
        "_handle_external_agent_message 는 항상 account_id_hint kwarg 를 forward 해야 함"
    )
    assert engine.last_call_kwargs.get("account_id_hint") is None
