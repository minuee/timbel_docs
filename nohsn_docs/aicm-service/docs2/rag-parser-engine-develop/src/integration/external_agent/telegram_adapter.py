"""Telegram bot 어댑터 — 첫 구현.

raw httpx 사용 (aiogram 미의존). webhook 검증 + 본문 파싱 + sendMessage API.

config 계약:
  - config 는 *항상* plain dict (Task 6 webhook router 가 Fernet 복호 후 전달).
  - vault path ("vault://...") 는 caller 가 미리 해석해 plain string 으로 주입.
  - 어댑터 내부에서 vault/ref 해석을 시도하지 않는다.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from dataclasses import dataclass
from hmac import compare_digest
from typing import Any, AsyncIterator
import httpx
from fastapi import Request

from src.integration.external_agent.base import (
    ChannelAdapter, InboundMessage, ParseInboundError, ParseInboundResult,
)
from src.integration.external_agent.response_blocks import (
    AlertBlock,
    ButtonBlock,
    CardBlock,
    CarouselBlock,
    ImageBlock,
    LinkBlock,
    ListCardBlock,
    ListItem,
    QuickReplyBlock,
    ResponseEnvelope,
    TableBlock,
    TextBlock,
)

log = logging.getLogger(__name__)

# MarkdownV2 이스케이프 대상 문자 (Telegram 공식 문서)
_MD_V2_ESCAPE = "_*[]()~`>#+-=|{}.!"

# webhook body 크기 한도 — Telegram 은 2MB 까지 가능하지만 실 사용은 4-100KB.
# DoS 방어로 1MB 초과는 거부.
MAX_BODY_BYTES = 1 * 1024 * 1024

# 429 retry — 최대 횟수 및 retry_after 상한 (악의적 retry_after 보호).
MAX_429_RETRIES = 3
MAX_RETRY_AFTER_SECS = 30


def _escape_md_v2(text: str) -> str:
    """Telegram MarkdownV2 특수문자 이스케이프.

    한글/숫자는 그대로 통과. 특수문자는 백슬래시 prefix.

    2026-05-08 D18-v2 (사용자 절칙):
    *escape 전* LaTeX → 유니코드 변환 (`$\\rightarrow$` → `→`). KaTeX 미지원
    Telegram 에서도 화살표/그리스/부등호가 평문 가독성으로 노출되도록.
    sanitize 가 결정론적이라 idempotent — 이미 유니코드면 no-op.
    """
    # 2026-05-08 — markdown 정규화 → LaTeX sanitize 순서. heading/표 앞 빈 줄
    # 보장 후 LaTeX 변환. 둘 다 idempotent / swallow 안전.
    try:
        from src.common.text.markdown_normalizer import normalize_markdown
        text = normalize_markdown(text)
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.common.text.latex_sanitizer import sanitize_latex_to_unicode
        text = sanitize_latex_to_unicode(text)
    except Exception:  # noqa: BLE001
        # sanitizer 결함이 발송 흐름 끊지 않도록 swallow.
        pass
    return "".join(("\\" + c if c in _MD_V2_ESCAPE else c) for c in text)


# ---------------------------------------------------------------------------
# Markdown → Telegram HTML 변환 (2026-05-08, rich-text + citations)
# ---------------------------------------------------------------------------
# 사용자 명시 (2026-05-08):
#   "텍스트를 생성할때 좀 이쁘게 생성해서 보내는게 가능한가? 표도 만들고 말이지."
#   "테스트챗창이나, 텔레그램에서는 참조 문서를 링크가 없어. ... 링크를 활성화"
#
# Telegram HTML mode 가 (MarkdownV2 보다 안전·안정적이라) 본 helper 가 LLM 의
# markdown 텍스트를 *HTML* 로 변환한다.
#   - **bold**            → <b>bold</b>
#   - *italic* / _italic_ → <i>italic</i>
#   - `code`              → <code>code</code>
#   - bullet `- item`     → • item
#   - markdown link [t](u)→ <a href="u">t</a>
#   - citation [N]        → <a href="{citation.url}">[N]</a>  (citation 매칭 시)
#
# 보안 (GPT-5 P0):
#   - HTML escape & < > 만 *먼저* 실행 — 이후 markdown 변환은 escape된 텍스트
#     에 적용. 본문 안 < script > 같은 태그는 escape 후 무력화됨.
#   - href scheme 화이트리스트: http / https / /api/ / /repos/ 만 허용.
#     javascript: / data: / blob: / vbscript: / file: 등 차단.
#   - markdown table 은 *별도 TableBlock* 로 분리되므로 본 helper 에선 무시.

import re as _re_md

_ALLOWED_URL_RE = _re_md.compile(
    r"^(https?://[^\s<>\"']+|/api/[^\s<>\"']+|/repos/[^\s<>\"']+)$",
    _re_md.IGNORECASE,
)


def _safe_href(url: str) -> str | None:
    """href URL 화이트리스트 검사. 허용된 스킴만 통과, 그 외 None.

    GPT-5 P0 fix — javascript:/data:/blob: 차단. 상대 경로는 /api/ /repos/ 한정.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if not _ALLOWED_URL_RE.match(url):
        return None
    return url


