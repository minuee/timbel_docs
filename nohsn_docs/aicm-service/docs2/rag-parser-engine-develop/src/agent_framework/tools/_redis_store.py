"""mock tool 들의 in-memory state 를 Redis 로 대체하는 경량 helper.

키 스키마:
  agent_mock:<category>:<phone_or_key>  → list | dict | set

- category: 'schedule' | 'diary' | 'news_sub' | 'news_reports' | 'calendar_booked' | 'reminder'
- 테스트는 conftest autouse fixture 가 flush (AGENT_MOCK_REDIS_DB=2 로 prod 격리).

uvicorn API_WORKERS=4 환경에서 worker 간 state 공유를 위해 Redis 사용.

DEPRECATED (D24 §2, 2026-05-08): redis legacy path 는 phone-scoped — 같은 phone
의 다른 agent 끼리 데이터가 섞일 수 있다. agent 단위 격리는 KMS path 만 보장.
production 은 ``AGENT_DATA_STORE=kms`` 로 cutover 권장. 본 모듈은 D25 옵션 A
(key schema rebuild + dual-write + migration) 후 제거 예정.

GPT-5 phase 0 patch: import 시점이 아닌 *첫 실 사용* 시점에 1회만
DeprecationWarning emit (once-flag). 매 호출마다 emit 하면 noise.
"""
from __future__ import annotations

import json
import os
import threading
import warnings
from typing import Any

import redis.asyncio as aioredis

from src.common.config import settings


# === D24 §2 — once-flag DeprecationWarning ===
# _get_client() 첫 진입 시 1회만 warn (process 단위). import 시 warn 하면 테스트
# noise + spec 문구 (첫 호출 시) 와 불일치.
# threading.Lock 으로 동시 첫 호출 시 중복 warn 방지 (GPT-5 phase 2 post 권고).
_DEPRECATION_WARNED = False
_EMIT_LOCK = threading.Lock()


def _emit_deprecation_once() -> None:
    """첫 실 사용 시점에 1회 DeprecationWarning emit (process-local once flag).

    Lock 으로 멀티스레드 첫 동시 호출 시 정확히 1회만 emit 보장.
    """
    global _DEPRECATION_WARNED  # noqa: PLW0603
    if _DEPRECATION_WARNED:
        return
    should_warn = False
    with _EMIT_LOCK:
        if not _DEPRECATION_WARNED:
            _DEPRECATION_WARNED = True
            should_warn = True
    if not should_warn:
        return
    warnings.warn(
        "redis legacy path (_redis_store) is deprecated; "
        "set AGENT_DATA_STORE=kms for agent isolation. "
        "removal plan: D25 (옵션 A — key schema rebuild + dual-write).",
        DeprecationWarning,
        stacklevel=2,
    )

# 클라이언트는 event loop 별로 캐시 — pytest-asyncio 가 테스트마다 loop 재생성하므로
# PID 만으로 캐시하면 "Event loop is closed" 발생.
_clients: dict[tuple[int, int, int], aioredis.Redis] = {}


def _current_db() -> int:
    """매 호출마다 환경 변수 확인 — 테스트가 conftest 에서 AGENT_MOCK_REDIS_DB=2 설정."""
    return int(os.environ.get("AGENT_MOCK_REDIS_DB", "0"))


def _base_url() -> str:
    """REDIS_URL 끝의 /N 부분을 떼어내고 뒤에 현재 DB 를 붙임."""
    url = os.environ.get("REDIS_URL", settings.REDIS_URL)
    # "redis://host:port/0" → "redis://host:port" (scheme 뒤 마지막 /숫자 제거)
    idx = url.rfind("/")
    scheme_end = url.find("//")
    if scheme_end != -1 and idx > scheme_end + 2:
        tail = url[idx + 1 :]
        if tail.isdigit():
            url = url[:idx]
    return f"{url}/{_current_db()}"


async def _get_client() -> aioredis.Redis:
    import asyncio

    # D24 §2 — 첫 실 사용 시점에 1회 DeprecationWarning emit.
    _emit_deprecation_once()

    pid = os.getpid()
    db = _current_db()
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    key = (pid, db, loop_id)
    client = _clients.get(key)
    if client is None:
        client = aioredis.from_url(_base_url(), decode_responses=True)
        _clients[key] = client
    return client


