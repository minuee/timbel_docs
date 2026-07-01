"""채널 연결 helper — admin UI 마법사 + script 양쪽이 공유하는 등록 로직.

설계 의도:
- ``scripts/setup/register_telegram_agent.py`` 와 동일한 절차 (getMe → secret 생성 →
  agent_channels UPSERT → setWebhook) 를 함수로 추출. 양쪽이 import 해서 *동일 동작*.
- duplicate 코드 회피 — admin 마법사 / 스크립트 / 향후 SDK 가 모두 단일 진입점.
- side-effect 분리 — 호출자는 (channel_id, kind, external_id, webhook_url, status) 만 받음.

지원 kind:
- telegram: BotFather token + getMe + setWebhook (+ DB UPSERT).
- kakaowork: webhook_url + (선택) auth header 만 저장 (validate 는 Phase 2).
- webhook: 일반 webhook URL 등록. 검증 옵션은 호출자에게 위임.

실패 시 ``ValueError`` (admin 입력 오류 — 400) 또는 ``RuntimeError``
(외부 API 장애 — 502) 로 raise. caller 가 적절한 HTTP status 변환.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.common.crypto.fernet import encrypt_dict
from src.common.logging import get_logger

log = get_logger(__name__)


ChannelKind = Literal["telegram", "kakaowork", "webhook"]


@dataclass
class ChannelConnectResult:
    """채널 연결 결과 — admin UI 가 그대로 사용자에게 노출 가능."""

    channel_id: UUID
    kind: str
    external_id: str
    webhook_url: str | None
    status: str  # 'created' | 'updated'
    bot_username: str | None = None  # telegram 한정
    bot_id: int | None = None  # telegram 한정


# ─── Telegram API helpers (script 와 동일 로직 재사용) ────────────────


async def telegram_get_me(bot_token: str) -> dict[str, Any]:
    """``getMe`` — token 검증 + bot 메타 (id / username / is_bot).

    - 401 → ``ValueError`` (token 폐기 — admin 에 즉시 안내).
    - 5xx / 타임아웃 → ``RuntimeError`` (Telegram 측 장애).
    """
    if not bot_token:
        raise ValueError("bot_token is required")
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as e:
        raise RuntimeError("getMe timeout") from e
    except Exception as e:
        raise RuntimeError(f"getMe network error: {e}") from e

    if resp.status_code == 401:
        raise ValueError("invalid bot token (401 from getMe)")
    if resp.status_code >= 400:
        raise RuntimeError(f"getMe HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"getMe not ok: {body.get('description')}")
    result = body.get("result") or {}
    if not result.get("is_bot"):
        raise ValueError("token is not a bot account")
    return result


async def telegram_set_webhook(
    bot_token: str, webhook_url: str, secret_token: str
) -> dict[str, Any]:
    """``setWebhook`` + secret_token 동기화. drop_pending_updates=True."""
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "drop_pending_updates": True,
        "allowed_updates": ["message", "edited_message", "callback_query"],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.TimeoutException as e:
        raise RuntimeError("setWebhook timeout") from e
    except Exception as e:
        raise RuntimeError(f"setWebhook network error: {e}") from e

    if resp.status_code >= 400:
        raise RuntimeError(
            f"setWebhook HTTP {resp.status_code}: {resp.text[:200]}"
        )
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"setWebhook not ok: {body.get('description')}")
    return body


# ─── DB UPSERT (kind 공통) ────────────────────────────────────────────


async def _upsert_channel(
    engine: AsyncEngine,
    *,
    agent_id: UUID,
    tenant_id: UUID | None,
    kind: str,
    external_id: str,
    config_payload: dict[str, Any],
    is_active: bool = True,
) -> tuple[UUID, str]:
    """``agent_channels`` (kind, external_id) UPSERT.

    같은 (kind, external_id) 가 있으면 *동일 agent* 인지 검증 후 UPDATE.
    다른 agent 에 묶여 있으면 ``ValueError`` — silent rebind 차단.

    return: (channel_id, 'created' | 'updated').
    """
    encrypted = encrypt_dict(config_payload)

    async with engine.begin() as conn:
        existing = (
            await conn.execute(
                text(
                    """
                    SELECT id, agent_id FROM agent_channels
                    WHERE kind = :kind AND external_id = :ext
                    LIMIT 1
                    """
                ),
                {"kind": kind, "ext": external_id},
            )
        ).first()
        if existing:
            channel_id = UUID(str(existing[0]))
            existing_agent_id = UUID(str(existing[1]))
            if existing_agent_id != agent_id:
                raise ValueError(
                    f"channel '{external_id}' (kind={kind}) is already bound to "
                    f"another agent ({existing_agent_id}). Refusing to rebind."
                )
            await conn.execute(
                text(
                    """
                    UPDATE agent_channels
                       SET config_encrypted = :enc,
                           is_active = :active,
                           updated_at = NOW()
                     WHERE id = :cid
                    """
                ),
                {"enc": encrypted, "active": is_active, "cid": channel_id},
            )
            return channel_id, "updated"

        # INSERT
        inserted = (
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_channels
                        (agent_id, kind, config_encrypted, is_active,
                         external_id, created_at, updated_at)
                    VALUES (:aid, :kind, :enc, :active,
                            :ext, NOW(), NOW())
                    RETURNING id
                    """
                ),
                {
                    "aid": agent_id,
                    "kind": kind,
                    "enc": encrypted,
                    "active": is_active,
                    "ext": external_id,
                },
            )
        ).first()
        channel_id = UUID(str(inserted[0]))
        return channel_id, "created"


# ─── webhook URL 결정 ─────────────────────────────────────────────────