def _html_escape_text(text: str) -> str:
    """Telegram HTML mode 안전 escape. & < > 만 escape (Telegram 권장)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_citation_url_map(
    citations: list[dict[str, Any]] | None,
    public_base: str | None,
    *,
    tenant_id: "str | uuid.UUID | None" = None,
) -> dict[int, str]:
    """citation list 에서 number → 절대 URL 매핑 build.

    citations 의 ``url`` 필드 (engine 이 채움) 가 상대 경로면 public_base prepend.
    스킴 화이트리스트 필터로 javascript:/data: 등 차단.

    D41 Phase 3 — HMAC token 첨부 (Telegram guest landing):
    - tenant_id 가 None / falsy 이면 *링크 생성 자체 중단* (fail-safe — plain
      [N] 으로 회귀, 다른 tenant block_id 추측 + auth-less 접근 차단).
    - URL 화이트리스트 엄격 (GPT-5 phase 0 v3 P0) — `/api/v1/citations/` 시작
      시에만 token 첨부. 외부 도메인 / 임의 URL 토큰 누설 차단.
    - block_id 가 citation dict 의 ``id`` 필드. UUID invalid / secret missing
      시 link skip (안전 fallback).

    Args:
        citations: SSE citations_finalized 가 emit 한 list.
        public_base: webhook base URL — 상대 path prepend 용.
        tenant_id: channel binding 의 tenant_id (None 이면 link 생성 X).

    Returns:
        ``{number: absolute_url_with_token}`` — Telegram [N] <a href> 매핑.
    """
    if not citations:
        return {}
    if not tenant_id:
        # GPT-5 P0 — tenant_id 미주입 시 링크 생성 X (다른 tenant 의 block_id
        # 추측 + auth-less 접근 위험 차단). plain [N] 으로 회귀.
        return {}
    # 지연 import — 순환 의존 회피.
    from src.common.security.citation_token import sign_citation_token

    out: dict[int, str] = {}
    base = (public_base or "").rstrip("/")
    for c in citations:
        if not isinstance(c, dict):
            continue
        try:
            n = int(c.get("number"))
        except (TypeError, ValueError):
            continue
        url = c.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        # GPT-5 phase 0 v3 P0 — URL 화이트리스트 엄격화. token 첨부는 *오직*
        # engine 이 만든 상대경로 `/api/v1/citations/...` 일 때만. 외부 도메인 /
        # 임의 URL 첨부 차단 (token leak surface 최소화).
        if not url.startswith("/api/v1/citations/"):
            continue
        if not base:
            # base 없으면 절대 URL build 불가 → skip (fail-safe).
            continue
        absolute = f"{base}{url}"
        # block_id = citation dict 의 id 필드. HMAC payload 에 들어가 path
        # tampering 차단.
        block_id = c.get("id")
        if not block_id:
            continue
        try:
            token, exp = sign_citation_token(str(block_id), tenant_id)
        except (ValueError, RuntimeError):
            # UUID invalid (block_id / tenant_id) 또는 secret < 32 byte —
            # 안전 fallback: 해당 citation 만 token 미첨부 (plain [N]).
            continue
        sep = "&" if "?" in absolute else "?"
        absolute = f"{absolute}{sep}t={token}&exp={exp}"
        safe = _safe_href(absolute)
        if safe:
            out[n] = safe
    return out


# ---------------------------------------------------------------------------
# 변환 단계별 정규식
# ---------------------------------------------------------------------------
# 코드블록 / 인라인 code 는 *변환 우회* — 안 변환 위해 placeholder 로 빼낸 뒤
# 다른 변환 후 복원.
_CODE_FENCE_RE = _re_md.compile(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", _re_md.DOTALL)
_INLINE_CODE_RE = _re_md.compile(r"`([^`\n]+)`")
# bold / italic — markdown 의 ** 가 italic 의 * 와 겹치므로 * 먼저 ** 매칭.
_BOLD_RE = _re_md.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC_STAR_RE = _re_md.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_ITALIC_UNDER_RE = _re_md.compile(r"(?<!_)_([^_\n]+?)_(?!_)")
_MD_LINK_RE = _re_md.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# citation [N] (1~3 digit) — markdown link 변환 *후* 처리해야 [N](url) 같은 게
# 안 깨진다.
_CITATION_RE = _re_md.compile(r"\[(\d{1,3})\]")
# bullet line — 줄 시작이 - / * / + + space.
_BULLET_RE = _re_md.compile(r"^([\-\*\+])\s+", _re_md.MULTILINE)
# numbered list — 그대로 유지 (Telegram 도 1. 2. 3. 자연 표시).


def _markdown_to_telegram_html(
    text: str,
    *,
    citation_url_map: dict[int, str] | None = None,
) -> str:
    """LLM markdown → Telegram HTML mode 안전 변환.

    Args:
        text: LLM final text (markdown).
        citation_url_map: ``{number: absolute_url}`` — 본문 안 [N] 마커를
            <a href> 로 wrapping. 빈 dict 또는 None 이면 [N] plain 그대로.

    2026-05-08 D18-v2 (사용자 절칙):
    *최우선* LaTeX → 유니코드 변환 (`$\\rightarrow$` → `→` 등). KRX 봇의
    `$\\rightarrow$` raw 노출 결함 회피. Web KaTeX 와 *동일 통합 답변* 을
    Telegram 도 *읽을 수 있게* 변환.
    """
    if not text:
        return ""
    citations = citation_url_map or {}

    # 0a) markdown 정합성 정규화 (2026-05-08) — heading/표 앞 빈 줄 보장.
    # LLM 답변에 `### 제목` 앞 빈 줄 누락 시 raw 노출 결함 차단. idempotent.
    try:
        from src.common.text.markdown_normalizer import normalize_markdown
        text = normalize_markdown(text)
    except Exception:  # noqa: BLE001
        log.warning("markdown_normalizer failed — continuing with raw text")

    # 0b) LaTeX → 유니코드 (D18-v2). 수식 구분자 안 변환 + 구분자 strip.
    # 매핑 미히트 (`\frac{a}{b}` 같은 복잡식) 는 raw 잔여 — `$` 만 제거되어
    # 평문 가독성 일부 확보. Telegram 은 KaTeX 미지원이라 평문화가 최선.
    try:
        from src.common.text.latex_sanitizer import sanitize_latex_to_unicode
        text = sanitize_latex_to_unicode(text)
    except Exception:  # noqa: BLE001
        # sanitizer 결함이 발송 흐름 전체를 끊지 않도록 swallow.
        log.warning("latex_sanitizer failed — continuing with raw text")

    # 1) 코드블록 / 인라인 code 보호 — placeholder 로 escape.
    code_blocks: list[str] = []

    def _stash_fence(m: _re_md.Match) -> str:
        code_blocks.append(m.group(2))
        return f"\x00CODEBLOCK{len(code_blocks)-1}\x00"

    def _stash_inline(m: _re_md.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00INLINECODE{len(code_blocks)-1}\x00"

    text = _CODE_FENCE_RE.sub(_stash_fence, text)
    text = _INLINE_CODE_RE.sub(_stash_inline, text)

    # 2) HTML escape — 본문 *전체*. 코드블록 placeholder 는 escape 안 됨 (\x00 통과).
    text = _html_escape_text(text)

    # 3) markdown link [text](url) — citation 보다 먼저. URL 이 화이트리스트
    #    통과해야만 링크 wrap. 아니면 raw text 유지 (escape 됐으니 안전).
    def _link_sub(m: _re_md.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        # url 은 escape 된 상태일 수 있음 — 원복.
        url_raw = (
            url.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        )
        safe = _safe_href(url_raw)
        if not safe:
            return f"[{label}]({url})"
        # href 안 따옴표는 escape (HTML mode 권장).
        href = safe.replace('"', "&quot;")
        return f'<a href="{href}">{label}</a>'

    text = _MD_LINK_RE.sub(_link_sub, text)

    # 4) citation [N] — citation_url_map 매칭 시 <a href> wrap.
    def _cite_sub(m: _re_md.Match) -> str:
        try:
            n = int(m.group(1))
        except ValueError:
            return m.group(0)
        url = citations.get(n)
        if not url:
            return m.group(0)  # plain [N] 유지.
        href = url.replace('"', "&quot;")
        return f'<a href="{href}">[{n}]</a>'

    text = _CITATION_RE.sub(_cite_sub, text)

    # 5) bold / italic — link/citation HTML 안에 들어가지 않도록 외부 텍스트만.
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_UNDER_RE.sub(r"<i>\1</i>", text)

    # 6) bullet — '- item' / '* item' / '+ item' → '• item'.
    text = _BULLET_RE.sub("• ", text)

    # 7) 코드블록 placeholder 복원.
    def _restore_fence(m: _re_md.Match) -> str:
        idx = int(m.group(1))
        code = code_blocks[idx] if 0 <= idx < len(code_blocks) else ""
        return f"<pre>{_html_escape_text(code)}</pre>"

    def _restore_inline(m: _re_md.Match) -> str:
        idx = int(m.group(1))
        code = code_blocks[idx] if 0 <= idx < len(code_blocks) else ""
        return f"<code>{_html_escape_text(code)}</code>"

    text = _re_md.sub(r"\x00CODEBLOCK(\d+)\x00", _restore_fence, text)
    text = _re_md.sub(r"\x00INLINECODE(\d+)\x00", _restore_inline, text)

    return text


@dataclass(frozen=True)
class _SendContext:
    """블록 발송 helper 전반에 공유되는 컨텍스트.

    chat_id / message_thread_id 같은 인자가 모든 sub-call (sendMessage,
    sendPhoto, ...) 에 동일하게 들어가 — 매 helper 마다 키워드 펴는 대신
    1 객체로 묶음.

    2026-05-08 — citation 인라인 링크 (사용자 절칙). citation_url_map 은
    {number: absolute_url} — TextBlock(parse_mode="markdown") 변환 시
    본문 안 [N] 마커를 <a href> 로 wrap 하는 데 사용. None 이면 비활성.
    """

    bot_token: str
    chat_id: int | str
    message_thread_id: int | None = None
    citation_url_map: dict[int, str] | None = None


class TelegramSendError(RuntimeError):
    """Telegram sendMessage 실패.

    Attributes:
        status_code: HTTP status (None = network 오류 / timeout)
        retryable: True 면 caller 가 backoff 후 재시도 가능. False 면 permanent
            (token 폐기, 사용자 차단 등) — 채널 / mapping 비활성 권고.
        permanent_reason: permanent 일 때 사유 코드 (
            ``"bot_blocked"`` / ``"chat_not_found"`` / ``"token_revoked"`` 등).
            caller 가 분기.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
        permanent_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.permanent_reason = permanent_reason


