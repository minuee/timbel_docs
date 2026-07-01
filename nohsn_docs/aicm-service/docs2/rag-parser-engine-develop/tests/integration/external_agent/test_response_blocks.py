"""Phase 1.5C — ResponseEnvelope 5종 블록 → Telegram 매핑 테스트.

Block 별 Telegram API 호출 시그니처 / payload 검증 + 호환성 (str → envelope
auto-wrap) + 빈 envelope no-op + stub 어댑터 NotImplementedError.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integration.external_agent.response_blocks import (
    ButtonBlock,
    CardBlock,
    CarouselBlock,
    ListCardBlock,
    ListItem,
    QuickReplyBlock,
    ResponseEnvelope,
    TextBlock,
)
from src.integration.external_agent.telegram_adapter import TelegramAdapter


# ---------------------------------------------------------------------------
# 헬퍼 — httpx.AsyncClient.post 패치 (sent calls 캡처)
# ---------------------------------------------------------------------------


class _SentCalls:
    """httpx mock 이 캡처한 호출 리스트.

    각 호출은 ``{"url", "json", "method"}`` dict.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def make_post(self):
        async def fake_post(_self, url, json):
            method = url.rsplit("/", 1)[-1]
            self.calls.append({"url": url, "json": json, "method": method})
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "ok"
            return resp

        return fake_post

    @property
    def methods(self) -> list[str]:
        return [c["method"] for c in self.calls]


@pytest.fixture
def adapter() -> TelegramAdapter:
    return TelegramAdapter()


@pytest.fixture
def captured() -> _SentCalls:
    return _SentCalls()


# ---------------------------------------------------------------------------
# 1) TextBlock — sendMessage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_block_sends_message(adapter, captured):
    envelope = ResponseEnvelope(blocks=[TextBlock(text="안녕하세요")])
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.methods == ["sendMessage"]
    payload = captured.calls[0]["json"]
    assert payload["chat_id"] == 12345
    assert payload["parse_mode"] == "MarkdownV2"
    # MarkdownV2 escape — 평범 한글은 그대로
    assert "안녕하세요" in payload["text"]


@pytest.mark.asyncio
async def test_text_block_markdown_passthrough(adapter, captured):
    """parse_mode='markdown' 은 호출자가 작성한 markdown 그대로 전달 (escape X)."""
    envelope = ResponseEnvelope(
        blocks=[TextBlock(text="*굵게* _기울임_", parse_mode="markdown")]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    payload = captured.calls[0]["json"]
    # markdown 모드는 백슬래시 이스케이프 없음
    assert payload["text"] == "*굵게* _기울임_"


# ---------------------------------------------------------------------------
# 2) CardBlock — sendPhoto + caption + InlineKeyboardMarkup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_card_block_with_image_sends_photo(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[
            CardBlock(
                title="신상품",
                description="새로 입고된 무선 이어폰",
                image_url="https://cdn.example.com/p1.jpg",
                buttons=[
                    ButtonBlock(label="자세히", action="url", payload="https://x.com/p"),
                    ButtonBlock(label="장바구니", action="postback", payload="add_p1"),
                ],
            )
        ]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.methods == ["sendPhoto"]
    payload = captured.calls[0]["json"]
    assert payload["photo"] == "https://cdn.example.com/p1.jpg"
    assert "신상품" in payload["caption"]
    assert "이어폰" in payload["caption"]
    assert payload["parse_mode"] == "MarkdownV2"

    rm = payload["reply_markup"]
    rows = rm["inline_keyboard"]
    assert len(rows) == 2
    # 첫 row = url 버튼
    assert rows[0][0]["text"] == "자세히"
    assert rows[0][0]["url"] == "https://x.com/p"
    # 둘째 row = postback 버튼
    assert rows[1][0]["text"] == "장바구니"
    assert rows[1][0]["callback_data"] == "add_p1"


@pytest.mark.asyncio
async def test_card_block_no_image_falls_back_to_message(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[CardBlock(title="공지", description="오늘은 정기 점검일")]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.methods == ["sendMessage"]


# ---------------------------------------------------------------------------
# 3) CarouselBlock — 카드 순차 발송 (Telegram native carousel 없음)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_carousel_block_sends_each_card_sequentially(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[
            CarouselBlock(
                cards=[
                    CardBlock(title=f"상품{i}", image_url=f"https://x/{i}.jpg")
                    for i in range(3)
                ]
            )
        ]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.methods == ["sendPhoto"] * 3


