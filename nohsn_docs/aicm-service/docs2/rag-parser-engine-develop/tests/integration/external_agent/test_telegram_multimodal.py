"""Telegram adapter multimodal block 발송 테스트 — KMS-Plus 2026-05-07.

ImageBlock / TableBlock / LinkBlock / AlertBlock 이 native 매핑으로
sendPhoto / sendMessage 로 변환되는지 검증. _send_request 를 mock 해
실제 Telegram 호출 없이 payload 만 캡처.

사용자 절칙: "표나 그림 등의 자료를 답변과 함께 첨부 — 풀옵션".
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.integration.external_agent.response_blocks import (
    AlertBlock,
    ImageBlock,
    LinkBlock,
    ResponseEnvelope,
    TableBlock,
)
from src.integration.external_agent.telegram_adapter import TelegramAdapter


@pytest.fixture
def adapter():
    return TelegramAdapter()


@pytest.fixture
def captured(adapter, monkeypatch):
    """_send_request 호출 캡처. (method, payload) tuple list 반환."""
    calls: list[tuple[str, dict]] = []

    async def fake_send(self, bot_token, method, payload):
        calls.append((method, payload))

    monkeypatch.setattr(TelegramAdapter, "_send_request", fake_send)
    return calls


@pytest.mark.asyncio
async def test_image_block_sends_photo(adapter, captured):
    env = ResponseEnvelope(
        blocks=[ImageBlock(image_url="https://x.com/img.png", caption="설명")]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 1
    method, payload = captured[0]
    assert method == "sendPhoto"
    assert payload["photo"] == "https://x.com/img.png"
    assert payload["chat_id"] == 12345
    assert "caption" in payload


@pytest.mark.asyncio
async def test_image_block_no_url_fallback_text(adapter, captured):
    """image_url 비어 있으면 caption 텍스트로 fallback (raise X)."""
    env = ResponseEnvelope(
        blocks=[ImageBlock(image_url="", caption="이미지 누락 안내")]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 1
    method, payload = captured[0]
    assert method == "sendMessage"
    assert "이미지 누락 안내" in payload["text"]


@pytest.mark.asyncio
async def test_table_block_sends_markdown_pre_block(adapter, captured):
    """GPT-5 P1-1 fix — HTML <pre> mode (MarkdownV2 backslash escape 결함 회피)."""
    md = "| 항목 | 금액 |\n| --- | --- |\n| A | 100 |"
    env = ResponseEnvelope(
        blocks=[TableBlock(title="단가표", markdown=md)]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 1
    method, payload = captured[0]
    assert method == "sendMessage"
    # HTML pre block — <pre>...</pre> 안에 표 본문.
    assert payload["parse_mode"] == "HTML"
    assert "<pre>" in payload["text"] and "</pre>" in payload["text"]
    assert "| A | 100 |" in payload["text"]
    # 제목은 <b>...</b>.
    assert "<b>단가표</b>" in payload["text"]


@pytest.mark.asyncio
async def test_table_block_headers_rows_builds_markdown(adapter, captured):
    """markdown 미설정 + headers/rows → adapter 가 markdown 빌드."""
    env = ResponseEnvelope(
        blocks=[TableBlock(headers=["a", "b"], rows=[["1", "2"], ["3", "4"]])]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 1
    _, payload = captured[0]
    text = payload["text"]
    assert "| a | b |" in text
    assert "| 1 | 2 |" in text
    assert "| 3 | 4 |" in text


@pytest.mark.asyncio
async def test_link_block_sends_inline_url_button(adapter, captured):
    env = ResponseEnvelope(
        blocks=[LinkBlock(url="https://x.com/page", title="공식 안내", description="자세히")]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 1
    _, payload = captured[0]
    assert "공식 안내" in payload["text"]
    rm = payload.get("reply_markup")
    assert rm and "inline_keyboard" in rm
    assert rm["inline_keyboard"][0][0]["url"] == "https://x.com/page"


@pytest.mark.asyncio
async def test_alert_block_warning_prefix(adapter, captured):
    env = ResponseEnvelope(
        blocks=[AlertBlock(text="중요 안내", level="warning", title="주의")]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 1
    _, payload = captured[0]
    text = payload["text"]
    # level prefix [주의] (escape 된 형태 — \[주의\] 또는 [주의]).
    assert "주의" in text
    assert "중요 안내" in text


@pytest.mark.asyncio
async def test_mixed_envelope_sends_in_order(adapter, captured):
    """Text + Image + Table 순서로 발송. 순서 보존 검증."""
    from src.integration.external_agent.response_blocks import TextBlock
    env = ResponseEnvelope(
        blocks=[
            TextBlock(text="요약입니다."),
            ImageBlock(image_url="https://x.com/a.png"),
            TableBlock(markdown="| a | b |\n|---|---|\n| 1 | 2 |"),
        ]
    )
    await adapter.send_outbound(
        config={"bot_token": "test"}, to="12345", response=env
    )
    assert len(captured) == 3
    methods = [c[0] for c in captured]
    assert methods == ["sendMessage", "sendPhoto", "sendMessage"]