class TelegramAdapter:
    kind: str = "telegram"

    async def parse_inbound(
        self, request: Request, config: dict[str, Any]
    ) -> InboundMessage | None:
        """webhook payload → InboundMessage (호환 시그니처).

        검증 실패 / 비-메시지 이벤트 / secret 없음 → None 반환 (fail-closed).

        새 코드 / 라우터는 ``parse_inbound_v2`` 사용을 권장 (실패 사유 + audit 라벨).
        """
        result = await self.parse_inbound_v2(request, config)
        return result.message

    async def parse_inbound_v2(
        self, request: Request, config: dict[str, Any]
    ) -> ParseInboundResult:
        """webhook payload → ParseInboundResult (실패 사유 분류).

        라우터가 audit log 에 ``error`` 와 ``event_label`` 을 기록해 운영
        디버깅 가능. 보안 검증은 *body 파싱 전* 수행 (unauthenticated body
        처리 사이드이펙트 차단).

        Routing/metadata 보강 (Task 8f + Telegram deep dive §11):
        - ``from_user_id`` = 실 발신자 user.id (audit / mapping key).
        - ``chat_id`` = ``message.chat.id`` (응답 발송 대상 — group/supergroup
          에서도 정확한 chat 으로 발송).
        - ``chat_type`` = "private" | "group" | "supergroup" | "channel".
        - ``message_thread_id`` = forum supergroup 토픽 ID (응답이 General 로
          새는 결함 차단).
        """
        # 1) webhook secret 검증 (constant-time compare).
        expected_secret = config.get("webhook_secret")  # plain string only
        if expected_secret is None:
            log.warning(
                "telegram webhook_secret missing in config — fail-closed"
            )
            return ParseInboundResult(error=ParseInboundError.SECRET_MISSING)

        actual_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
        # 길이가 다르면 compare_digest 가 즉시 false — 안전.
        if not compare_digest(actual_secret, expected_secret):
            log.warning("telegram webhook secret mismatch")
            return ParseInboundResult(error=ParseInboundError.SIGNATURE_FAILURE)

        # 2) body size 한도 — Content-Length 헤더 우선, 없으면 read 후 측정.
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
            log.warning(
                "telegram webhook body too large content_length=%s", cl
            )
            return ParseInboundResult(error=ParseInboundError.BODY_TOO_LARGE)

        # 3) JSON parse.
        try:
            body = await request.json()
        except Exception:
            log.warning("telegram webhook body json parse failed")
            return ParseInboundResult(error=ParseInboundError.PAYLOAD_INVALID)

        if not isinstance(body, dict):
            return ParseInboundResult(error=ParseInboundError.PAYLOAD_INVALID)

        # update_id — Telegram update 의 멱등성 key (필수, 단조증가 int).
        update_id_raw = body.get("update_id")
        idempotency_key: str | None = None
        if isinstance(update_id_raw, int):
            idempotency_key = str(update_id_raw)

        # 4) 이벤트 분류 — text 메시지만 처리, 그 외는 ack-only.
        msg = body.get("message")
        if not isinstance(msg, dict):
            # my_chat_member / edited_message / callback_query 등 — ack 만.
            label = next(
                (k for k in (
                    "edited_message", "channel_post", "callback_query",
                    "my_chat_member", "chat_member", "inline_query",
                    "chat_join_request",
                ) if isinstance(body.get(k), dict)),
                "unknown",
            )
            return ParseInboundResult(
                error=ParseInboundError.HEALTHCHECK_ONLY,
                event_label=f"non_message.{label}",
            )

        text = msg.get("text") or ""
        if not text:
            # photo / sticker / voice / document — Phase 1 미지원
            kind_label = next(
                (k for k in (
                    "photo", "sticker", "voice", "video", "document",
                    "audio", "location", "contact", "poll",
                ) if k in msg),
                "unknown",
            )
            return ParseInboundResult(
                error=ParseInboundError.UNSUPPORTED_EVENT,
                event_label=f"message.{kind_label}",
            )

        from_user = msg.get("from") or {}
        chat = msg.get("chat") or {}
        chat_type = chat.get("type")  # private / group / supergroup / channel
        chat_id_raw = chat.get("id")
        from_id_raw = from_user.get("id")

        # from_user_id = 실 user.id (audit / mapping). channel post 는 from
        # 없을 수 있어 chat.id 로 fallback.
        if from_id_raw is not None:
            from_user_id = str(from_id_raw)
        elif chat_id_raw is not None:
            from_user_id = str(chat_id_raw)
        else:
            return ParseInboundResult(error=ParseInboundError.PAYLOAD_INVALID)

        # chat_id = 응답 발송 대상. group/supergroup/channel 도 정확히 분리.
        chat_id_str = str(chat_id_raw) if chat_id_raw is not None else None

        # message_thread_id — forum supergroup 토픽. int 로 normalize.
        thread_id_raw = msg.get("message_thread_id")
        try:
            thread_id = int(thread_id_raw) if thread_id_raw is not None else None
        except (TypeError, ValueError):
            thread_id = None

        message = InboundMessage(
            from_user_id=from_user_id,
            from_user_name=str(
                from_user.get("first_name", "") or from_user.get("username", "")
            ),
            text=text,
            metadata={
                "chat_id": chat_id_raw,
                "chat_type": chat_type,
                "message_id": msg.get("message_id"),
                "message_thread_id": thread_id,
                "from_id": from_id_raw,
                "date": msg.get("date"),
            },
            idempotency_key=idempotency_key,
            chat_id=chat_id_str,
            chat_type=chat_type if chat_type in (
                "private", "group", "supergroup", "channel"
            ) else None,
            message_thread_id=thread_id,
        )
        return ParseInboundResult(
            message=message, event_label=f"message.text.{chat_type or 'unknown'}"
        )

    async def send_outbound(
        self,
        config: dict[str, Any],
        to: str,
        response: "str | ResponseEnvelope" = "",
        *,
        message_thread_id: int | None = None,
        # 호환성: 기존 ``text=`` 키워드 호출 패턴 보존.
        text: str | None = None,
        # 2026-05-08 — citation 인라인 링크. webhook layer 가 SSE event=citations
        # 로 capture 한 list 를 그대로 넘김. 본 helper 가 number→absolute_url
        # 매핑을 build 해 markdown→HTML 변환 시 [N] 마커를 <a href> 로 wrap.
        # None 이면 기존 동작 (citation 링크 X).
        citations: list[dict[str, Any]] | None = None,
        # citation url 이 상대 경로 (`/api/v1/citations/...`) 면 prepend 할 base.
        # config 에 webhook_base 가 있으면 그것을 우선, 없으면 settings.
        public_base_url: str | None = None,
        # D41 Phase 3 — channel binding 의 tenant_id. HMAC token 생성에 필수.
        # None 이면 _build_citation_url_map 가 link 생성 X (fail-safe, plain [N]).
        tenant_id: str | uuid.UUID | None = None,
    ) -> None:
        """외부 채널로 메시지 발송 — Phase 1.5C ResponseEnvelope 표준.

        시그니처 호환:
        - 신 표준: ``send_outbound(config, to, ResponseEnvelope([...]))``
        - 평문: ``send_outbound(config, to, "hello")`` —
          내부에서 ``ResponseEnvelope.from_text(text)`` 자동 wrap.
        - 레거시 키워드: ``send_outbound(config, to=..., text="hello")`` — 기존
          호출자 보존 (시연 path 무영향).

        ResponseEnvelope 가 비어있으면 (``blocks=[]``) no-op.

        블록별 Telegram 매핑:
        - TextBlock        → sendMessage (MarkdownV2 escape).
        - CardBlock        → sendPhoto + caption + InlineKeyboardMarkup
                             (image_url 없으면 sendMessage with markdown).
        - CarouselBlock    → 카드 순차 발송 (Telegram native carousel 없음).
        - QuickReplyBlock  → sendMessage + ReplyKeyboardMarkup
                             (one_time_keyboard=True).
        - ListCardBlock    → sendMessage with markdown 항목 리스트 +
                             InlineKeyboardMarkup (footer buttons).

        ButtonBlock action 매핑:
        - url      → InlineKeyboard ``url`` 필드.
        - postback → InlineKeyboard ``callback_data`` 필드.
        - phone    → 메시지 본문에 ``라벨: 전화번호`` 텍스트 inline (Telegram 의
                     phone share 는 contact request 가 별도 API 라 단순화).
        - share    → 메시지 본문에 텍스트 inline.

        실패 시 ``TelegramSendError`` raise. 에러 코드 분류는
        ``_send_request`` 참고. bot_token 누락은 ``ValueError``.
        """
        # 1) 입력 정규화 — str / None / ResponseEnvelope 모두 envelope 로.
        envelope = self._coerce_envelope(response, text)
        if envelope.is_empty():
            return  # no-op

        bot_token = config.get("bot_token")
        if not bot_token:
            raise ValueError("telegram bot_token missing in config")

        chat_id = self._coerce_chat_id(to)
        # 2026-05-08 — citation url map build (one-shot). public_base_url 우선,
        # 미지정 시 config 의 base, 그것도 없으면 settings.
        if public_base_url is None:
            public_base_url = config.get("public_base_url") or config.get(
                "webhook_base_url"
            )
        if public_base_url is None:
            try:
                from src.common.config import settings as _settings
                public_base_url = getattr(
                    _settings, "EXTERNAL_AGENT_WEBHOOK_BASE_URL", ""
                ) or None
            except Exception:  # noqa: BLE001
                public_base_url = None
        # D41 Phase 3 — tenant_id 우선순위: 명시 인자 > config["tenant_id"].
        # 둘 다 None 이면 _build_citation_url_map 가 link 생성 X (fail-safe).
        effective_tenant_id = tenant_id if tenant_id is not None else config.get(
            "tenant_id"
        )
        citation_url_map = _build_citation_url_map(
            citations, public_base_url, tenant_id=effective_tenant_id
        )
        ctx = _SendContext(
            bot_token=bot_token,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            citation_url_map=citation_url_map or None,
        )

        # 2) 블록별 발송 — 순서 보존, native 매핑.
        for block in envelope.blocks:
            if isinstance(block, TextBlock):
                await self._send_text_block(ctx, block)
            elif isinstance(block, CardBlock):
                await self._send_card_block(ctx, block)
            elif isinstance(block, CarouselBlock):
                # Telegram 은 native carousel 없음 — 카드 순차 발송.
                for card in block.cards:
                    await self._send_card_block(ctx, card)
            elif isinstance(block, QuickReplyBlock):
                await self._send_quick_reply_block(ctx, block)
            elif isinstance(block, ListCardBlock):
                await self._send_list_card_block(ctx, block)
            elif isinstance(block, ImageBlock):
                # KMS-Plus 2026-05-07 — 그림 첨부 (사용자 절칙).
                await self._send_image_block(ctx, block)
            elif isinstance(block, TableBlock):
                # KMS-Plus 2026-05-07 — 표 첨부.
                await self._send_table_block(ctx, block)
            elif isinstance(block, LinkBlock):
                # KMS-Plus 2026-05-07 — 외부 링크.
                await self._send_link_block(ctx, block)
            elif isinstance(block, AlertBlock):
                # KMS-Plus 2026-05-07 — 색상 박스 안내.
                await self._send_alert_block(ctx, block)
            else:
                # 알 수 없는 블록 type — 안전 fallback (텍스트 대표).
                fallback = getattr(block, "text", None) or repr(block)
                await self._send_text_block(
                    ctx, TextBlock(text=str(fallback), parse_mode="plain")
                )

    # -------------------------------------------------------------------
    # 블록 → Telegram API 변환 helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _coerce_envelope(
        response: "str | ResponseEnvelope | None",
        text: str | None,
    ) -> ResponseEnvelope:
        """입력을 ResponseEnvelope 로 정규화 — 호환 dispatch."""
        if isinstance(response, ResponseEnvelope):
            return response
        if isinstance(response, str) and response:
            return ResponseEnvelope.from_text(response)
        if isinstance(text, str) and text:
            return ResponseEnvelope.from_text(text)
        return ResponseEnvelope(blocks=[])

    @staticmethod
    def _coerce_chat_id(to: str) -> int | str:
        """to 가 numeric chat_id 일 수도, username 일 수도. 둘 다 처리."""
        try:
            return int(to)
        except (ValueError, TypeError):
            return to

    @staticmethod
    def _build_inline_keyboard(
        buttons: list[ButtonBlock],
    ) -> dict[str, Any] | None:
        """ButtonBlock list → InlineKeyboardMarkup. action 별 매핑.

        - url      → {"text", "url"}
        - postback → {"text", "callback_data"}
        - phone / share → 인라인 키보드에 표현 어색 → None 반환 (caller 가
          본문 텍스트로 inline). 빈 리스트도 None.
        """
        rows: list[list[dict[str, Any]]] = []
        for btn in buttons:
            if btn.action == "url":
                # D41 Phase 3 pre P0 — URL 스킴 화이트리스트 (javascript:/data:
                # 차단, defense-in-depth). 통과 못하면 button 자체를 skip.
                safe = _safe_href(btn.payload or "")
                if safe is None:
                    continue
                rows.append([{"text": btn.label, "url": safe}])
            elif btn.action == "postback":
                # callback_data 64 byte 한도 — Telegram 제약. 초과는 truncate.
                cb = btn.payload[:64] if btn.payload else ""
                rows.append([{"text": btn.label, "callback_data": cb}])
            # phone / share 는 inline keyboard 표현 X — caller 가 텍스트 처리.
        if not rows:
            return None
        return {"inline_keyboard": rows}

    @staticmethod
    def _format_inline_phone_share(
        buttons: list[ButtonBlock],
    ) -> str:
        """phone / share 액션 버튼은 본문 텍스트로 inline 변환.

        phone → "라벨: 010-1234-5678"
        share → "라벨: <payload>"
        url / postback 은 inline keyboard 처리 — 여기 포함 X.
        """
        lines: list[str] = []
        for btn in buttons:
            if btn.action == "phone":
                lines.append(f"{btn.label}: {btn.payload}")
            elif btn.action == "share":
                lines.append(f"{btn.label}: {btn.payload}")
        return "\n".join(lines)

    async def _send_text_block(
        self, ctx: "_SendContext", block: TextBlock
    ) -> None:
        """TextBlock → sendMessage.

        - parse_mode == "markdown" 일 때 (2026-05-08 rich-text):
          markdown → HTML 변환 (bold/italic/code/link/citation/bullet) 후
          parse_mode=HTML 로 발송. citation [N] 마커는 ctx.citation_url_map
          으로 <a href> wrap. 4096자 한도 → 초과 시 truncate + 안내.
        - parse_mode == "plain" 일 때:
          기존 MarkdownV2 escape 경로 (회귀 0).

        실패 시 plain text fallback — envelope 흐름 끊지 않음.
        """
        if block.parse_mode == "markdown":
            # 2026-05-08 — markdown → HTML 변환 (rich-text + citation 링크).
            try:
                html_text = _markdown_to_telegram_html(
                    block.text,
                    citation_url_map=ctx.citation_url_map,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "markdown_to_html failed: %s — fallback to plain", exc
                )
                html_text = None
            if html_text:
                # Telegram sendMessage 4096자 한도 — 안전 margin 3900 truncate.
                if len(html_text) > 3900:
                    html_text = html_text[:3900] + "\n\n... (잘림)"
                payload: dict[str, Any] = {
                    "chat_id": ctx.chat_id,
                    "text": html_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                }
                if ctx.message_thread_id is not None:
                    payload["message_thread_id"] = ctx.message_thread_id
                try:
                    await self._send_request(
                        ctx.bot_token, "sendMessage", payload
                    )
                    return
                except TelegramSendError as exc:
                    log.warning(
                        "sendMessage(HTML) failed status=%s — fallback plain",
                        exc.status_code,
                    )
                    # plain fallback 으로 진행.

        # plain mode — 기존 MarkdownV2 escape 경로 (회귀 0).
        # D18-v2 (2026-05-08) — `_escape_md_v2` 가 *내부적으로* sanitize_latex
        # 호출 (idempotent). MarkdownV2 도 LaTeX 미지원이라 `$\rightarrow$`
        # 가 평문 `→` 로 변환된 뒤 escape 됨.
        payload_text = _escape_md_v2(block.text)
        payload = {
            "chat_id": ctx.chat_id,
            "text": payload_text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        await self._send_request(ctx.bot_token, "sendMessage", payload)

    async def _send_card_block(
        self, ctx: "_SendContext", card: CardBlock
    ) -> None:
        """CardBlock → sendPhoto (이미지 있으면) 또는 sendMessage.

        caption 은 markdown — title 굵게 + description.
        """
        # caption / text body 구성
        title_md = _escape_md_v2(card.title)
        body_parts = [f"*{title_md}*"] if card.title else []
        if card.description:
            body_parts.append(_escape_md_v2(card.description))
        # phone / share 액션은 본문 inline.
        phone_share = self._format_inline_phone_share(card.buttons)
        if phone_share:
            body_parts.append(_escape_md_v2(phone_share))
        body = "\n\n".join(body_parts)

        reply_markup = self._build_inline_keyboard(card.buttons)

        if card.image_url:
            payload: dict[str, Any] = {
                "chat_id": ctx.chat_id,
                "photo": card.image_url,
                "caption": body,
                "parse_mode": "MarkdownV2",
            }
            if ctx.message_thread_id is not None:
                payload["message_thread_id"] = ctx.message_thread_id
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            await self._send_request(ctx.bot_token, "sendPhoto", payload)
        else:
            payload = {
                "chat_id": ctx.chat_id,
                "text": body,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": False,
            }
            if ctx.message_thread_id is not None:
                payload["message_thread_id"] = ctx.message_thread_id
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            await self._send_request(ctx.bot_token, "sendMessage", payload)

    async def _send_quick_reply_block(
        self, ctx: "_SendContext", block: QuickReplyBlock
    ) -> None:
        """QuickReplyBlock → sendMessage + ReplyKeyboardMarkup.

        ``one_time_keyboard=True`` 로 한 번 탭하면 키보드 사라짐 (UX).
        ``options`` 의 각 항목이 사용자가 탭하면 그대로 입력 텍스트로 전송.
        """
        text_md = _escape_md_v2(block.text)
        # 각 옵션을 1열 keyboard row 로 — 모바일 가독성.
        keyboard = [[{"text": opt}] for opt in block.options if opt]
        payload: dict[str, Any] = {
            "chat_id": ctx.chat_id,
            "text": text_md,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        if keyboard:
            payload["reply_markup"] = {
                "keyboard": keyboard,
                "one_time_keyboard": True,
                "resize_keyboard": True,
            }
        await self._send_request(ctx.bot_token, "sendMessage", payload)

    async def _send_list_card_block(
        self, ctx: "_SendContext", block: ListCardBlock
    ) -> None:
        """ListCardBlock → sendMessage with markdown 항목 리스트 + InlineKeyboard.

        제목 굵게 + 항목 ``- text`` (description 있으면 들여쓰기 한 줄). 항목별
        callback 은 inline keyboard 의 별도 버튼으로 노출.
        """
        title_md = _escape_md_v2(block.title) if block.title else ""
        body_parts: list[str] = []
        if title_md:
            body_parts.append(f"*{title_md}*")

        item_lines: list[str] = []
        item_callback_buttons: list[ButtonBlock] = []
        for it in block.items:
            line = f"\\- {_escape_md_v2(it.text)}"
            if it.description:
                # MarkdownV2 안전 — italic 로 부연.
                line += f"\n  _{_escape_md_v2(it.description)}_"
            item_lines.append(line)
            if it.callback:
                item_callback_buttons.append(
                    ButtonBlock(
                        label=it.text[:32] or "선택",
                        action="postback",
                        payload=it.callback,
                    )
                )
        if item_lines:
            body_parts.append("\n".join(item_lines))

        # phone / share footer 액션은 본문 inline.
        phone_share = self._format_inline_phone_share(block.buttons)
        if phone_share:
            body_parts.append(_escape_md_v2(phone_share))

        body = "\n\n".join(body_parts) if body_parts else _escape_md_v2("(빈 목록)")

        # inline keyboard = 항목 callback + footer buttons (url/postback 만).
        merged_buttons = item_callback_buttons + list(block.buttons)
        reply_markup = self._build_inline_keyboard(merged_buttons)

        payload: dict[str, Any] = {
            "chat_id": ctx.chat_id,
            "text": body,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self._send_request(ctx.bot_token, "sendMessage", payload)

    # -------------------------------------------------------------------
    # KMS-Plus 2026-05-07 — multimodal block helpers (image / table / link / alert).
    # 사용자 절칙: "표나 그림도 답변과 같이 첨부 — 풀옵션".
    # -------------------------------------------------------------------

    async def _send_image_block(
        self, ctx: "_SendContext", block: "ImageBlock"
    ) -> None:
        """ImageBlock → sendPhoto + caption.

        - image_url 가 비어 있으면 caption 만 텍스트로 fallback (절대 raise 금지).
        - caption 은 markdown_v2 escape (한글/영문 통과).
        - GPT-5 P1-2 — caption 1024자 한도 → 안전 margin 900자 truncate.
        - GPT-5 P1-3 — sendPhoto 실패 시 caption + url 을 TextBlock 으로 fallback,
          예외는 raise 하지 않고 다음 block 발송 계속하도록 swallow.
        """
        if not block.image_url:
            # 이미지 url 없으면 caption 만이라도 안내.
            fallback = block.caption or block.alt_text or "(이미지 없음)"
            await self._send_text_block(
                ctx, TextBlock(text=fallback, parse_mode="plain")
            )
            return
        # GPT-5 P1-2 — caption truncate (Telegram sendPhoto 한도 1024).
        caption_raw = block.caption or ""
        if len(caption_raw) > 900:
            caption_raw = caption_raw[:880] + "..."
        caption_md = _escape_md_v2(caption_raw) if caption_raw else ""
        payload: dict[str, Any] = {
            "chat_id": ctx.chat_id,
            "photo": block.image_url,
            "parse_mode": "MarkdownV2",
        }
        if caption_md:
            payload["caption"] = caption_md
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        try:
            await self._send_request(ctx.bot_token, "sendPhoto", payload)
        except TelegramSendError as exc:
            # GPT-5 P1-3 — 이미지 발송 실패 → caption + url 텍스트로 fallback,
            # 다음 block 으로 계속 진행 (envelope 전체가 끊기지 않도록).
            log.warning(
                "telegram sendPhoto failed status=%s — falling back to text",
                exc.status_code,
            )
            fallback_text = (
                f"{block.caption or block.alt_text or '이미지'}: {block.image_url}"
            )
            try:
                await self._send_text_block(
                    ctx, TextBlock(text=fallback_text, parse_mode="plain")
                )
            except Exception:  # noqa: BLE001
                pass  # fallback 도 실패면 silent — 다음 block 으로.

    async def _send_table_block(
        self, ctx: "_SendContext", block: "TableBlock"
    ) -> None:
        """TableBlock → sendMessage with HTML <pre> monospace 본문.

        Telegram 은 native table 없음 — HTML <pre> 로 monospace 표 가독성 확보.
        markdown 우선, 없으면 headers/rows 로 빌드.

        GPT-5 P1-1 fix — MarkdownV2 pre-block 은 backslash/backtick escape 가
        불완전 (table cell 의 `|` escape 가 \\| 로 백슬래시 들어가 parse 깨짐).
        HTML mode 로 바꿔 `<pre>` + `&` `<` `>` 만 escape 하면 안전.

        4096 자 한도 — 3800 초과 시 truncate + 안내.
        실패 시 raise 하지 않고 plain text fallback (다음 block 계속).
        """
        # markdown 본문 결정.
        body_md = (block.markdown or "").strip()
        if not body_md and block.headers and block.rows:
            body_md = self._build_markdown_table(block.headers, block.rows)
        if not body_md:
            body_md = "(빈 표)"

        # HTML escape — &, <, > 만. 표 안 cell 은 그대로 monospace 렌더.
        safe_body = (
            body_md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        if len(safe_body) > 3800:
            safe_body = safe_body[:3800] + "\n\n... (잘림)"

        title_html = ""
        if block.title:
            title_safe = (
                block.title.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            title_html = f"<b>{title_safe}</b>\n\n"
        text = f"{title_html}<pre>{safe_body}</pre>"

        payload: dict[str, Any] = {
            "chat_id": ctx.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        try:
            await self._send_request(ctx.bot_token, "sendMessage", payload)
        except TelegramSendError as exc:
            # GPT-5 P1-3 — 표 발송 실패 → plain 텍스트 fallback, 다음 block 계속.
            log.warning(
                "telegram sendMessage(table HTML) failed status=%s — plain fallback",
                exc.status_code,
            )
            try:
                fallback_text = (
                    f"{block.title or '표'}\n{body_md[:3500]}"
                )
                await self._send_text_block(
                    ctx, TextBlock(text=fallback_text, parse_mode="plain")
                )
            except Exception:  # noqa: BLE001
                pass

    async def _send_link_block(
        self, ctx: "_SendContext", block: "LinkBlock"
    ) -> None:
        """LinkBlock → sendMessage + 인라인 url 버튼.

        본문엔 title/description 노출, 버튼으로 외부 URL 진입.
        """
        if not block.url:
            return  # url 없는 LinkBlock 은 no-op
        title = block.title or block.url
        body_parts = [_escape_md_v2(title)]
        if block.description:
            body_parts.append(_escape_md_v2(block.description))
        text = "\n".join(body_parts)

        # D41 Phase 3 pre P0 — URL 스킴 화이트리스트. 통과 못하면 button 비활성
        # (텍스트만 발송, 회귀 0).
        safe_url = _safe_href(block.url)
        payload: dict[str, Any] = {
            "chat_id": ctx.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        if safe_url is not None:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": title[:64] or "열기", "url": safe_url}]]
            }
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        await self._send_request(ctx.bot_token, "sendMessage", payload)

    async def _send_alert_block(
        self, ctx: "_SendContext", block: "AlertBlock"
    ) -> None:
        """AlertBlock → sendMessage + level 별 아이콘 prefix.

        Telegram 은 색상 박스 native 없음 — 텍스트 prefix 로 시각 구분.
        """
        # level 별 prefix — 이모지 X (사용자 절칙). 텍스트 라벨로 구분.
        level_prefix = {
            "info": "[INFO]",
            "warning": "[주의]",
            "error": "[오류]",
            "success": "[성공]",
        }.get(block.level or "info", "[INFO]")

        title_md = ""
        if block.title:
            title_md = f"*{_escape_md_v2(block.title)}*\n"
        prefix_md = _escape_md_v2(level_prefix) + " "
        body_md = _escape_md_v2(block.text or "")
        text = f"{title_md}{prefix_md}{body_md}".strip()

        payload: dict[str, Any] = {
            "chat_id": ctx.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        if ctx.message_thread_id is not None:
            payload["message_thread_id"] = ctx.message_thread_id
        await self._send_request(ctx.bot_token, "sendMessage", payload)

    @staticmethod
    def _build_markdown_table(
        headers: list[str], rows: list[list[str]]
    ) -> str:
        """headers + rows → GFM markdown 표.

        cell 안의 ``|`` / 줄바꿈은 안전 치환. 빈 행/빈 헤더는 그대로 통과.
        """
        def _safe_cell(c: object) -> str:
            s = str(c) if c is not None else ""
            return s.replace("|", "\\|").replace("\n", " ").strip()

        cols = max(len(headers), max((len(r) for r in rows), default=0))
        if cols == 0:
            return ""
        # header 행 padding
        h = list(headers) + [""] * (cols - len(headers))
        lines = ["| " + " | ".join(_safe_cell(c) for c in h) + " |"]
        lines.append("|" + "|".join([" --- "] * cols) + "|")
        for r in rows:
            r2 = list(r) + [""] * (cols - len(r))
            lines.append("| " + " | ".join(_safe_cell(c) for c in r2) + " |")
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # 저수준 — 공통 HTTP 호출 (429 retry / 에러 분류).
    # -------------------------------------------------------------------

    async def _send_request(
        self,
        bot_token: str,
        method: str,
        payload: dict[str, Any],
    ) -> None:
        """Telegram bot API 호출 + 에러 분류 + 429 backoff retry.

        에러 코드 분류 (Telegram deep dive §15):
        - 429 → ``parameters.retry_after`` 만큼 sleep 후 재시도 (최대 3회).
        - 401 → token 폐기. ``permanent_reason="token_revoked"``, retryable=False.
        - 403 → 봇 차단 / 그룹 추방. ``permanent_reason="bot_blocked"`` /
          ``"bot_kicked"`` / ``"user_deactivated"``, retryable=False.
        - 400 → payload 오류. ``"chat_not_found"`` 등 permanent.
        - 5xx → transient. ``retryable=True``.
        - timeout / network → ``retryable=True``.
        """
        url = f"https://api.telegram.org/bot{bot_token}/{method}"
        retries_left = MAX_429_RETRIES
        last_err: TelegramSendError | None = None

        while retries_left >= 0:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
            except httpx.TimeoutException as e:
                log.error("telegram %s timeout", method)
                raise TelegramSendError(
                    "timeout", status_code=None, retryable=True
                ) from e
            except Exception as e:
                log.exception("telegram %s network error", method)
                raise TelegramSendError(
                    str(e), status_code=None, retryable=True
                ) from e

            sc = resp.status_code
            if sc < 400:
                return

            try:
                body_json = resp.json()
            except Exception:
                body_json = {}
            description = (body_json or {}).get("description", "")
            params = (body_json or {}).get("parameters", {}) or {}

            log.error(
                "telegram %s %s: %s", method, sc, (resp.text or "")[:300]
            )

            if sc == 429:
                retry_after_raw = params.get("retry_after")
                if retry_after_raw is None:
                    retry_after_raw = resp.headers.get("Retry-After")
                try:
                    retry_after = int(retry_after_raw)
                except (TypeError, ValueError):
                    retry_after = 1
                retry_after = max(0, min(retry_after, MAX_RETRY_AFTER_SECS))

                last_err = TelegramSendError(
                    f"HTTP 429 retry_after={retry_after}",
                    status_code=429,
                    retryable=True,
                )
                if retries_left <= 0:
                    raise last_err
                retries_left -= 1
                log.warning(
                    "telegram 429 sleep retry_after=%s remaining_retries=%s",
                    retry_after,
                    retries_left,
                )
                await asyncio.sleep(retry_after)
                continue

            if sc == 401:
                raise TelegramSendError(
                    f"HTTP 401: {description or 'unauthorized'}",
                    status_code=401,
                    retryable=False,
                    permanent_reason="token_revoked",
                )

            if sc == 403:
                low = description.lower()
                if "blocked" in low:
                    reason = "bot_blocked"
                elif "kicked" in low:
                    reason = "bot_kicked"
                elif "deactivated" in low:
                    reason = "user_deactivated"
                else:
                    reason = "forbidden"
                raise TelegramSendError(
                    f"HTTP 403: {description or 'forbidden'}",
                    status_code=403,
                    retryable=False,
                    permanent_reason=reason,
                )

            if sc == 400:
                low = description.lower()
                if "chat not found" in low:
                    reason = "chat_not_found"
                else:
                    reason = "bad_request"
                raise TelegramSendError(
                    f"HTTP 400: {description or 'bad request'}",
                    status_code=400,
                    retryable=False,
                    permanent_reason=reason,
                )

            if sc >= 500:
                raise TelegramSendError(
                    f"HTTP {sc}",
                    status_code=sc,
                    retryable=True,
                )

            raise TelegramSendError(
                f"HTTP {sc}",
                status_code=sc,
                retryable=False,
            )

        if last_err is not None:
            raise last_err
        raise TelegramSendError("unreachable", status_code=None, retryable=False)

    async def collect_response(
        self, sse_stream: AsyncIterator[dict]
    ) -> tuple[str, list[dict]]:
        chunks: list[str] = []
        citations: list[dict] = []
        async for ev in sse_stream:
            event_name = ev.get("event")
            data = ev.get("data") or {}

            if event_name in ("token", "delta"):
                chunks.append(data.get("text") or data.get("delta") or "")
            elif event_name == "citations_finalized":
                items = data.get("items") or []
                if isinstance(items, list):
                    citations = items

        body = "".join(chunks).strip()
        if citations:
            # Telegram message 길이 한계 4096. citations 부분 줄여서 추가.
            # D85c-B2 (2026-05-13) — 사용자 보고 "근거문서 링크 매번 누락" fix.
            # 이전: 제목만 plain text. URL 누락. 이제 HTML `<a href="url">title</a>`
            # 형식 — `_markdown_to_telegram_html()` path 가 본문을 HTML 로 보낼 때
            # 그대로 inline link 가 됨. 본문이 plain text path 면 일반 텍스트로
            # fallback (markdown 파서 깨질 risk 회피 — GPT-5.5 D85c #2 권고).
            #
            # title 안 HTML special char (`<`, `>`, `&`) escape — Telegram HTML
            # parser 가 깨지지 않도록. url 은 backend 가 이미 URL-encode (HMAC
            # signed) — 추가 escape 불요.
            def _esc(s: str) -> str:
                return (
                    s.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )

            cite_lines = []
            for i, c in enumerate(citations[:5]):
                title = (c.get("title") or "").strip() or "(제목 없음)"
                url = (c.get("url") or "").strip()
                if url:
                    # HTML anchor — `_markdown_to_telegram_html` path 에서 살아남음.
                    # 본문이 plain text path 로 전송되면 raw HTML 이 보이지만
                    # 클릭 가능 텍스트로는 노출됨 (telegram 자동 url detection).
                    cite_lines.append(
                        f'[{i+1}] <a href="{url}">{_esc(title)}</a>'
                    )
                else:
                    cite_lines.append(f"[{i+1}] {_esc(title)}")
            if cite_lines:
                body = body + "\n\n참고 문서:\n" + "\n".join(cite_lines)

        # 4096 자 한계 — 초과 시 truncate + 안내
        if len(body) > 4000:
            body = body[:3950] + "\n\n... (응답이 잘렸습니다)"

        return body, citations

    # -------------------------------------------------------------------
    # 운영 도구 — getMe / getWebhookInfo
    # -------------------------------------------------------------------

    async def get_me(self, bot_token: str) -> dict[str, Any]:
        """``getMe`` — 토큰 검증 + 봇 메타 (id / username / is_bot).

        등록 시 ``setWebhook`` 직전에 호출해 잘못된 토큰을 즉시 reject.

        Returns dict ({id, is_bot, first_name, username, ...}).
        실패 시 ``TelegramSendError`` raise.
        """
        if not bot_token:
            raise ValueError("bot_token required for getMe")
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
        except httpx.TimeoutException as e:
            raise TelegramSendError(
                "getMe timeout", status_code=None, retryable=True
            ) from e
        except Exception as e:
            raise TelegramSendError(
                f"getMe network error: {e}", status_code=None, retryable=True
            ) from e

        if resp.status_code == 401:
            raise TelegramSendError(
                "getMe 401 — invalid bot token",
                status_code=401,
                retryable=False,
                permanent_reason="token_revoked",
            )
        if resp.status_code >= 400:
            raise TelegramSendError(
                f"getMe HTTP {resp.status_code}",
                status_code=resp.status_code,
                retryable=resp.status_code >= 500,
            )
        try:
            body = resp.json()
        except Exception as e:
            raise TelegramSendError(
                "getMe response not JSON", status_code=resp.status_code, retryable=False
            ) from e
        if not body.get("ok"):
            raise TelegramSendError(
                f"getMe not ok: {body.get('description')}",
                status_code=resp.status_code,
                retryable=False,
            )
        return body.get("result") or {}

    async def get_webhook_info(self, bot_token: str) -> dict[str, Any]:
        """``getWebhookInfo`` — 운영 모니터링 (pending_update_count / last_error_*).

        admin endpoint / cron 폴링이 사용. 5분 주기로 호출해
        ``pending_update_count > 100`` 또는 ``last_error_date`` 가 최근이면
        alarm.
        """
        if not bot_token:
            raise ValueError("bot_token required for getWebhookInfo")
        url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
        except httpx.TimeoutException as e:
            raise TelegramSendError(
                "getWebhookInfo timeout", status_code=None, retryable=True
            ) from e
        except Exception as e:
            raise TelegramSendError(
                f"getWebhookInfo network error: {e}",
                status_code=None,
                retryable=True,
            ) from e

        if resp.status_code >= 400:
            raise TelegramSendError(
                f"getWebhookInfo HTTP {resp.status_code}",
                status_code=resp.status_code,
                retryable=resp.status_code >= 500,
            )
        try:
            body = resp.json()
        except Exception as e:
            raise TelegramSendError(
                "getWebhookInfo response not JSON",
                status_code=resp.status_code,
                retryable=False,
            ) from e
        if not body.get("ok"):
            raise TelegramSendError(
                f"getWebhookInfo not ok: {body.get('description')}",
                status_code=resp.status_code,
                retryable=False,
            )
        return body.get("result") or {}
