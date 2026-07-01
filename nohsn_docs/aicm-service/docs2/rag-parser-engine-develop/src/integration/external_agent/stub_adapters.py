"""Slack / Discord / Line / KakaoTalk 채널 어댑터 stub.

Phase 1.5C — TelegramAdapter 가 ResponseEnvelope 표준의 첫 reference. 다른
채널 어댑터는 후속 PR 에서 구현 예정. registry 가 ``unsupported channel kind``
400 으로 fallback 하지 않고 *명시적으로* "후속 PR" 임을 알리도록 stub 클래스를
제공.

호출 시 ``NotImplementedError`` raise — 등록된 채널은 ``registry.py`` 에서
주석 처리되어 있어 실제로는 trigger 되지 않지만, 디버깅 / 채널 카탈로그 UI 가
참조하도록 ``kind`` 와 docstring 만 보존.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Union

from fastapi import Request

from src.integration.external_agent.base import (
    InboundMessage,
    ParseInboundResult,
)
from src.integration.external_agent.response_blocks import ResponseEnvelope


class _NotImplementedAdapter:
    """후속 PR 에서 구현 예정인 채널 어댑터의 공통 base.

    네 메서드 모두 ``NotImplementedError`` raise — 우연히 등록되어 호출되어도
    명확한 에러로 감지. 운영에서는 ``registry.py`` 에 등록 *전* 까지 호출되지
    않는다.
    """

    kind: str = "<unset>"

    async def parse_inbound(
        self, request: Request, config: dict[str, Any]
    ) -> InboundMessage | None:
        raise NotImplementedError(
            f"{self.kind} adapter not implemented yet (Phase 1.5C 후속 PR)"
        )

    async def parse_inbound_v2(
        self, request: Request, config: dict[str, Any]
    ) -> ParseInboundResult:
        raise NotImplementedError(
            f"{self.kind} adapter not implemented yet (Phase 1.5C 후속 PR)"
        )

    async def send_outbound(
        self,
        config: dict[str, Any],
        to: str,
        response: Union[str, ResponseEnvelope] = "",
    ) -> None:
        raise NotImplementedError(
            f"{self.kind} adapter not implemented yet (Phase 1.5C 후속 PR)"
        )

    async def collect_response(
        self, sse_stream: AsyncIterator[dict]
    ) -> tuple[str, list[dict]]:
        raise NotImplementedError(
            f"{self.kind} adapter not implemented yet (Phase 1.5C 후속 PR)"
        )


class SlackAdapter(_NotImplementedAdapter):
    """Slack — Block Kit (text/section/actions) → ResponseEnvelope 매핑 예정.

    매핑 가이드 (후속):
    - TextBlock        → chat.postMessage text.
    - CardBlock        → section block + image_url + actions.
    - CarouselBlock    → 다중 attachment (legacy) 또는 section block 반복.
    - QuickReplyBlock  → actions block + buttons.
    - ListCardBlock    → section blocks 다열.
    """

    kind: str = "slack"


class DiscordAdapter(_NotImplementedAdapter):
    """Discord — Embed (title/description/image/fields) → ResponseEnvelope 매핑 예정.

    매핑 가이드 (후속):
    - TextBlock        → 채널 messages 본문.
    - CardBlock        → Embed.
    - CarouselBlock    → 다중 Embed (Discord 는 1 message 당 10개 embed 지원).
    - QuickReplyBlock  → Action Row + Buttons.
    - ListCardBlock    → Embed.fields.
    """

    kind: str = "discord"


class LineAdapter(_NotImplementedAdapter):
    """LINE — Flex Message (bubble/carousel) → ResponseEnvelope 매핑 예정.

    매핑 가이드 (후속):
    - TextBlock        → text message.
    - CardBlock        → bubble Flex Message.
    - CarouselBlock    → carousel Flex Message.
    - QuickReplyBlock  → message + quickReply items.
    - ListCardBlock    → bubble with body components.
    """

    kind: str = "line"


class KakaoTalkAdapter(_NotImplementedAdapter):
    """KakaoTalk — basicCard / carouselCard / listCard / quickReplies 매핑 예정.

    KakaoTalk 의 응답 type 이 우리 ResponseEnvelope 5종과 *직접* 1:1 매핑되어
    사실상 가장 자연스러운 채널. ``Doc/research/2026-05-07-kakao-mapping-final-analysis.md``
    참조.

    매핑 가이드 (후속):
    - TextBlock        → simpleText.
    - CardBlock        → basicCard / commerceCard.
    - CarouselBlock    → carouselCard.
    - QuickReplyBlock  → simpleText + quickReplies.
    - ListCardBlock    → listCard.
    """

    kind: str = "kakaotalk"


__all__ = [
    "SlackAdapter",
    "DiscordAdapter",
    "LineAdapter",
    "KakaoTalkAdapter",
]