# ---------------------------------------------------------------------------
# 4) QuickReplyBlock — sendMessage + ReplyKeyboardMarkup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_reply_block_sets_reply_keyboard(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[
            QuickReplyBlock(
                text="어떤 메뉴를 보시겠어요?",
                options=["예약", "결제", "문의"],
            )
        ]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.methods == ["sendMessage"]
    rm = captured.calls[0]["json"]["reply_markup"]
    assert rm["one_time_keyboard"] is True
    assert rm["resize_keyboard"] is True
    # 각 옵션이 1열 row
    assert rm["keyboard"] == [[{"text": "예약"}], [{"text": "결제"}], [{"text": "문의"}]]


# ---------------------------------------------------------------------------
# 5) ListCardBlock — sendMessage + markdown list + InlineKeyboardMarkup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_card_block_renders_markdown_and_inline_keyboard(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[
            ListCardBlock(
                title="자주 묻는 질문",
                items=[
                    ListItem(text="환불 정책", callback="faq:refund"),
                    ListItem(
                        text="배송 기간",
                        description="2-3 영업일",
                        callback="faq:shipping",
                    ),
                    ListItem(text="고객센터 안내"),  # callback 없음
                ],
                buttons=[
                    ButtonBlock(label="홈으로", action="postback", payload="home"),
                ],
            )
        ]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.methods == ["sendMessage"]
    payload = captured.calls[0]["json"]
    text = payload["text"]
    # 제목 굵게 + 항목 dash
    assert "자주 묻는 질문" in text
    assert "환불 정책" in text
    assert "2\\-3 영업일" in text or "2-3 영업일" in text  # MarkdownV2 escape

    # inline keyboard = 항목 callback (2개) + footer button (1개)
    rm = payload["reply_markup"]
    rows = rm["inline_keyboard"]
    assert len(rows) == 3
    # 두 callback 항목은 callback_data 채워짐
    cbs = [r[0].get("callback_data") for r in rows]
    assert "faq:refund" in cbs
    assert "faq:shipping" in cbs
    assert "home" in cbs


# ---------------------------------------------------------------------------
# 6) 빈 ResponseEnvelope — no-op (HTTP 호출 없음)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_envelope_is_noop(adapter, captured):
    envelope = ResponseEnvelope(blocks=[])
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    assert captured.calls == []


# ---------------------------------------------------------------------------
# 7) 호환성 — str / text= 키워드 → ResponseEnvelope auto-wrap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_str_response_auto_wraps_to_text_block(adapter, captured):
    """기존 plain str 호출이 시연 path 와 동일 동작 (TextBlock 1개)."""
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", "hello")
    assert captured.methods == ["sendMessage"]
    assert "hello" in captured.calls[0]["json"]["text"]


@pytest.mark.asyncio
async def test_legacy_text_keyword_still_works(adapter, captured):
    """기존 ``text=`` 키워드 호출 (router 의 fallback path) 보존."""
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        # 빈 positional + text= 키워드
        await adapter.send_outbound(
            {"bot_token": "TK"}, "12345", text="legacy hello"
        )
    assert captured.methods == ["sendMessage"]
    assert "legacy hello" in captured.calls[0]["json"]["text"]


# ---------------------------------------------------------------------------
# 8) phone / share action → 본문 inline (inline keyboard 미지원)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phone_action_inlined_in_caption(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[
            CardBlock(
                title="고객센터",
                buttons=[
                    ButtonBlock(label="전화", action="phone", payload="010-1234-5678"),
                ],
            )
        ]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound({"bot_token": "TK"}, "12345", envelope)
    payload = captured.calls[0]["json"]
    # phone 은 inline keyboard X — 본문 텍스트 inline.
    assert "010" in payload["text"] or "010" in payload.get("caption", "")
    assert "reply_markup" not in payload  # phone 만 있으면 inline keyboard 비움


# ---------------------------------------------------------------------------
# 9) message_thread_id (forum supergroup) 보존
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_thread_id_propagates_to_each_block(adapter, captured):
    envelope = ResponseEnvelope(
        blocks=[
            TextBlock(text="hi"),
            CardBlock(title="x", description="y"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=captured.make_post()):
        await adapter.send_outbound(
            {"bot_token": "TK"}, "12345", envelope, message_thread_id=42
        )
    assert len(captured.calls) == 2
    for c in captured.calls:
        assert c["json"]["message_thread_id"] == 42


# ---------------------------------------------------------------------------
# 10) Stub 어댑터 — NotImplementedError raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_adapters_raise_not_implemented():
    from src.integration.external_agent.stub_adapters import (
        DiscordAdapter,
        KakaoTalkAdapter,
        LineAdapter,
        SlackAdapter,
    )

    for adapter_cls in (SlackAdapter, DiscordAdapter, LineAdapter, KakaoTalkAdapter):
        a = adapter_cls()
        with pytest.raises(NotImplementedError, match="not implemented yet"):
            await a.send_outbound({}, "x", "y")
