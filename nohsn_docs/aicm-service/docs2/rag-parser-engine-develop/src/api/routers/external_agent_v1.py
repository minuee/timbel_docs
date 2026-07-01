"""/api/v1/external/agent/{agent_id}/* — External Agent 외부 호출자 측 (API key).

JWT 가 없는 외부 시스템 (콜센터봇, slack/webhook integration 등) 이 발급받은
API key 로 agent 와 대화하기 위한 endpoint.

Endpoint:
- ``POST /api/v1/external/agent/{agent_id}/message``
  - Auth: ``Authorization: Bearer <key>`` (preferred) 또는 ``X-Agent-API-Key: <key>``
  - Response:
    - ``Accept: text/event-stream`` → SSE (engine event 그대로 전달)
    - 그 외 → ``application/json`` ({message, intent, session_id})
  - 매 호출마다 ``agent_message_log`` 1행 INSERT (status=ok|error, latency_ms)

Phase P3.B (KMS-Plus). 운영자 측은 ``agents_v1.py`` 참조.

Phase 1 Task 6 (KMS-Plus):
- ``POST /api/v1/external-agent/{kind}/{external_id}/webhook``
  - 외부 채널 (Telegram 등) webhook 수신.
  - channel 조회 → config decrypt → adapter.parse_inbound → agent load →
    AgentContext → _handle_external_agent_message → adapter.send_outbound.

TODO(P3.B+1): per-api-key rate limit (현재는 미적용 — slowapi key_func 가 IP
기반이라 api_key_id 단위 limit 은 별도 미들웨어 또는 redis counter 가 필요).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from src.agent_framework.api.dependencies import get_agent_engine
from src.agent_framework.observability.latency_probe import LatencyProbe
from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.sender_context import SenderContext
from src.common.config import settings
from src.common.feature_flags import FeatureFlag, is_enabled

log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/external/agent", tags=["external-agent-v1"])


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


# ---------------------------------------------------------------------------
# L9 (2026-05-07) — webhook overhead 단축 LRU 캐시.
# webhook 진입마다 (kind, external_id) → channel + decrypted config + agent
# 매번 조회. 운영 환경에서 webhook 빈도 높음 (수십 / sec). 5 분 TTL 캐시.
# config 변경 / 봇 token rotate 시 admin 측 invalidate (별도 endpoint 가능).
# ---------------------------------------------------------------------------

_CHANNEL_CACHE_TTL_S = 300.0   # 5 분
_CHANNEL_CACHE_MAX = 256       # bot 수 상한 가정
_channel_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _channel_cache_get(kind: str, external_id: str) -> dict[str, Any] | None:
    key = (kind, external_id)
    entry = _channel_cache.get(key)
    if entry is None:
        return None
    expires, data = entry
    if expires < time.time():
        _channel_cache.pop(key, None)
        return None
    return data


def _channel_cache_put(kind: str, external_id: str, data: dict[str, Any]) -> None:
    if len(_channel_cache) >= _CHANNEL_CACHE_MAX:
        # 만료 정리. 그래도 넘치면 oldest drop.
        now = time.time()
        stale = [k for k, v in _channel_cache.items() if v[0] < now]
        for k in stale:
            _channel_cache.pop(k, None)
        if len(_channel_cache) >= _CHANNEL_CACHE_MAX:
            oldest_k = min(
                _channel_cache.keys(), key=lambda k: _channel_cache[k][0]
            )
            _channel_cache.pop(oldest_k, None)
    _channel_cache[(kind, external_id)] = (
        time.time() + _CHANNEL_CACHE_TTL_S,
        data,
    )


def invalidate_channel_cache(kind: str | None = None, external_id: str | None = None) -> int:
    """admin 이 channel config / token rotate 시 호출. 반환=invalidated count."""
    if kind is not None and external_id is not None:
        return 1 if _channel_cache.pop((kind, external_id), None) else 0
    n = len(_channel_cache)
    _channel_cache.clear()
    return n


# agent_id → (AgentContext, tenant_id, is_active) 캐시.
# AgentContext 는 frozen dataclass 라 thread-safe.
_AGENT_CACHE_TTL_S = 300.0
_AGENT_CACHE_MAX = 256
_agent_cache: dict[UUID, tuple[float, dict[str, Any]]] = {}


def _agent_cache_get(agent_id: UUID) -> dict[str, Any] | None:
    entry = _agent_cache.get(agent_id)
    if entry is None:
        return None
    expires, data = entry
    if expires < time.time():
        _agent_cache.pop(agent_id, None)
        return None
    return data


def _agent_cache_put(agent_id: UUID, data: dict[str, Any]) -> None:
    if len(_agent_cache) >= _AGENT_CACHE_MAX:
        now = time.time()
        stale = [k for k, v in _agent_cache.items() if v[0] < now]
        for k in stale:
            _agent_cache.pop(k, None)
        if len(_agent_cache) >= _AGENT_CACHE_MAX:
            oldest_k = min(_agent_cache.keys(), key=lambda k: _agent_cache[k][0])
            _agent_cache.pop(oldest_k, None)
    _agent_cache[agent_id] = (time.time() + _AGENT_CACHE_TTL_S, data)


def invalidate_agent_cache(agent_id: UUID | None = None) -> int:
    if agent_id is not None:
        return 1 if _agent_cache.pop(agent_id, None) else 0
    n = len(_agent_cache)
    _agent_cache.clear()
    return n


# ---------------------------------------------------------------------------
# Auth — API key
# ---------------------------------------------------------------------------


def _extract_api_key(authorization: str | None, x_agent_api_key: str | None) -> str:
    """Authorization: Bearer <key> 우선, 없으면 X-Agent-API-Key. 없으면 401."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    if x_agent_api_key:
        token = x_agent_api_key.strip()
        if token:
            return token
    raise HTTPException(401, "missing api key (Authorization: Bearer ... or X-Agent-API-Key)")


async def _verify_api_key(plaintext: str) -> tuple[UUID, UUID, str]:
    """plaintext API key → (api_key_id, agent_id, key_hash).

    1. prefix (앞 12자) 로 후보 행 조회 (active 만).
    2. 각 후보의 key_hash 에 대해 bcrypt.checkpw — 일치 1건 발견 시 해당 row 반환.
    3. 일치 없음 → 401.
    """
    import bcrypt

    if len(plaintext) < 12:
        raise HTTPException(401, "invalid api key format")
    prefix = plaintext[:12]
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, agent_id, key_hash
                    FROM agent_api_keys
                    WHERE key_prefix = :p AND revoked_at IS NULL
                    """
                ),
                {"p": prefix},
            )
        ).fetchall()
    if not rows:
        raise HTTPException(401, "invalid api key")
    plain_b = plaintext.encode("utf-8")
    # 충돌 매우 드문 케이스 — 여러 row 일 때만 순회.
    for row in rows:
        try:
            if bcrypt.checkpw(plain_b, row[2].encode("utf-8")):
                return UUID(str(row[0])), UUID(str(row[1])), row[2]
        except (ValueError, TypeError):
            continue
    raise HTTPException(401, "invalid api key")


async def _load_agent_row(agent_id: UUID) -> dict[str, Any]:
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id, tenant_id, name, persona, system_prompt, is_active
                    FROM agents WHERE id = :aid LIMIT 1
                    """
                ),
                {"aid": agent_id},
            )
        ).first()
    if not row:
        raise HTTPException(404, "agent not found")
    return {
        "id": UUID(str(row[0])),
        "tenant_id": UUID(str(row[1])),
        "name": row[2],
        "persona": row[3] or "",
        "system_prompt": row[4] or "",
        "is_active": bool(row[5]),
    }


async def _touch_last_used(api_key_id: UUID) -> None:
    eng = _get_engine()
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text("UPDATE agent_api_keys SET last_used_at = now() WHERE id = :kid"),
                {"kid": api_key_id},
            )
    except Exception:
        # last_used_at 갱신 실패는 호출 차단 사유 아님.
        pass


def _compose(persona: str, system_prompt: str, user_text: str) -> str:
    parts: list[str] = []
    p = (persona or "").strip()
    s = (system_prompt or "").strip()
    if p:
        parts.append(f"[페르소나]\n{p}")
    if s:
        parts.append(f"[추가 지시]\n{s}")
    if not parts:
        return user_text
    parts.append(f"[사용자]: {user_text}")
    return "\n\n".join(parts)


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Phase 1.5A Task 7 — SenderContext factory (channel webhook)
# ---------------------------------------------------------------------------


def _build_sender_context_from_channel(
    *,
    mapping: Any,
    tenant_id: UUID,
    channel_kind: str,
    role: str | None = None,
) -> SenderContext:
    """channel webhook 의 mapping → SenderContext.

    mapping.internal_user_id (또는 internal_account_id) 둘 다 NULL → tier=guest.
    매핑되어 있으면 role 인자로 admin/owner 확인:
      - admin/owner → tier=admin
      - 그 외        → tier=verified

    verified_via 는 mapping.verified_via (없으면 'channel_mapping') — Phase 1
    매핑은 admin 수동 update 가 기본 (channel_mapping). Phase 2 이후 phone_otp
    같은 명시적 검증 경로가 추가되면 mapping 컬럼이 채워진다.
    """
    _internal_user = getattr(mapping, "internal_user_id", None)
    _internal_account = getattr(mapping, "internal_account_id", None)
    if _internal_user is None and _internal_account is None:
        tier = "guest"
        verified_via: str | None = None
    else:
        if (role or "").lower() in ("admin", "owner"):
            tier = "admin"
        else:
            tier = "verified"
        verified_via = getattr(mapping, "verified_via", None) or "channel_mapping"
    return SenderContext(
        tier=tier,
        internal_user_id=_internal_user,
        tenant_id=tenant_id,
        channel_kind=channel_kind,
        verified_via=verified_via,
        confirm_token=None,
    )