def _key(category: str, phone: str | None = None) -> str:
    if phone is None:
        return f"agent_mock:{category}"
    return f"agent_mock:{category}:{phone}"


# ── Generic list helpers (phone-scoped) ────────────────────────────────


async def rpush_item(category: str, phone: str, item: dict) -> None:
    c = await _get_client()
    await c.rpush(_key(category, phone), json.dumps(item, ensure_ascii=False))


async def list_items(category: str, phone: str) -> list[dict]:
    c = await _get_client()
    raws = await c.lrange(_key(category, phone), 0, -1)
    return [json.loads(r) for r in raws]


async def replace_items(category: str, phone: str, items: list[dict]) -> None:
    """list 전체를 새 items 로 교체 — update 흐름에서 사용."""
    c = await _get_client()
    key = _key(category, phone)
    pipe = c.pipeline()
    pipe.delete(key)
    if items:
        pipe.rpush(
            key,
            *[json.dumps(it, ensure_ascii=False) for it in items],
        )
    await pipe.execute()


async def remove_by_id(category: str, phone: str, item_id: str) -> bool:
    """list 안의 {"id": ...} item 하나 제거. True 면 지워짐."""
    c = await _get_client()
    key = _key(category, phone)
    raws = await c.lrange(key, 0, -1)
    removed = False
    kept: list[str] = []
    for r in raws:
        try:
            obj = json.loads(r)
        except Exception:
            kept.append(r)
            continue
        if not removed and obj.get("id") == item_id:
            removed = True
            continue
        kept.append(r)
    if not removed:
        return False
    pipe = c.pipeline()
    pipe.delete(key)
    if kept:
        pipe.rpush(key, *kept)
    await pipe.execute()
    return True


# ── Hash helpers (phone-scoped dict) ───────────────────────────────────


async def hash_get(category: str, phone: str) -> dict:
    c = await _get_client()
    raw = await c.get(_key(category, phone))
    if not raw:
        return {}
    return json.loads(raw)


async def hash_set(category: str, phone: str, value: dict) -> None:
    c = await _get_client()
    await c.set(_key(category, phone), json.dumps(value, ensure_ascii=False))


# ── Global list (no phone scope — reminder) ────────────────────────────


async def rpush_global(category: str, item: dict) -> None:
    c = await _get_client()
    await c.rpush(_key(category), json.dumps(item, ensure_ascii=False))


async def list_global(category: str) -> list[dict]:
    c = await _get_client()
    raws = await c.lrange(_key(category), 0, -1)
    return [json.loads(r) for r in raws]


async def replace_global(category: str, items: list[dict]) -> None:
    """전역 리스트를 통째로 교체. reminder_store.mark_fired 가 사용 (id patch)."""
    c = await _get_client()
    key = _key(category)
    pipe = c.pipeline()
    pipe.delete(key)
    if items:
        pipe.rpush(key, *[json.dumps(it, ensure_ascii=False) for it in items])
    await pipe.execute()


# ── Set helpers (calendar booked slots) ────────────────────────────────


async def sadd_member(category: str, member: str) -> None:
    c = await _get_client()
    await c.sadd(_key(category), member)


async def sismember(category: str, member: str) -> bool:
    c = await _get_client()
    return bool(await c.sismember(_key(category), member))


async def _flush_all_mocks() -> None:
    """테스트 conftest 에서 호출 — 모든 agent_mock:* 키 제거."""
    c = await _get_client()
    keys = await c.keys("agent_mock:*")
    if keys:
        await c.delete(*keys)


def _reset_sync() -> None:
    """동기 호출용 — 기존 sync `_reset()` 하위 호환.

    async context 안에서 호출되면 event loop 재진입 불가하므로
    동기 Redis 클라이언트로 직접 flush (scan+del). 테스트 autouse fixture 가
    이미 flush 했더라도 idempotent 하므로 안전.

    NOTE: _reset_sync 는 *테스트 인프라* — DeprecationWarning emit 안 함 (테스트
    cleanup 노이즈 방지).
    """
    import redis as sync_redis

    url = _base_url()
    try:
        client = sync_redis.Redis.from_url(url, decode_responses=True)
        keys = client.keys("agent_mock:*")
        if keys:
            client.delete(*keys)
        client.close()
    except Exception:
        # Redis 미연결 시 조용히 무시 (테스트 autouse fixture 가 주된 경로)
        pass