def build_telegram_webhook_url(base_url: str, bot_username: str) -> str:
    """``{base}/api/v1/external-agent/telegram/{username}/webhook``."""
    base = base_url.rstrip("/")
    return f"{base}/api/v1/external-agent/telegram/{bot_username}/webhook"


# ─── kind 별 connect ──────────────────────────────────────────────────


async def connect_telegram_channel(
    engine: AsyncEngine,
    *,
    agent_id: UUID,
    tenant_id: UUID | None,
    bot_token: str,
    webhook_base_url: str,
    register_webhook: bool = True,
) -> ChannelConnectResult:
    """Telegram 봇 등록 — getMe → DB UPSERT → setWebhook.

    register_webhook=False 면 setWebhook 호출을 생략 (테스트 / 분리 등록).
    """
    # 1. getMe — token 검증 + bot 메타.
    me = await telegram_get_me(bot_token)
    bot_id = int(me.get("id"))
    bot_username = (me.get("username") or "").lower().lstrip("@")
    if not bot_username:
        raise ValueError("bot has no username (BotFather 에서 username 설정 필요)")

    # 2. webhook secret 생성.
    webhook_secret = secrets.token_urlsafe(32)

    # 3. DB UPSERT (config_encrypted = bot_token + webhook_secret + bot_id).
    config_payload = {
        "bot_token": bot_token,
        "webhook_secret": webhook_secret,
        "bot_id": bot_id,
        "bot_username": bot_username,
    }
    channel_id, action = await _upsert_channel(
        engine,
        agent_id=agent_id,
        tenant_id=tenant_id,
        kind="telegram",
        external_id=bot_username,
        config_payload=config_payload,
        is_active=True,
    )

    webhook_url: str | None = None
    if register_webhook:
        if not webhook_base_url:
            raise ValueError(
                "webhook_base_url is required (env EXTERNAL_AGENT_WEBHOOK_BASE_URL "
                "또는 admin 입력 — cloudflared trycloudflare URL 등)"
            )
        webhook_url = build_telegram_webhook_url(webhook_base_url, bot_username)
        await telegram_set_webhook(bot_token, webhook_url, webhook_secret)
        log.info(
            "telegram_channel_connected agent_id=%s bot=@%s action=%s url=%s",
            agent_id, bot_username, action, webhook_url,
        )
    else:
        log.info(
            "telegram_channel_connected agent_id=%s bot=@%s action=%s "
            "(setWebhook skipped)",
            agent_id, bot_username, action,
        )

    return ChannelConnectResult(
        channel_id=channel_id,
        kind="telegram",
        external_id=bot_username,
        webhook_url=webhook_url,
        status=action,
        bot_username=bot_username,
        bot_id=bot_id,
    )


async def connect_kakaowork_channel(
    engine: AsyncEngine,
    *,
    agent_id: UUID,
    tenant_id: UUID | None,
    webhook_url: str,
    secret: str | None = None,
) -> ChannelConnectResult:
    """KakaoWork webhook URL 등록 (Phase 2 placeholder — validate 미수행).

    DB 만 INSERT. 검증/실제 응답은 향후 KakaoWork adapter 가 처리.
    external_id = webhook_url 의 마지막 path segment 또는 hash 기반.
    """
    if not webhook_url:
        raise ValueError("webhook_url is required for kakaowork")
    # external_id — webhook URL 끝부분 hash (충돌 방지).
    import hashlib
    external_id = "kw-" + hashlib.sha1(
        webhook_url.encode("utf-8")
    ).hexdigest()[:16]
    config_payload: dict[str, Any] = {
        "webhook_url": webhook_url,
    }
    if secret:
        config_payload["secret"] = secret
    channel_id, action = await _upsert_channel(
        engine,
        agent_id=agent_id,
        tenant_id=tenant_id,
        kind="kakaowork",
        external_id=external_id,
        config_payload=config_payload,
        is_active=True,
    )
    log.info(
        "kakaowork_channel_connected agent_id=%s ext=%s action=%s",
        agent_id, external_id, action,
    )
    return ChannelConnectResult(
        channel_id=channel_id,
        kind="kakaowork",
        external_id=external_id,
        webhook_url=webhook_url,
        status=action,
    )


async def connect_webhook_channel(
    engine: AsyncEngine,
    *,
    agent_id: UUID,
    tenant_id: UUID | None,
    webhook_url: str,
    auth_headers: dict[str, str] | None = None,
    secret: str | None = None,
) -> ChannelConnectResult:
    """일반 webhook URL 등록 — admin 이 외부 시스템과 연결.

    external_id = webhook URL hash. config_encrypted 에 url + auth_headers 저장.
    """
    if not webhook_url:
        raise ValueError("webhook_url is required for webhook")
    import hashlib
    external_id = "wh-" + hashlib.sha1(
        webhook_url.encode("utf-8")
    ).hexdigest()[:16]
    config_payload: dict[str, Any] = {
        "webhook_url": webhook_url,
    }
    if auth_headers:
        config_payload["auth_headers"] = auth_headers
    if secret:
        config_payload["secret"] = secret
    channel_id, action = await _upsert_channel(
        engine,
        agent_id=agent_id,
        tenant_id=tenant_id,
        kind="webhook",
        external_id=external_id,
        config_payload=config_payload,
        is_active=True,
    )
    log.info(
        "webhook_channel_connected agent_id=%s ext=%s action=%s",
        agent_id, external_id, action,
    )
    return ChannelConnectResult(
        channel_id=channel_id,
        kind="webhook",
        external_id=external_id,
        webhook_url=webhook_url,
        status=action,
    )