async def _write_log(
    *,
    agent_id: UUID,
    api_key_id: UUID | None,
    channel: str | None,
    external_session_id: str | None,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    status: str,
    latency_ms: int,
) -> None:
    """agent_message_log 1행 INSERT.

    ``api_key_id`` 는 nullable — webhook flow (API key 미사용) 에서 None 전달.
    호출자: external_message (api_key 인증) / channel_webhook (kind 라우팅).
    """
    eng = _get_engine()
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_message_log
                      (agent_id, api_key_id, channel, external_session_id,
                       request, response, status, latency_ms)
                    VALUES
                      (:agent_id, :key_id, :channel, :ext_sid,
                       CAST(:req AS jsonb),
                       CAST(:resp AS jsonb),
                       :status, :lat)
                    """
                ),
                {
                    "agent_id": agent_id,
                    "key_id": api_key_id,
                    "channel": channel,
                    "ext_sid": external_session_id,
                    "req": json.dumps(request_payload, ensure_ascii=False),
                    "resp": None if response_payload is None
                            else json.dumps(response_payload, ensure_ascii=False),
                    "status": status,
                    "lat": latency_ms,
                },
            )
    except Exception:
        # 로깅 실패는 응답 망치지 않음 — silent drop (운영 알람은 별도 metric 으로).
        pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ExternalMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
    channel: str | None = None
    external_session_id: str | None = None


# ---------------------------------------------------------------------------
# /message
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/message")
async def external_message(
    agent_id: str,
    body: ExternalMessageRequest,
    request: Request,
    authorization: str | None = Header(None),
    x_agent_api_key: str | None = Header(None, alias="X-Agent-API-Key"),
    accept: str | None = Header(None),
    engine: AgentEngine = Depends(get_agent_engine),
):
    """외부 호출 — API key 인증, agent persona/system_prompt prepend, SSE 또는 JSON 응답.

    Accept: text/event-stream → SSE. 그 외 → JSON.

    매 호출 종료 시 agent_message_log 1행 INSERT (status=ok|error, latency_ms).
    """
    # 1) URL agent_id 파싱
    try:
        url_agent_id = UUID(agent_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid agent_id: {e}") from e

    # 2) API key 인증
    plaintext = _extract_api_key(authorization, x_agent_api_key)
    api_key_id, key_agent_id, _ = await _verify_api_key(plaintext)

    # 3) URL 의 agent_id 와 키의 agent_id 일치 확인
    if url_agent_id != key_agent_id:
        raise HTTPException(403, "api key does not belong to this agent")

    # 4) agent active 확인
    agent = await _load_agent_row(url_agent_id)
    if not agent["is_active"]:
        raise HTTPException(403, "agent is inactive")

    # 5) last_used_at 갱신 (best effort, fire and forget — 응답 latency 영향 X)
    asyncio.create_task(_touch_last_used(api_key_id))

    # 6) 메시지 합성 + session_id 결정
    sid = body.session_id or f"ext-{url_agent_id}-{int(time.time()*1000)}"
    composed = _compose(agent["persona"], agent["system_prompt"], body.message)
    request_payload = {
        "message": body.message,
        "session_id": body.session_id,
        "channel": body.channel,
        "external_session_id": body.external_session_id,
    }

    wants_sse = (accept or "").lower().startswith("text/event-stream")
    t0 = time.perf_counter()

    # ---- SSE 모드 ----
    if wants_sse:
        # Latency P0-1 (2026-05-07) — external agent SSE 응답에 phase 별 측정.
        # flag off 시 byte-equal (probe=None 분기 미진입).
        _probe_enabled: bool = is_enabled(
            FeatureFlag.LATENCY_PROBE_SSE, tenant_id=str(agent["tenant_id"])
        )

        async def stream():
            collected: list[str] = []
            captured_intent: str | None = None
            err: str | None = None
            probe: LatencyProbe | None = None
            _turn_started: float = 0.0
            if _probe_enabled:
                probe = LatencyProbe()
                _turn_started = time.time()
            # D33 §3 — bind_agent_scope() 실 호출 site (external_agent SSE).
            # url_agent_id 가 검증된 caller 의 agent_id — 명시적 agent scope wrap.
            from src.api.middleware.rls_context import bind_agent_scope as _bind_scope

            async def _scoped_engine_turn():
                async with _bind_scope(str(url_agent_id), str(agent["tenant_id"])):
                    async for _it_item in engine.turn(
                        sid, str(agent["tenant_id"]), composed
                    ):
                        yield _it_item

            try:
                async for item in _scoped_engine_turn():
                    if probe is not None:
                        try:
                            probe.consume_event(item)
                        except Exception:
                            pass
                    ev = item.get("event", "message")
                    data = item.get("data", {}) or {}
                    if ev in ("token", "delta") and isinstance(data, dict):
                        chunk = data.get("text") or data.get("delta") or ""
                        if chunk:
                            collected.append(chunk)
                    if ev == "intent" and isinstance(data, dict):
                        intents = data.get("intents") or []
                        if intents and captured_intent is None:
                            first = intents[0]
                            captured_intent = (
                                first if isinstance(first, str)
                                else (first or {}).get("name")
                            )
                    yield _sse(ev, data)
                # P0-1: turn 종료 후 latency_probe payload — done 뒤 observability event.
                if probe is not None:
                    try:
                        probe.record_phase("engine_turn", _turn_started, time.time())
                        probe.finalize_derived_phases(_turn_started)
                        yield _sse("latency_probe", probe.to_sse_payload())
                    except Exception:
                        pass
            except Exception as e:  # noqa: BLE001
                err = str(e)
                yield _sse("error", {"detail": err})
            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                response_payload = {
                    "message": "".join(collected).strip(),
                    "intent": captured_intent,
                    "session_id": sid,
                }
                await _write_log(
                    agent_id=url_agent_id,
                    api_key_id=api_key_id,
                    channel=body.channel,
                    external_session_id=body.external_session_id,
                    request_payload=request_payload,
                    response_payload=response_payload,
                    status="error" if err else "ok",
                    latency_ms=latency_ms,
                )

        return StreamingResponse(stream(), media_type="text/event-stream")

    # ---- JSON 모드 ----
    collected: list[str] = []
    captured_intent: str | None = None
    err: str | None = None

    # D33 §3 — bind_agent_scope() — JSON 모드도 동일 wrap.
    from src.api.middleware.rls_context import bind_agent_scope as _bind_scope_json

    async def _scoped_engine_turn_json():
        async with _bind_scope_json(str(url_agent_id), str(agent["tenant_id"])):
            async for _it_item in engine.turn(
                sid, str(agent["tenant_id"]), composed
            ):
                yield _it_item

    try:
        async for item in _scoped_engine_turn_json():
            ev = item.get("event", "message")
            data = item.get("data", {}) or {}
            if ev in ("token", "delta") and isinstance(data, dict):
                chunk = data.get("text") or data.get("delta") or ""
                if chunk:
                    collected.append(chunk)
            if ev == "intent" and isinstance(data, dict):
                intents = data.get("intents") or []
                if intents and captured_intent is None:
                    first = intents[0]
                    captured_intent = (
                        first if isinstance(first, str)
                        else (first or {}).get("name")
                    )
    except Exception as e:  # noqa: BLE001
        err = str(e)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    assistant_text = "".join(collected).strip()
    response_payload: dict[str, Any] = {
        "message": assistant_text,
        "intent": captured_intent,
        "session_id": sid,
    }
    if err:
        response_payload["error"] = err

    await _write_log(
        agent_id=url_agent_id,
        api_key_id=api_key_id,
        channel=body.channel,
        external_session_id=body.external_session_id,
        request_payload=request_payload,
        response_payload=response_payload,
        status="error" if err else "ok",
        latency_ms=latency_ms,
    )

    if err:
        # 502 — engine 내부 오류. body 는 디버깅용.
        return JSONResponse(response_payload, status_code=502)
    return response_payload


# ---------------------------------------------------------------------------
# OpenAI Chat Completions 호환 endpoint (dispatch #150, 2026-05-07)
#
# spec: docs/superpowers/specs/2026-05-07-openai-compatible-endpoint.md
# 기존 /message 와 별도 — 회귀 0. OpenAI Python/JS SDK / LangChain / Vercel AI
# SDK 등이 base_url 만 바꾸면 그대로 호출 가능.
# ---------------------------------------------------------------------------


def _openai_error_body(message: str, type_: str, *, code: str | None = None,
                       param: str | None = None) -> dict[str, Any]:
    """OpenAI 형식 error envelope. GPT-5 P0/3, P1/9 fix 반영."""
    return {
        "error": {
            "message": message,
            "type": type_,
            "param": param,
            "code": code,
        }
    }


def _count_tokens_estimate(text: str) -> int:
    """tiktoken cl100k_base 추정. 실패 시 fallback 휴리스틱.

    GPT-5 P1/12 — CJK 는 char//2, 그 외 char//4.
    """
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore[import-not-found]
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # CJK ratio 가 일정 비율 이상이면 char//2, 아니면 char//4.
        cjk = sum(1 for c in text if "　" <= c <= "鿿" or "가" <= c <= "힯")
        if cjk * 2 > len(text):
            return max(1, len(text) // 2)
        return max(1, len(text) // 4)


def _count_messages_tokens(messages: list[dict]) -> int:
    """messages 배열의 prompt token 추정. role 헤더 +3 token / 메시지 (OpenAI 권장)."""
    total = 0
    for msg in messages:
        total += 3
        total += _count_tokens_estimate(str(msg.get("role") or ""))
        content = msg.get("content")
        if isinstance(content, str):
            total += _count_tokens_estimate(content)
        elif isinstance(content, list):
            # multimodal — text part 만 추정 (router 가 400 으로 거절하지만 안전망)
            for part in content:
                if isinstance(part, dict):
                    text_val = part.get("text") or ""
                    if isinstance(text_val, str):
                        total += _count_tokens_estimate(text_val)
    return total + 3  # 응답 priming


def _build_effective_prompt_from_messages(
    *, persona: str, system_prompt: str, messages: list[dict], user_text: str,
) -> str:
    """OpenAI messages → engine 의 effective prompt 합성.

    현 engine.turn 은 단일 user_text 만 받으므로 history 를 [대화 이력] 섹션으로
    prepend.

    persona / system_prompt: agents 테이블의 frozen 값 — 우선.
    messages 의 system role 은 [추가 시스템] 으로 합쳐서 전달 (admin 의도 존중).
    """
    parts: list[str] = []
    p = (persona or "").strip()
    s = (system_prompt or "").strip()
    if p:
        parts.append(f"[페르소나]\n{p}")
    if s:
        parts.append(f"[추가 지시]\n{s}")

    # messages 의 system role 만 모음 (마지막 user 제외 history 에서).
    extra_systems: list[str] = []
    history: list[str] = []
    for msg in messages:
        role = msg.get("role") or ""
        content_raw = msg.get("content")
        if not isinstance(content_raw, str):
            continue
        content = content_raw.strip()
        if not content:
            continue
        if role == "system":
            extra_systems.append(content)
        elif role in ("user", "assistant"):
            history.append(f"{role}: {content}")
        # tool / function 은 무시 (OpenAI tool calling 미지원).

    if extra_systems:
        parts.append("[추가 시스템]\n" + "\n\n".join(extra_systems))
    if history:
        parts.append("[대화 이력]\n" + "\n".join(history))
    parts.append(f"[현재 사용자 발화]: {user_text}")
    return "\n\n".join(parts)


def _make_chunk(*, id_: str, created: int, model: str,
                delta: dict, finish_reason: str | None) -> bytes:
    """OpenAI chat.completion.chunk SSE 한 줄 — 'data: <json>\\n\\n'."""
    payload = {
        "id": id_,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/{agent_id}/chat/completions")
async def chat_completions(
    agent_id: str,
    request: Request,
    authorization: str | None = Header(None),
    x_agent_api_key: str | None = Header(None, alias="X-Agent-API-Key"),
    engine: AgentEngine = Depends(get_agent_engine),
):
    """OpenAI Chat Completions 호환 endpoint.

    spec: docs/superpowers/specs/2026-05-07-openai-compatible-endpoint.md
    GPT-5 P0/P1 fix 반영.
    """
    import uuid

    # body parse — pydantic schema. 알 수 없는 OpenAI 필드 (top_p 등) 도 수용 (extra=allow).
    try:
        body_json = await request.json()
    except Exception:
        return JSONResponse(
            _openai_error_body("invalid JSON body", "invalid_request_error"),
            status_code=400,
        )

    # 1) URL agent_id 파싱
    try:
        url_agent_id = UUID(agent_id)
    except ValueError:
        return JSONResponse(
            _openai_error_body("invalid agent_id", "invalid_request_error"),
            status_code=400,
        )

    # 2) API key 인증 — generic 401 (P2/16 tenant enumeration 회피)
    try:
        plaintext = _extract_api_key(authorization, x_agent_api_key)
        api_key_id, key_agent_id, _ = await _verify_api_key(plaintext)
    except HTTPException:
        return JSONResponse(
            _openai_error_body(
                "Invalid authentication credentials",
                "authentication_error",
                code="invalid_api_key",
            ),
            status_code=401,
        )

    # 3) URL agent_id 와 key.agent_id 일치 — generic 403
    if url_agent_id != key_agent_id:
        return JSONResponse(
            _openai_error_body("Permission denied", "insufficient_permissions"),
            status_code=403,
        )

    # 4) agent 활성 — generic 403
    try:
        agent = await _load_agent_row(url_agent_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return JSONResponse(
                _openai_error_body("Permission denied", "insufficient_permissions"),
                status_code=403,
            )
        raise
    if not agent["is_active"]:
        return JSONResponse(
            _openai_error_body("Permission denied", "insufficient_permissions"),
            status_code=403,
        )

    # 5) messages 검증 (GPT-5 P0/6)
    raw_messages = body_json.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return JSONResponse(
            _openai_error_body("messages is required and must be a non-empty array",
                               "invalid_request_error", param="messages"),
            status_code=400,
        )
    # role / content 검증
    cleaned_messages: list[dict] = []
    for i, msg in enumerate(raw_messages):
        if not isinstance(msg, dict):
            return JSONResponse(
                _openai_error_body(f"messages[{i}] must be an object",
                                   "invalid_request_error", param=f"messages[{i}]"),
                status_code=400,
            )
        role = msg.get("role")
        if role not in ("system", "user", "assistant", "tool", "function"):
            return JSONResponse(
                _openai_error_body(f"messages[{i}].role invalid: {role!r}",
                                   "invalid_request_error", param=f"messages[{i}].role"),
                status_code=400,
            )
        content = msg.get("content")
        if isinstance(content, list):
            return JSONResponse(
                _openai_error_body(
                    "multimodal content array not supported — please send content as string",
                    "invalid_request_error",
                    param=f"messages[{i}].content",
                ),
                status_code=400,
            )
        if content is not None and not isinstance(content, str):
            return JSONResponse(
                _openai_error_body(
                    f"messages[{i}].content must be string or null",
                    "invalid_request_error",
                    param=f"messages[{i}].content",
                ),
                status_code=400,
            )
        cleaned_messages.append({"role": role, "content": content})

    # 마지막 메시지 role check + user_text 추출
    last = cleaned_messages[-1]
    if last["role"] == "user":
        user_text = (last.get("content") or "").strip()
        history_msgs = cleaned_messages[:-1]
    elif last["role"] == "assistant":
        # 마지막이 assistant — 직전 user 를 user_text 로 사용 (GPT-5 P0/6).
        user_idx: int | None = None
        for j in range(len(cleaned_messages) - 2, -1, -1):
            if cleaned_messages[j]["role"] == "user":
                user_idx = j
                break
        if user_idx is None:
            return JSONResponse(
                _openai_error_body(
                    "messages must contain at least one user message",
                    "invalid_request_error", param="messages",
                ),
                status_code=400,
            )
        user_text = (cleaned_messages[user_idx].get("content") or "").strip()
        # history 에는 last (assistant) 도 포함 (대화 이력 으로).
        history_msgs = cleaned_messages[:user_idx] + cleaned_messages[user_idx+1:]
    else:
        return JSONResponse(
            _openai_error_body(
                f"last message role must be 'user' or 'assistant', got {last['role']!r}",
                "invalid_request_error", param="messages",
            ),
            status_code=400,
        )

    if not user_text:
        return JSONResponse(
            _openai_error_body(
                "user message content is empty",
                "invalid_request_error", param="messages",
            ),
            status_code=400,
        )

    # 6) last_used_at 갱신 (best-effort)
    asyncio.create_task(_touch_last_used(api_key_id))

    # 7) session_id — uuid 로 동시 호출 충돌 회피 (P2/24)
    session_id = f"openai-{url_agent_id}-{uuid.uuid4().hex[:12]}"
    response_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    response_model = f"agent-{url_agent_id}"
    created_unix = int(time.time())

    # 8) effective prompt 합성
    effective_prompt = _build_effective_prompt_from_messages(
        persona=agent["persona"],
        system_prompt=agent["system_prompt"],
        messages=history_msgs,
        user_text=user_text,
    )

    request_payload = {
        "messages_count": len(cleaned_messages),
        "stream": bool(body_json.get("stream", False)),
        "model": body_json.get("model"),
        "user_text_preview": user_text[:300],
    }

    # 9) prompt token 추정 (GPT-5 P1/11 — OpenAI-style messages 기준)
    prompt_tokens = _count_messages_tokens(cleaned_messages)

    stream_mode = bool(body_json.get("stream", False))
    t0 = time.perf_counter()

    # ============================================================
    # Stream 모드
    # ============================================================
    if stream_mode:
        async def sse_stream():
            collected: list[str] = []
            captured_citations: list[dict] = []
            err: str | None = None
            sent_role_chunk = False
            try:
                # 첫 chunk: role only (P1/10)
                yield _make_chunk(
                    id_=response_id, created=created_unix, model=response_model,
                    delta={"role": "assistant"}, finish_reason=None,
                )
                sent_role_chunk = True

                # D33 §3 — bind_agent_scope() — OpenAI compatible SSE.
                from src.api.middleware.rls_context import (
                    bind_agent_scope as _bind_scope_oai_sse,
                )

                async def _scoped_turn_oai_sse():
                    async with _bind_scope_oai_sse(
                        str(url_agent_id), str(agent["tenant_id"])
                    ):
                        async for _it_item in engine.turn(
                            session_id, str(agent["tenant_id"]), effective_prompt
                        ):
                            yield _it_item

                async for item in _scoped_turn_oai_sse():
                    ev = item.get("event", "message")
                    data = item.get("data", {}) or {}
                    if ev in ("token", "delta") and isinstance(data, dict):
                        chunk = data.get("text") or data.get("delta") or ""
                        if chunk:
                            collected.append(chunk)
                            yield _make_chunk(
                                id_=response_id, created=created_unix,
                                model=response_model,
                                delta={"content": chunk}, finish_reason=None,
                            )
                    elif ev == "citations" and isinstance(data, dict):
                        # 2026-05-08 — citation 인라인 링크 (사용자 절칙).
                        # OpenAI compatible 응답 종료 직전 별도 chunk 로 emit.
                        items = data.get("items") or []
                        if isinstance(items, list):
                            captured_citations = items
                # 2026-05-08 — citations 가 있으면 종료 직전 비표준 x_citations
                # delta chunk 를 한 번 emit (GPT-5 P1: SDK 가 무시하지만 호환).
                # GPT-5 diff verdict (Phase 6) — strict decoder 보호 위해 env
                # flag 로 옵트인. ENABLE_OPENAI_X_CITATIONS_STREAM=1 (default OFF)
                # 클라이언트 합의 후 활성. non-stream 은 root-level x_citations
                # 라 호환성 안전하므로 항상 emit.
                import os as _os_x_cite
                _stream_x_cite_enabled = _os_x_cite.environ.get(
                    "ENABLE_OPENAI_X_CITATIONS_STREAM", "0"
                ).lower() in ("1", "true", "yes")
                if captured_citations and _stream_x_cite_enabled:
                    try:
                        x_chunk_payload = {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created_unix,
                            "model": response_model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "x_citations": captured_citations[:10],
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield (
                            f"data: {json.dumps(x_chunk_payload, ensure_ascii=False)}"
                            f"\n\n"
                        ).encode("utf-8")
                    except Exception:  # noqa: BLE001
                        pass
                # 정상 종료 chunk + [DONE]
                yield _make_chunk(
                    id_=response_id, created=created_unix, model=response_model,
                    delta={}, finish_reason="stop",
                )
                yield b"data: [DONE]\n\n"
            except Exception as e:  # noqa: BLE001
                err = str(e)
                # GPT-5 P0/1 — error 시 [DONE] / finish_reason=error 비표준 X.
                # OpenAI SSE error 옵션 (data: {"error": {...}}) 1줄 emit 후 close.
                # GPT-5 Phase 5 P2/7 — generic message 만 노출 (internal leak 방지).
                # 상세 err 은 _write_log 에 남김.
                err_payload = _openai_error_body(
                    "Internal server error", "server_error",
                )
                try:
                    yield (f"data: {json.dumps(err_payload, ensure_ascii=False)}"
                           f"\n\n").encode("utf-8")
                except Exception:
                    pass
            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                assistant_text = "".join(collected).strip()
                completion_tokens = _count_tokens_estimate(assistant_text)
                response_payload = {
                    "id": response_id,
                    "stream": True,
                    "message_preview": assistant_text[:300],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                    "sent_role_chunk": sent_role_chunk,
                }
                if err:
                    response_payload["error"] = err
                await _write_log(
                    agent_id=url_agent_id,
                    api_key_id=api_key_id,
                    channel="openai_compatible",
                    external_session_id=None,
                    request_payload=request_payload,
                    response_payload=response_payload,
                    status="error" if err else "ok",
                    latency_ms=latency_ms,
                )

        # GPT-5 Phase 5 P1/2 — Content-Type 에 charset=utf-8 명시.
        return StreamingResponse(
            sse_stream(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ============================================================
    # Non-stream 모드 (JSON)
    # ============================================================
    collected: list[str] = []
    captured_citations: list[dict] = []
    err: str | None = None

    # D33 §3 — bind_agent_scope() — OpenAI compatible JSON.
    from src.api.middleware.rls_context import (
        bind_agent_scope as _bind_scope_oai_json,
    )

    async def _scoped_turn_oai_json():
        async with _bind_scope_oai_json(
            str(url_agent_id), str(agent["tenant_id"])
        ):
            async for _it_item in engine.turn(
                session_id, str(agent["tenant_id"]), effective_prompt
            ):
                yield _it_item

    try:
        async for item in _scoped_turn_oai_json():
            ev = item.get("event", "message")
            data = item.get("data", {}) or {}
            if ev in ("token", "delta") and isinstance(data, dict):
                chunk = data.get("text") or data.get("delta") or ""
                if chunk:
                    collected.append(chunk)
            elif ev == "citations" and isinstance(data, dict):
                # 2026-05-08 — citation 인라인 링크 (사용자 절칙).
                items = data.get("items") or []
                if isinstance(items, list):
                    captured_citations = items
    except Exception as e:  # noqa: BLE001
        err = str(e)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    assistant_text = "".join(collected).strip()
    completion_tokens = _count_tokens_estimate(assistant_text)
    total_tokens = prompt_tokens + completion_tokens

    log_response = {
        "id": response_id,
        "stream": False,
        "message_preview": assistant_text[:300],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }
    if err:
        log_response["error"] = err

    await _write_log(
        agent_id=url_agent_id,
        api_key_id=api_key_id,
        channel="openai_compatible",
        external_session_id=None,
        request_payload=request_payload,
        response_payload=log_response,
        status="error" if err else "ok",
        latency_ms=latency_ms,
    )

    if err:
        # GPT-5 Phase 5 P2/7 — generic message. 상세 err 은 agent_message_log 에.
        return JSONResponse(
            _openai_error_body("Internal server error", "server_error"),
            status_code=502,
        )

    response_body: dict[str, Any] = {
        "id": response_id,
        "object": "chat.completion",
        "created": created_unix,
        "model": response_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": assistant_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }
    # 2026-05-08 — citation 인라인 링크 (사용자 절칙). x_ prefix 비표준 필드 —
    # OpenAI SDK 가 무시하므로 호환성 유지. 클라이언트가 명시적으로 읽으면
    # number / title / url / snippet 활용.
    if captured_citations:
        response_body["x_citations"] = captured_citations[:10]
    return response_body


# ---------------------------------------------------------------------------
# Phase 1 Task 6 — webhook router
# prefix: /api/v1/external-agent
# ---------------------------------------------------------------------------

webhook_router = APIRouter(
    prefix="/api/v1/external-agent",
    tags=["external-agent-webhook"],
)

_webhook_engine: AsyncEngine | None = None


def _get_webhook_engine() -> AsyncEngine:
    global _webhook_engine
    if _webhook_engine is None:
        _webhook_engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _webhook_engine


async def _wh_upsert_user_mapping(
    db: AsyncSession,
    channel_id: UUID,
    external_user_id: str,
    chat_id: str | None = None,
) -> Any:
    """channel_user_mappings 에 (channel_id, chat_id, external_user_id) 단위 upsert.

    Task 8f — chat_id binding 추가 (alembic 062):
    - private chat: chat_id == external_user_id (Telegram 한정).
    - group/supergroup/channel: chat_id != external_user_id — 동일 user 라도
      chat 마다 분리된 mapping (group 별 admin 활성 / metadata 분리).
    - chat_id=None caller (legacy 또는 channel post `from` 부재) → external_user_id
      로 fallback.

    059 (spec 2026-05-07): caller 는 ``mapping.internal_account_id`` 를 즉시
    primitive 로 추출해 session 외부로 들고 나갈 것 (DetachedInstanceError 회피).

    스키마 호환성: ``channel_user_mappings.chat_id`` 컬럼이 alembic 062 적용
    *전* 환경에서는 ORM 모델이 chat_id 를 SET 해도 INSERT 가 실패한다. 이 경우
    fallback 으로 (channel_id, external_user_id) 단일 키 lookup/insert 시도.
    """
    from src.core.models.agent import ChannelUserMapping

    binding_chat_id = chat_id if chat_id is not None else external_user_id

    # 1) (channel_id, chat_id, external_user_id) lookup 시도. chat_id 컬럼
    #    부재 환경 → AttributeError 또는 ProgrammingError. 양쪽 다 fallback.
    mapping = None
    use_chat_id_column = hasattr(ChannelUserMapping, "chat_id")
    if use_chat_id_column:
        try:
            stmt = select(ChannelUserMapping).where(
                ChannelUserMapping.channel_id == channel_id,
                ChannelUserMapping.chat_id == binding_chat_id,
                ChannelUserMapping.external_user_id == external_user_id,
            )
            mapping = (await db.execute(stmt)).scalar_one_or_none()
        except Exception as exc:
            log.warning(
                "channel_user_mappings.chat_id query failed (likely pre-062): %r", exc
            )
            use_chat_id_column = False
    if not use_chat_id_column:
        # legacy lookup — alembic 062 미적용 환경.
        stmt = select(ChannelUserMapping).where(
            ChannelUserMapping.channel_id == channel_id,
            ChannelUserMapping.external_user_id == external_user_id,
        )
        mapping = (await db.execute(stmt)).scalar_one_or_none()

    now = datetime.now(tz=timezone.utc)
    if mapping:
        mapping.last_seen = now
    else:
        kwargs: dict[str, Any] = dict(
            channel_id=channel_id,
            external_user_id=external_user_id,
            internal_user_id=None,
            internal_account_id=None,
            first_seen=now,
            last_seen=now,
        )
        if use_chat_id_column:
            kwargs["chat_id"] = binding_chat_id
        mapping = ChannelUserMapping(**kwargs)
        db.add(mapping)
    await db.flush()
    return mapping


async def _wh_get_agent(db: AsyncSession, agent_id: UUID) -> Any:
    """agents 테이블에서 단건 조회."""
    from src.core.models.agent import Agent

    stmt = select(Agent).where(Agent.id == agent_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _wh_deactivate_user_mapping(
    db: AsyncSession,
    channel_id: UUID,
    external_user_id: str,
    reason: str,
) -> None:
    """403 (bot blocked / kicked) — channel_user_mappings 의 last_seen 만 갱신.

    현재 스키마에는 mapping.is_active 컬럼이 없어 row 삭제는 cascade 위험 큼.
    Phase 1.5 에서는 log + admin alert 로 가시성만 확보. 운영자가
    ``agent_channels.is_active=false`` 토글 또는 mapping 수동 제거 (수동 SQL).
    """
    log.warning(
        "telegram_send_permanent: channel_id=%s external_user=%s reason=%s",
        channel_id,
        external_user_id,
        reason,
    )


async def _wh_deactivate_channel(
    db: AsyncSession,
    channel_id: UUID,
    reason: str,
) -> None:
    """401 (token revoked) — agent_channels.is_active=false 자동 토글.

    bot token 폐기는 channel 전체에 영향 — 모든 사용자에게 발송 불가.
    """
    from src.core.models.agent import AgentChannel

    try:
        chan = await db.get(AgentChannel, channel_id)
        if chan and chan.is_active:
            chan.is_active = False
            await db.flush()
            log.error(
                "agent_channel_auto_deactivated: channel_id=%s reason=%s",
                channel_id,
                reason,
            )
    except Exception:
        log.exception("agent_channel_deactivate_failed channel_id=%s", channel_id)


async def _wh_check_and_record_dedup(
    db: AsyncSession,
    channel_id: UUID,
    idempotency_key: str,
) -> bool:
    """``channel_inbound_dedup`` INSERT — 새 row 면 True, 중복이면 False.

    PostgreSQL ``INSERT ... ON CONFLICT DO NOTHING`` 으로 race 안전.
    True = 처리 진행, False = 이미 처리된 update — caller 가 즉시 204 return.

    테이블 부재 (alembic 060 미적용) 환경 안전 — Exception 시 True 반환
    (best-effort, 기존 동작 보존).
    """
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO channel_inbound_dedup (channel_id, idempotency_key)
                VALUES (:cid, :key)
                ON CONFLICT (channel_id, idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {"cid": str(channel_id), "key": idempotency_key},
        )
        row = result.first()
        # row 가 있으면 새 INSERT 성공 (처리 진행), 없으면 중복.
        return row is not None
    except Exception as exc:
        # 마이그레이션 미적용 / DB 일시 장애 → best-effort 로 처리 진행.
        log.warning("inbound_dedup_check_failed (proceed): %r", exc)
        return True


# ---------------------------------------------------------------------------
# Telegram retry policy — max 3회 exp backoff (1s/2s/4s) + permanent 즉시 fail
# ---------------------------------------------------------------------------
# OOS-guard-and-telegram-retry-fix (2026-05-07) — 사용자 명시:
#   "Telegram retry = max 3회 exponential backoff (1s→2s→4s) + permanent reason
#    즉시 fail"
#
# GPT-5 권고 반영:
# - 어댑터 layer 의 429 retry 는 그대로 유지 (telegram_adapter._send_request).
#   wrapper 는 429 *를 다시 retry 하지 않음* — 이중 retry 회피 (rate limit 가중).
# - jitter ±0.25s 추가 (random.uniform) — 동시 다발 retry 의 thundering herd 차단.
# - permanent reason (token_revoked / bot_blocked / chat_not_found 등) 은 즉시 fail
#   (retry X) — 기존 exc.retryable 시그널 그대로 활용.
# - 메서드 시그니처 유지 — TypeError 발생 시 legacy fallback path 도 그대로.
_TELEGRAM_RETRY_DELAYS = (1.0, 2.0, 4.0)
_TELEGRAM_RETRY_JITTER = 0.25


async def _send_outbound_with_retry(
    adapter: Any,
    *,
    config: dict[str, Any],
    to: str,
    response: Any = None,
    text: str | None = None,
    message_thread_id: int | None = None,
    # 2026-05-08 — citation 인라인 링크 (사용자 절칙). Telegram 어댑터가
    # markdown→HTML 변환 시 [N] 마커를 <a href> 로 wrap.
    citations: list[dict[str, Any]] | None = None,
    # D41 Phase 3 — citation landing 의 HMAC token 생성용 tenant_id.
    # None 이면 어댑터가 link 생성 X (fail-safe).
    tenant_id: Any | None = None,
) -> int:
    """``adapter.send_outbound(...)`` + max 3 retry (exp backoff + jitter).

    재시도 정책:
    - permanent (``exc.retryable=False``) → 즉시 fail (token_revoked /
      bot_blocked / bot_kicked / user_deactivated / chat_not_found).
    - 429 (``exc.status_code=429``) → wrapper 는 retry *안 함* — 어댑터 자체가
      이미 retry_after 까지 sleep 후 3회 retry 함. 두 번 retry 하면 rate limit
      가중. 그대로 raise.
    - transient (5xx, network, timeout) → 1s → 2s → 4s sleep 후 retry. ±0.25s
      jitter (asyncio.gather 에서 동시 발사된 retry 가 동기화되는 thundering
      herd 차단).

    Args:
        adapter: ``TelegramAdapter`` 또는 호환. ``send_outbound`` 메서드 보유.
        config: 어댑터 config (bot_token 포함).
        to: chat_id (str).
        response: ResponseEnvelope. None 이면 ``text=`` legacy 호출 시도.
        text: legacy 호출 (fallback). None 이면 response 만 사용.
        message_thread_id: 어댑터가 지원하면 keyword 전달, TypeError 면 fallback.

    Returns:
        실제 발송 성공한 attempt 번호 (0=첫 시도, 3=4번째 시도).

    Raises:
        TelegramSendError: permanent fail 즉시 또는 3회 retry 모두 실패.
        Exception: 그 외 어댑터 예외 (retry X — 즉시 raise).
    """
    import random as _r
    from src.integration.external_agent.telegram_adapter import (
        TelegramSendError,
    )

    last_exc: TelegramSendError | None = None
    for attempt in range(len(_TELEGRAM_RETRY_DELAYS) + 1):  # 0,1,2,3 = 1+3 retry
        try:
            try:
                # 신 표준 — message_thread_id + response + citations 키워드.
                kwargs: dict[str, Any] = {
                    "message_thread_id": message_thread_id,
                }
                # 2026-05-08 — citation 인라인 링크 (사용자 절칙). 어댑터가
                # 미지원 시 TypeError → legacy fallback.
                if citations is not None:
                    kwargs["citations"] = citations
                # D41 Phase 3 — citation landing HMAC token 생성용 tenant_id.
                # 어댑터가 미지원 시 TypeError → legacy fallback (link 미첨부).
                if tenant_id is not None:
                    kwargs["tenant_id"] = tenant_id
                if response is not None:
                    await adapter.send_outbound(
                        config,
                        to=to,
                        response=response,
                        **kwargs,
                    )
                else:
                    await adapter.send_outbound(
                        config,
                        to=to,
                        text=text or "",
                        **kwargs,
                    )
            except TypeError:
                # legacy 어댑터 — citations / response / message_thread_id 미지원.
                # GPT-5 P1 fix (2026-05-08): 점진 fallback — 새 키워드부터 제거.
                # 1) response + thread_id (citations 만 제외) — envelope 보존.
                # 2) text + thread_id — envelope 도 미지원 시.
                # 3) text only — 가장 보수적.
                _legacy_text = text or ""
                if not _legacy_text and response is not None:
                    _legacy_text = (
                        getattr(response, "to_text", None)() if hasattr(response, "to_text") else str(response)
                    )
                # 1) citations 빼고 response 보존.
                if response is not None:
                    try:
                        await adapter.send_outbound(
                            config,
                            to=to,
                            response=response,
                            message_thread_id=message_thread_id,
                        )
                        return attempt
                    except TypeError:
                        pass
                # 2) text + thread_id.
                try:
                    await adapter.send_outbound(
                        config,
                        to=to,
                        text=_legacy_text,
                        message_thread_id=message_thread_id,
                    )
                except TypeError:
                    # 3) 최후의 fallback — 가장 단순한 호출.
                    await adapter.send_outbound(
                        config, to=to, text=_legacy_text
                    )
            return attempt  # 성공
        except TelegramSendError as exc:
            last_exc = exc
            # GPT-5 P1 권고 — 실제 시도 횟수 (1-indexed) 를 예외에 부착해 caller
            # 가 retry_attempts_used 를 정확히 기록하도록.
            try:
                setattr(exc, "attempts_made", attempt + 1)
            except Exception:  # noqa: BLE001
                pass
            # permanent → 즉시 raise (retry X).
            if not exc.retryable:
                raise
            # 429 → 어댑터 layer 가 이미 retry. wrapper 는 retry X.
            if exc.status_code == 429:
                raise
            # transient (5xx / network / timeout) — retry.
            if attempt < len(_TELEGRAM_RETRY_DELAYS):
                base = _TELEGRAM_RETRY_DELAYS[attempt]
                jitter = _r.uniform(-_TELEGRAM_RETRY_JITTER, _TELEGRAM_RETRY_JITTER)
                wait_s = max(0.0, base + jitter)
                log.warning(
                    "telegram_send_transient_retry: attempt=%s status=%s "
                    "wait=%.2fs reason=%s",
                    attempt + 1,
                    exc.status_code,
                    wait_s,
                    str(exc)[:160],
                )
                await asyncio.sleep(wait_s)
                continue
            # 모든 retry 소진 → 마지막 raise.
            raise

    # 도달 불가 — 안전망.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("telegram_send_with_retry: unreachable")


@webhook_router.post("/{kind}/{external_id}/webhook", status_code=204)
async def channel_webhook(
    kind: str,
    external_id: str,
    request: Request,
    engine: AgentEngine = Depends(get_agent_engine),
):
    """외부 채널 webhook 수신 (Phase 1 Task 6).

    1. kind + external_id 로 agent_channels 조회 (is_active=True 만).
    2. config_encrypted Fernet 복호 → adapter.parse_inbound 서명·파싱.
    3. external_user_id → channel_user_mappings upsert.
    4. agent → AgentContext 로드.
    5. _handle_external_agent_message → SSE stream.
    6. adapter.collect_response + adapter.send_outbound 으로 채널 메시지 발송.

    검증 실패 / 비-msg 이벤트 / 설정 오류 → 204 (Telegram 재시도 회피).

    매 webhook turn 종료 시 ``agent_message_log`` 1행 INSERT (status / latency_ms /
    external_session_id) — dashboard / billing / insights 누적용. test-chat 의
    round 2 fix 와 동일 패턴 (commit 7516dad). webhook 은 API key 미사용이라
    ``api_key_id = NULL``, ``channel = kind``, ``external_session_id = chat_id``.
    """
    from src.integration.external_agent.registry import get_adapter
    from src.integration.external_agent.telegram_adapter import TelegramSendError
    from src.common.crypto.fernet import decrypt_dict
    from src.core.models.agent import AgentChannel
    from src.agent_framework.runtime.agent_context import AgentContext
    from src.api.routers.chat_v1 import _handle_external_agent_message

    # webhook turn latency 측정 시작 — agent_message_log INSERT 용.
    _log_t0 = time.monotonic()
    # finally INSERT 에 필요한 정보 (try 진입 전 None init — 어떤 단계에서 실패해도
    # 가능한 만큼 채워서 row 1건 보장).
    _log_status: str = "ok"
    _log_response: dict[str, Any] = {}
    _log_request: dict[str, Any] = {"kind": kind, "external_id": external_id}
    _log_external_session_id: str | None = None
    _log_agent_id: UUID | None = None
    _log_should_write: bool = False  # 진짜 turn 발생 시에만 INSERT (skip/dedup 제외).

    # adapter 조회 — 미지원 kind 는 400.
    adapter = get_adapter(kind)
    if adapter is None:
        raise HTTPException(400, f"unsupported channel kind: {kind}")

    # channel 조회 + user mapping upsert + agent 로드
    # L9 (2026-05-07) — channel + config 5 분 캐시. webhook 진입 latency
    # 단축 (primary DB roundtrip 1회 절약 ~ 50-200ms).
    _eng = _get_webhook_engine()
    channel = None
    config: dict = {}
    inbound = None
    agent = None
    channel_id = None
    channel_agent_id = None
    try:
        cached = _channel_cache_get(kind, external_id)
        if cached is not None:
            channel_id = cached["channel_id"]
            channel_agent_id = cached["agent_id"]
            config = cached["config"]
        else:
            async with AsyncSession(_eng) as db:
                async with db.begin():
                    stmt = select(AgentChannel).where(
                        AgentChannel.kind == kind,
                        AgentChannel.external_id == external_id,
                        AgentChannel.is_active.is_(True),
                    )
                    channel = (await db.execute(stmt)).scalar_one_or_none()
                    if not channel:
                        log.warning(
                            "webhook channel not found: kind=%s external_id=%s", kind, external_id
                        )
                        return

                    # session 종료 후에도 필요한 필드는 미리 추출 (DetachedInstanceError 방지)
                    channel_id = channel.id
                    channel_agent_id = channel.agent_id

                    # config 복호
                    try:
                        config = decrypt_dict(channel.config_encrypted)
                    except Exception as exc:
                        log.exception("channel config decrypt failed: %r", exc)
                        return  # 204 (설정 손상)
            # 캐시에 primitive 저장 — ORM 객체는 보관하지 않음.
            _channel_cache_put(
                kind,
                external_id,
                {
                    "channel_id": channel_id,
                    "agent_id": channel_agent_id,
                    "config": config,
                },
            )

        # webhook 서명 검증 + 본문 파싱 (I/O 없음 — session 밖에서 OK).
        # parse_inbound_v2 (있으면) 로 풍부한 결과 — 실패 사유 / 이벤트 라벨 audit.
        parse_v2 = getattr(adapter, "parse_inbound_v2", None)
        inbound = None
        parse_error: str | None = None
        event_label: str | None = None
        if parse_v2 is not None:
            result = await parse_v2(request, config)
            inbound = result.message
            parse_error = result.error.value if result.error else None
            event_label = result.event_label
        else:
            inbound = await adapter.parse_inbound(request, config)

        if inbound is None:
            # audit log 라벨 — 운영 디버깅 용. 대량 noise 방지 위해 INFO 수준.
            log.info(
                "webhook_inbound_skipped: kind=%s channel_id=%s error=%s event=%s",
                kind,
                channel_id,
                parse_error,
                event_label,
            )
            return  # 204

        # 멱등성 dedup — update_id 가 있으면 (channel_id, key) 기준 INSERT.
        # 새 INSERT 성공 = 처리 진행, 중복 = 즉시 204 (재 emit X).
        if inbound.idempotency_key is not None:
            async with AsyncSession(_eng) as db:
                async with db.begin():
                    is_new = await _wh_check_and_record_dedup(
                        db, channel_id, inbound.idempotency_key
                    )
            if not is_new:
                log.info(
                    "inbound_dedup_hit: kind=%s channel_id=%s key=%s",
                    kind,
                    channel_id,
                    inbound.idempotency_key,
                )
                return

        # 응답 발송 대상 chat_id — Task 8f. inbound.chat_id (group/supergroup
        # 에서도 정확한 chat) 우선, 없으면 from_user_id 로 fallback (private 가정).
        outbound_chat_id = inbound.chat_id or inbound.from_user_id

        # user mapping upsert + agent 로드 — session 안에서 모든 필드 추출
        agent_context = None
        agent_tenant_id = None
        agent_active = False
        # 059 — mapping.internal_account_id 가 set 이면 chat_sessions 통합 path.
        internal_account_id: UUID | None = None
        # Phase 1.5A Task 7 — sender 빌드용 mapping 스냅샷 (DetachedInstanceError 회피).
        _mapping_internal_user_id: UUID | None = None
        _mapping_internal_account_id: UUID | None = None
        _mapping_verified_via: str | None = None
        # Task 8f — group/supergroup/channel default deny.
        # ``channel_user_mappings.group_enabled`` 가 false 면 응답하지 않음.
        # private chat 은 항상 enabled.
        group_enabled = False
        is_group_chat = inbound.chat_type in ("group", "supergroup", "channel")
        async with AsyncSession(_eng) as db:
            async with db.begin():
                mapping = await _wh_upsert_user_mapping(
                    db, channel_id, inbound.from_user_id, chat_id=outbound_chat_id
                )
                # DetachedInstanceError 패턴 — primitive 로 즉시 추출.
                if mapping is not None and mapping.internal_account_id is not None:
                    internal_account_id = mapping.internal_account_id
                if mapping is not None:
                    _mapping_internal_user_id = getattr(mapping, "internal_user_id", None)
                    _mapping_internal_account_id = getattr(
                        mapping, "internal_account_id", None
                    )
                    _mapping_verified_via = getattr(mapping, "verified_via", None)
                # mail-send-2 디버그 — mapping 추출 직후 시점 — internal_account_id
                # 가 비어 있는지 / 어떤 row id 인지 진단. PII 없음 (account_id 만).
                log.info(
                    "webhook_mapping_extracted: channel_id=%s mapping_id=%s "
                    "internal_account_id=%s internal_user_id=%s "
                    "external_user_id=%s chat_id=%s group_enabled=%s",
                    channel_id,
                    getattr(mapping, "id", None) if mapping else None,
                    str(_mapping_internal_account_id)
                    if _mapping_internal_account_id
                    else None,
                    str(_mapping_internal_user_id)
                    if _mapping_internal_user_id
                    else None,
                    inbound.from_user_id,
                    outbound_chat_id,
                    bool(getattr(mapping, "group_enabled", False)) if mapping else None,
                )
                # group_enabled 컬럼 — alembic 062 적용 환경에서만 존재.
                if mapping is not None:
                    group_enabled = bool(getattr(mapping, "group_enabled", False))
                # L9 (2026-05-07) — agent_context 5 분 캐시. webhook 진입마다
                # agents row + AgentContext.from_agent 호출 반복 회피.
                cached_agent = _agent_cache_get(channel_agent_id)
                if cached_agent is not None:
                    agent_active = cached_agent["is_active"]
                    if agent_active:
                        agent_context = cached_agent["context"]
                        agent_tenant_id = cached_agent["tenant_id"]
                else:
                    agent = await _wh_get_agent(db, channel_agent_id)
                    if agent is not None:
                        agent_active = bool(agent.is_active)
                        if agent_active:
                            agent_context = AgentContext.from_agent(agent)
                            agent_tenant_id = agent.tenant_id
                            _agent_cache_put(
                                channel_agent_id,
                                {
                                    "is_active": True,
                                    "context": agent_context,
                                    "tenant_id": agent_tenant_id,
                                },
                            )
                        else:
                            _agent_cache_put(
                                channel_agent_id,
                                {
                                    "is_active": False,
                                    "context": None,
                                    "tenant_id": None,
                                },
                            )

        # Task 8f — group / supergroup / channel default deny.
        # admin 이 group_enabled=true 토글하기 전에는 응답 안 함 (조용히 skip).
        if is_group_chat and not group_enabled:
            log.info(
                "group_chat_default_deny: kind=%s channel_id=%s chat_id=%s chat_type=%s",
                kind,
                channel_id,
                outbound_chat_id,
                inbound.chat_type,
            )
            return  # 204
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("webhook db error: %r", exc)
        return  # 204 (재시도 불필요한 내부 오류)

    if agent_context is None or not agent_active:
        log.warning("webhook agent not found or inactive: agent_id=%s", channel_agent_id)
        return

    # session_id — channel + external_user_id 기반 결정론적 값.
    # engine 내부 (Redis 등) 의 conversation key. 동시에 chat_sessions row 도
    # 별도 UUID 로 보장 (mapping.internal_account_id set 인 경우만).
    session_id = f"wh-{channel_id}-{inbound.from_user_id}"

    # Phase 1.5A Task 7 — SenderContext 빌드.
    # mapping NULL → guest. mapping set + role 미조회 → verified (기본).
    # admin 승격은 Phase 2 의 명시적 OTP/role lookup 으로 — 채널 첫 진입은
    # default verified 안전.
    _sender: SenderContext | None = None
    try:
        # ORM mapping 객체가 session 밖에서 detach 됐으므로 primitive snapshot
        # 으로 duck-typed 객체를 만들어 helper 에 전달.
        class _MappingSnapshot:
            __slots__ = (
                "internal_user_id",
                "internal_account_id",
                "verified_via",
            )

            def __init__(self, iuid, iaid, vv):
                self.internal_user_id = iuid
                self.internal_account_id = iaid
                self.verified_via = vv

        _sender = _build_sender_context_from_channel(
            mapping=_MappingSnapshot(
                _mapping_internal_user_id,
                _mapping_internal_account_id,
                _mapping_verified_via,
            ),
            tenant_id=agent_tenant_id,
            channel_kind=kind,
            role=None,  # Phase 2: admin role lookup. Phase 1 default = verified.
        )
    except Exception:
        # sender 빌드 실패 시 None — engine.turn() 은 sender=None default 로 동작.
        log.exception("sender_context build failed (continuing with sender=None)")
        _sender = None

    # 이 시점부터 실제 turn 발생 — finally INSERT 켜기.
    _log_should_write = True
    _log_agent_id = channel_agent_id
    _log_external_session_id = str(outbound_chat_id) if outbound_chat_id else inbound.from_user_id
    _log_request = {
        "kind": kind,
        "external_id": external_id,
        "from_user_id": inbound.from_user_id,
        "chat_id": outbound_chat_id,
        "chat_type": inbound.chat_type,
        "text": (inbound.text or "")[:2000],
    }
    # collect_response 가 stream 을 다 소비하므로, 별도 tee 로 final body /
    # citations / token 카운트 를 capture. tee 는 그냥 통과시키면서 lateral 로
    # 메타를 모은다 — adapter.collect_response 동작 무영향.
    _captured_body_chunks: list[str] = []
    _captured_citations: list[dict] = []
    # KMS-Plus 2026-05-07 — multimodal retrieve (사용자 절칙: 표/그림 답변 첨부).
    # GPT-5 검증 P0-2 — Telegram 도 SSE structured_block 을 받아 ImageBlock /
    # TableBlock / LinkBlock / AlertBlock 으로 변환해야 Web 과 동등하게 표/그림
    # 첨부 가능. 본 list 가 collect_response 후 envelope 에 append.
    _captured_structured_blocks: list[dict] = []

    # chat 처리 — engine.turn() SSE stream.
    # 059 — internal_account_id set 이면 chat_sessions/messages 통합 영속화.
    raw_sse_stream = _handle_external_agent_message(
        text=inbound.text,
        agent_context=agent_context,
        tenant_id=agent_tenant_id,
        session_id=session_id,
        engine=engine,
        internal_account_id=internal_account_id,
        channel_kind=kind,
        channel_id=channel_id,
        external_user_id=inbound.from_user_id,
        agent_id=channel_agent_id,
        # mail.send/diary/expense 등 user-scoped 도구가 args["account_id"] 를
        # 자동 주입 받도록 engine.turn 에 hint 전달. mapping NULL (guest) 이면
        # None — 도구가 "계정 정보 설정 미비" 에러로 적절히 응답.
        account_id_hint=str(internal_account_id) if internal_account_id else None,
        sender=_sender,
    )

    async def _tee_for_log():
        async for ev in raw_sse_stream:
            if isinstance(ev, dict):
                _ev = ev.get("event")
                _data = ev.get("data") or {}
                if _ev in ("token", "delta") and isinstance(_data, dict):
                    _chunk = _data.get("text") or _data.get("delta") or ""
                    if _chunk:
                        _captured_body_chunks.append(_chunk)
                elif _ev == "citations" and isinstance(_data, dict):
                    items = _data.get("items") or []
                    if isinstance(items, list):
                        _captured_citations[:] = items
                elif _ev == "structured_block" and isinstance(_data, dict):
                    # KMS-Plus 2026-05-07 — multimodal capture for Telegram/SMS/etc.
                    # Web frontend 는 SSE 직접 수신 — capture 영향 0.
                    _captured_structured_blocks.append(dict(_data))
            yield ev

    sse_stream = _tee_for_log()

    # forum supergroup topic 응답 보존 — Telegram 은 message_thread_id 없으면
    # General 로 보내져 사용자가 응답을 못 본다. Task 8f — InboundMessage
    # dataclass field 우선, 호환을 위해 metadata fallback.
    thread_id = inbound.message_thread_id
    if thread_id is None:
        thread_id_raw = (inbound.metadata or {}).get("message_thread_id")
        try:
            thread_id = int(thread_id_raw) if thread_id_raw is not None else None
        except (TypeError, ValueError):
            thread_id = None

    # SSE → 채널 메시지 변환 + 발송. send 의 send_outbound 키워드 호환:
    # message_thread_id 미지원 어댑터는 TypeError 발생 → fallback 호출.
    # Task 8f — to= 인자는 ``inbound.chat_id`` (group/supergroup 정확). private
    # 은 ``chat_id == from_user_id`` 라 무영향.
    #
    # Phase 1.5C — final text 를 ``ResponseEnvelope`` 로 wrap 한 뒤 전달.
    # 현재 wrap 결과는 TextBlock 1개 (시연 path 와 동일). 향후 LLM 이 직접
    # envelope JSON 으로 응답하면 ``render_response`` 가 5종 블록으로 디코드.
    from src.agent_framework.runtime.response_renderer import (
        render_response,
        append_structured_blocks_to_envelope,
    )
    try:
        try:
            body, citations = await adapter.collect_response(sse_stream)
            # 2026-05-08 — rich-text (사용자 절칙: "이쁘게 표도"). LLM 이 markdown
            # 으로 응답 → render_response(parse_mode="markdown") 가 본문 안
            # 표를 TableBlock 으로 자동 추출 + TextBlock(parse_mode="markdown")
            # 로 wrap. Telegram 어댑터가 markdown→HTML 변환 + citation [N]
            # 인라인 링크.
            # Feature flag KMS_TG_HTML_RICH=0 으로 비활성 (legacy plain).
            import os as _os_rich
            _rich_enabled = _os_rich.environ.get(
                "KMS_TG_HTML_RICH", "1"
            ).lower() in ("1", "true", "yes")
            envelope = render_response(
                body,
                parse_mode="markdown" if _rich_enabled else "plain",
            )
            # KMS-Plus 2026-05-07 — multimodal retrieve (사용자 절칙).
            # GPT-5 P0-2 fix — captured structured_blocks 를 ImageBlock /
            # TableBlock / LinkBlock / AlertBlock 으로 변환해 envelope 끝에
            # append. Telegram 도 Web 과 동등하게 표/그림 첨부.
            envelope = append_structured_blocks_to_envelope(
                envelope, _captured_structured_blocks
            )
            # OOS-guard-and-telegram-retry-fix (2026-05-07) — max 3 retry +
            # exp backoff (1s/2s/4s) + jitter ±0.25s. permanent reason 즉시 fail.
            _send_attempt = await _send_outbound_with_retry(
                adapter,
                config=config,
                to=outbound_chat_id,
                response=envelope,
                text=body,  # legacy fallback path 에서 사용.
                message_thread_id=thread_id,
                # 2026-05-08 — citation 인라인 링크. 어댑터가 markdown→HTML
                # 변환 시 [N] 마커를 <a href> 로 wrap.
                citations=_captured_citations or citations or None,
                # D41 Phase 3 — citation landing HMAC token 생성용 tenant_id.
                # channel.agent.tenant_id (webhook handler 가 미리 resolve).
                # None 이면 어댑터가 link 생성 X (fail-safe).
                tenant_id=agent_tenant_id,
            )
            # 성공 path — log_response 채움.
            _log_status = "ok"
            _log_response = {
                "message": (body or "")[:4000],
                "citations": (citations or [])[:10],
                "retry_attempts": _send_attempt,  # 0=첫 시도 성공, 1~3=retry 후 성공.
            }
        except TelegramSendError as exc:
            # permanent error 분기 — 채널 / mapping 자동 비활성.
            log.warning(
                "telegram_send_failed: status=%s retryable=%s permanent=%s",
                exc.status_code,
                exc.retryable,
                exc.permanent_reason,
            )
            _log_status = "error"
            _log_response = {
                "error": "telegram_send_failed",
                "status_code": exc.status_code,
                "retryable": exc.retryable,
                "permanent_reason": exc.permanent_reason,
                # 가능한 만큼 capture 된 본문 같이 기록 (debugging 용).
                "captured_body": ("".join(_captured_body_chunks))[:2000],
                # GPT-5 P1 권고 — _send_outbound_with_retry 가 부착한 attempts_made
                # 를 우선 사용. 없으면 fallback (permanent=1, transient=4).
                "retry_attempts_used": getattr(
                    exc,
                    "attempts_made",
                    len(_TELEGRAM_RETRY_DELAYS) + 1 if exc.retryable else 1,
                ),
            }
            if not exc.retryable and exc.permanent_reason:
                try:
                    async with AsyncSession(_eng) as db:
                        async with db.begin():
                            if exc.permanent_reason == "token_revoked":
                                await _wh_deactivate_channel(
                                    db, channel_id, exc.permanent_reason
                                )
                            elif exc.permanent_reason in (
                                "bot_blocked", "bot_kicked",
                                "user_deactivated", "chat_not_found",
                            ):
                                await _wh_deactivate_user_mapping(
                                    db,
                                    channel_id,
                                    inbound.from_user_id,
                                    exc.permanent_reason,
                                )
                except Exception:
                    log.exception("permanent error handling failed")
            # transient (5xx, 429, timeout) — fallback 안내 메시지 시도. permanent
            # 면 알림 보낼 채널이 죽었으니 시도 안 함. fallback 도 retry 동일 정책.
            if exc.retryable:
                try:
                    await _send_outbound_with_retry(
                        adapter,
                        config=config,
                        to=outbound_chat_id,
                        text="죄송합니다, 응답 생성 중 오류가 발생했습니다.",
                        message_thread_id=thread_id,
                    )
                except Exception:
                    pass
        except Exception as exc:
            log.exception("channel send failed: %r", exc)
            _log_status = "error"
            _log_response = {
                "error": "channel_send_failed",
                "message": str(exc)[:500],
                "captured_body": ("".join(_captured_body_chunks))[:2000],
            }
            # best-effort 오류 알림 — retry 동일 정책.
            try:
                await _send_outbound_with_retry(
                    adapter,
                    config=config,
                    to=outbound_chat_id,
                    text="죄송합니다, 응답 생성 중 오류가 발생했습니다.",
                    message_thread_id=thread_id,
                )
            except Exception:
                pass
    finally:
        # round 3 fix — webhook turn 종료 시 agent_message_log INSERT.
        # _log_should_write 가 True 인 경우 (실제 engine.turn() 진입한 경우) 만
        # 기록. skip / dedup_hit / group_default_deny / mapping 미존재 등은 일찌감치
        # return 으로 빠져나가므로 finally 가 실행돼도 should_write=False 유지.
        if _log_should_write and _log_agent_id is not None:
            _latency_ms = int((time.monotonic() - _log_t0) * 1000)
            try:
                await _write_log(
                    agent_id=_log_agent_id,
                    api_key_id=None,  # webhook 은 API key 미사용.
                    channel=kind,
                    external_session_id=_log_external_session_id,
                    request_payload=_log_request,
                    response_payload=_log_response,
                    status=_log_status,
                    latency_ms=_latency_ms,
                )
            except Exception:
                # _write_log 자체도 silent drop 이지만 한 번 더 감싸 webhook
                # 응답 실패 차단.
                log.exception("agent_message_log insert failed (best-effort)")
    # 항상 204 반환 (Telegram 은 2xx 받으면 재시도 안 함).


# ---------------------------------------------------------------------------
# 운영 도구 — getMe 등록 검증 + getWebhookInfo 폴링 모니터
# ---------------------------------------------------------------------------


class TelegramVerifyRequest(BaseModel):
    """등록 시 호출 — bot_token 만 받아 getMe 로 검증.

    config_encrypted 저장 *전* 사용. 잘못된 token 을 첫 webhook 까지 발견 안
    하는 결함 방지.
    """

    bot_token: str = Field(..., min_length=10)


@webhook_router.post("/telegram/verify-token")
async def telegram_verify_token(body: TelegramVerifyRequest):
    """``getMe`` 호출 — bot_token 유효성 검증 + bot meta 반환.

    응답: ``{ok, bot_id, bot_username, first_name, can_join_groups,
            can_read_all_group_messages, supports_inline_queries}``

    실패: 401 (token 폐기), 502 (Telegram API 응답 이상).
    """
    from src.integration.external_agent.registry import get_adapter
    from src.integration.external_agent.telegram_adapter import TelegramSendError

    adapter = get_adapter("telegram")
    if adapter is None or not hasattr(adapter, "get_me"):
        raise HTTPException(500, "telegram adapter unavailable")

    try:
        me = await adapter.get_me(body.bot_token)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except TelegramSendError as e:
        if e.status_code == 401 or e.permanent_reason == "token_revoked":
            raise HTTPException(401, "invalid bot token") from e
        raise HTTPException(502, f"telegram getMe failed: {e}") from e

    if not me.get("is_bot"):
        raise HTTPException(400, "token is not a bot account")

    return {
        "ok": True,
        "bot_id": me.get("id"),
        "bot_username": me.get("username"),
        "first_name": me.get("first_name"),
        "can_join_groups": me.get("can_join_groups"),
        "can_read_all_group_messages": me.get("can_read_all_group_messages"),
        "supports_inline_queries": me.get("supports_inline_queries"),
    }


@webhook_router.get("/telegram/{external_id}/webhook-info")
async def telegram_webhook_info(external_id: str):
    """``getWebhookInfo`` 폴링 — 운영 모니터링.

    응답: WebhookInfo 풀 + ``health`` 필드 (ok / warn / error 분류).

    health 분류:
    - error: ``last_error_date`` 가 5분 이내 OR ``pending_update_count > 100``
    - warn: ``pending_update_count > 10`` OR last_error_date 가 24h 이내
    - ok: 위 외 모두

    cron / admin alert 가 health=error 시 PagerDuty / Slack 알림.
    """
    import time as _time
    from src.integration.external_agent.registry import get_adapter
    from src.integration.external_agent.telegram_adapter import TelegramSendError
    from src.common.crypto.fernet import decrypt_dict
    from src.core.models.agent import AgentChannel

    adapter = get_adapter("telegram")
    if adapter is None or not hasattr(adapter, "get_webhook_info"):
        raise HTTPException(500, "telegram adapter unavailable")

    # channel 조회 + bot_token 추출
    _eng = _get_webhook_engine()
    bot_token: str | None = None
    async with AsyncSession(_eng) as db:
        async with db.begin():
            stmt = select(AgentChannel).where(
                AgentChannel.kind == "telegram",
                AgentChannel.external_id == external_id,
            )
            channel = (await db.execute(stmt)).scalar_one_or_none()
            if channel is None:
                raise HTTPException(404, f"channel not found: {external_id}")
            try:
                cfg = decrypt_dict(channel.config_encrypted)
                bot_token = cfg.get("bot_token")
            except Exception as exc:
                log.exception("config decrypt failed for webhook-info: %r", exc)
                raise HTTPException(500, "channel config decrypt failed") from exc

    if not bot_token:
        raise HTTPException(500, "bot_token missing in channel config")

    try:
        info = await adapter.get_webhook_info(bot_token)
    except TelegramSendError as e:
        raise HTTPException(502, f"getWebhookInfo failed: {e}") from e

    # health 분류
    pending = int(info.get("pending_update_count") or 0)
    last_err_date = info.get("last_error_date") or 0
    now_ts = int(_time.time())
    err_age = now_ts - int(last_err_date) if last_err_date else None

    if pending > 100 or (err_age is not None and err_age < 300):
        health = "error"
    elif pending > 10 or (err_age is not None and err_age < 86400):
        health = "warn"
    else:
        health = "ok"

    return {
        "external_id": external_id,
        "health": health,
        "info": info,
    }


@webhook_router.get("/telegram/health-summary")
async def telegram_health_summary():
    """모든 활성 telegram 채널의 health 요약 — admin dashboard / cron.

    각 채널마다 ``getWebhookInfo`` 호출. 채널 N 개면 N 호출 (소수 채널 가정).
    응답: ``{channels: [{external_id, health, pending, last_error_message}]}``
    """
    import time as _time
    from src.integration.external_agent.registry import get_adapter
    from src.integration.external_agent.telegram_adapter import TelegramSendError
    from src.common.crypto.fernet import decrypt_dict
    from src.core.models.agent import AgentChannel

    adapter = get_adapter("telegram")
    if adapter is None or not hasattr(adapter, "get_webhook_info"):
        raise HTTPException(500, "telegram adapter unavailable")

    _eng = _get_webhook_engine()
    results: list[dict] = []
    async with AsyncSession(_eng) as db:
        async with db.begin():
            stmt = select(AgentChannel).where(
                AgentChannel.kind == "telegram",
                AgentChannel.is_active.is_(True),
            )
            rows = (await db.execute(stmt)).scalars().all()
            # token 을 미리 추출 (DetachedInstanceError 방지 + session 외부 호출).
            channel_tokens: list[tuple[str, str]] = []
            for ch in rows:
                try:
                    cfg = decrypt_dict(ch.config_encrypted)
                    token = cfg.get("bot_token")
                    if token:
                        channel_tokens.append((ch.external_id, token))
                except Exception:
                    log.exception(
                        "config decrypt failed health-summary external_id=%s",
                        ch.external_id,
                    )

    now_ts = int(_time.time())
    for ext_id, token in channel_tokens:
        try:
            info = await adapter.get_webhook_info(token)
        except TelegramSendError as e:
            results.append({
                "external_id": ext_id,
                "health": "error",
                "pending": None,
                "last_error_message": f"getWebhookInfo failed: {e}",
            })
            continue

        pending = int(info.get("pending_update_count") or 0)
        last_err_date = info.get("last_error_date") or 0
        err_age = now_ts - int(last_err_date) if last_err_date else None

        if pending > 100 or (err_age is not None and err_age < 300):
            health = "error"
        elif pending > 10 or (err_age is not None and err_age < 86400):
            health = "warn"
        else:
            health = "ok"

        results.append({
            "external_id": ext_id,
            "health": health,
            "pending": pending,
            "last_error_message": info.get("last_error_message"),
            "last_error_date": last_err_date,
        })

    overall = "ok"
    for r in results:
        if r["health"] == "error":
            overall = "error"
            break
        if r["health"] == "warn":
            overall = "warn"

    return {"overall_health": overall, "channels": results}
