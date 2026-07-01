"""``/api/v1/chat/url_preview`` — KMS-Plus P6 backend wrapper layer.

frontend-v3 Multimodal Composer 가 paste/typing 으로 감지한 URL 메타 프리뷰
endpoint. P0.2 stub 에서 P6 본 구현으로 승격.

가드 / 동작:
- Bearer 인증 필수 (P0.2 와 동일 — ``_require_bearer``).
- 실 fetch 는 ``src.agent_framework.api.url_preview.fetch_url_preview`` 가 처리
  — SSRF / DNS rebinding / oversized payload / disallowed content-type / redirect
  cap 등 모든 가드 탑재.
- per-account 인메모리 캐시 (TTL 10 min) — (url, account_id) 키. 동일 사용자가
  같은 URL 을 짧게 반복 paste 해도 외부 요청을 매번 보내지 않게.

응답은 항상 200 + body — 거부 사유는 ``status="rejected"`` + ``reason`` 로 노출.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from src.agent_framework.api.url_preview import fetch_url_preview
from src.api.auth.jwt_utils import InvalidToken, decode_token

router = APIRouter(prefix="/api/v1/chat", tags=["chat-v1"])

# ---------------------------------------------------------------------------
# 캐시 — per (url, account_id), TTL 600s
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS: int = 600
_CACHE_MAX_ENTRIES: int = 1024
_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _cache_get(key: tuple[str, str]) -> dict[str, Any] | None:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.monotonic() - ts > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple[str, str], payload: dict[str, Any]) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        # 단순 evict — 가장 오래된 1 개 제거. LRU 까지 갈 필요 없는 규모.
        oldest_key = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest_key, None)
    _cache[key] = (time.monotonic(), payload)


def _clear_cache_for_tests() -> None:
    """테스트 격리용 — 운영 코드에서 호출 금지."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _require_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "empty token")
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    return str(sub)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UrlPreviewIn(BaseModel):
    url: str


class UrlPreviewOut(BaseModel):
    status: str  # "ok" | "rejected"
    url: str | None = None
    title: str | None = None
    description: str | None = None
    image: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/url_preview", response_model=UrlPreviewOut)
async def url_preview(
    body: UrlPreviewIn,
    authorization: str | None = Header(default=None),
) -> UrlPreviewOut:
    """URL 메타 프리뷰 — Bearer 인증 + SSRF guard + per-account 캐시."""
    account_id = _require_bearer(authorization)

    cache_key = (body.url, account_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return UrlPreviewOut(**cached)

    result = await fetch_url_preview(body.url)
    out = UrlPreviewOut(
        status=result.get("status", "rejected"),
        url=result.get("url"),
        title=result.get("title"),
        description=result.get("description"),
        image=result.get("image"),
        reason=result.get("reason"),
    )
    _cache_put(cache_key, out.model_dump())
    return out
