"""ChannelAdapter Protocol + InboundMessage 데이터 클래스.

외부 채널 (Telegram, KakaoWork, 전화) 어댑터의 공통 인터페이스.

NOTE: Phase 1.5C — 응답 표준 ``ResponseEnvelope`` 를 ``send_outbound`` 의
정식 인자로 도입. 기존 ``text: str`` 호출 호환을 위해 어댑터는 두 시그니처를
모두 받는다 (str → ``ResponseEnvelope.from_text(...)`` 자동 wrap).
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Protocol, Union
from fastapi import Request

from src.integration.external_agent.response_blocks import ResponseEnvelope


class ParseInboundError(str, Enum):
    """parse_inbound 실패 사유 — audit log 라벨 통일."""

    SIGNATURE_FAILURE = "signature_failure"  # X-Telegram-Bot-Api-Secret-Token 불일치
    SECRET_MISSING = "secret_missing"        # config 에 webhook_secret 키 자체 없음
    PAYLOAD_INVALID = "payload_invalid"      # JSON parse 실패 / 스키마 위반
    UNSUPPORTED_EVENT = "unsupported_event"  # photo / sticker / poll 등 미지원 이벤트
    HEALTHCHECK_ONLY = "healthcheck_only"    # my_chat_member, edited_message 등 ack-only
    BODY_TOO_LARGE = "body_too_large"        # 1MB 초과 (DoS 방어)


@dataclass
class InboundMessage:
    """채널 inbound 메시지 표준 표현.

    Task 8f — chat_id binding 결함 fix:
    - ``from_user_id`` = 실 발신자 user.id (audit + ``channel_user_mappings``
      external_user_id binding key). group/supergroup 에서도 user 단위.
    - ``chat_id`` = 응답 발송 대상 chat. Telegram 의 ``message.chat.id``.
      group/supergroup/channel 에서는 ``from_user_id`` 와 다름. 응답은 반드시
      이 ``chat_id`` 로 보내야 한다 (잘못된 chat 발송 / 발송 실패 회피).
    - ``chat_type`` = "private" | "group" | "supergroup" | "channel" | None.
      group_enabled 게이트 / 응답 정책에 사용.
    - ``message_thread_id`` = forum supergroup 의 토픽 ID. 응답 sendMessage
      payload 에 포함하지 않으면 General 채널로 새는 결함 차단.

    호환성: ``chat_id`` 는 Optional — adapter 가 미설정 시 caller 가
    ``from_user_id`` 로 fallback (private chat 가정). 새 어댑터는 항상 채울 것.
    """

    from_user_id: str          # 실 user.id (audit / mapping binding key)
    from_user_name: str        # 표시명 (선택, 비어 있을 수 있음)
    text: str                  # 본문 텍스트
    metadata: dict[str, Any]   # 채널별 추가 정보 (message_id 등)
    # idempotency_key — 채널이 제공하는 update 식별자. Telegram 은 update_id,
    # Slack 은 event_id, LINE 은 webhookEventId. webhook router 가
    # ``channel_inbound_dedup`` 테이블에 기록해 재시도 중복 차단 (alembic 060).
    idempotency_key: str | None = None
    # Routing 정보 — Task 8f.
    chat_id: str | None = None
    chat_type: str | None = None
    message_thread_id: int | None = None


@dataclass
class ParseInboundResult:
    """parse_inbound 의 풍부한 반환값.

    호환성: ``message`` 만 사용하면 기존 ``InboundMessage | None`` 와 동일 동작.
    추가 ``error`` 필드로 실패 사유 (audit / 디버깅) 분류 가능.
    """

    message: InboundMessage | None = None
    error: ParseInboundError | None = None
    # event_label — log/audit 용 (예: "message.text", "my_chat_member.added")
    event_label: str | None = None


class ChannelAdapter(Protocol):
    kind: str

    async def parse_inbound(
        self, request: Request, config: dict[str, Any]
    ) -> InboundMessage | None:
        """webhook payload → InboundMessage. 검증 실패 또는 비-msg 이면 None.

        호환 유지를 위해 None 반환 시그니처는 그대로. 어댑터 구현이 더 풍부한
        ``parse_inbound_v2(...) -> ParseInboundResult`` 메서드를 함께 제공할
        수 있으며 (선택), 라우터는 우선 v2 가 있으면 사용.
        """
        ...

    async def send_outbound(
        self,
        config: dict[str, Any],
        to: str,
        response: Union[str, ResponseEnvelope],
    ) -> None:
        """외부 채널로 메시지 발송.

        Phase 1.5C 표준: ``response`` 는 ``ResponseEnvelope`` (5종 블록 묶음).
        호환성: ``str`` 도 받으면 어댑터가 자동으로
        ``ResponseEnvelope.from_text(text)`` 로 wrap 한다 (시연 path 무영향).

        ``ResponseEnvelope`` 가 비어있으면 (``blocks=[]``) no-op (발송 skip).

        채널별 변환 정책은 어댑터 구현에 위임. native 미지원 type 은 안전
        fallback (예: Telegram 의 carousel 은 순차 sendPhoto 로 분해). 이
        메서드는 *raise* 하지 않거나, raise 시 ``TelegramSendError`` 같은
        채널-특화 예외만 던진다.
        """
        ...

    async def collect_response(
        self, sse_stream: AsyncIterator[dict]
    ) -> tuple[str, list[dict]]:
        """SSE stream → 채널 메시지 단일 응답 (token 누적, citations 포함)."""
        ...
