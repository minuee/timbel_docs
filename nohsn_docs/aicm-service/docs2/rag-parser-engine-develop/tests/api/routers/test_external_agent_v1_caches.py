"""L9 (2026-05-07) — webhook overhead 단축 LRU 캐시 단위 검증.

- channel_cache 와 agent_cache 의 TTL / max-size / invalidate 동작.
- DB / FastAPI 레이어 없이 pure 함수만 테스트.
"""
from __future__ import annotations

import time
from uuid import uuid4

from src.api.routers.external_agent_v1 import (
    _channel_cache,
    _channel_cache_get,
    _channel_cache_put,
    invalidate_channel_cache,
    _agent_cache,
    _agent_cache_get,
    _agent_cache_put,
    invalidate_agent_cache,
)


def setup_function():
    """테스트마다 캐시 초기화."""
    _channel_cache.clear()
    _agent_cache.clear()


def test_channel_cache_put_and_get():
    data = {"channel_id": uuid4(), "agent_id": uuid4(), "config": {"token": "x"}}
    _channel_cache_put("telegram", "ext-1", data)
    got = _channel_cache_get("telegram", "ext-1")
    assert got == data


def test_channel_cache_miss_returns_none():
    assert _channel_cache_get("telegram", "missing") is None


def test_channel_cache_invalidate_specific():
    _channel_cache_put("telegram", "ext-a", {"channel_id": uuid4(), "agent_id": None, "config": {}})
    _channel_cache_put("telegram", "ext-b", {"channel_id": uuid4(), "agent_id": None, "config": {}})
    n = invalidate_channel_cache("telegram", "ext-a")
    assert n == 1
    assert _channel_cache_get("telegram", "ext-a") is None
    assert _channel_cache_get("telegram", "ext-b") is not None


def test_channel_cache_invalidate_all():
    _channel_cache_put("telegram", "ext-a", {"channel_id": uuid4(), "agent_id": None, "config": {}})
    _channel_cache_put("telegram", "ext-b", {"channel_id": uuid4(), "agent_id": None, "config": {}})
    n = invalidate_channel_cache()
    assert n == 2
    assert _channel_cache_get("telegram", "ext-a") is None


def test_agent_cache_put_and_get():
    aid = uuid4()
    data = {"is_active": True, "context": object(), "tenant_id": uuid4()}
    _agent_cache_put(aid, data)
    got = _agent_cache_get(aid)
    assert got is data


def test_agent_cache_invalidate_specific():
    a1 = uuid4()
    a2 = uuid4()
    _agent_cache_put(a1, {"is_active": True, "context": None, "tenant_id": None})
    _agent_cache_put(a2, {"is_active": True, "context": None, "tenant_id": None})
    n = invalidate_agent_cache(a1)
    assert n == 1
    assert _agent_cache_get(a1) is None
    assert _agent_cache_get(a2) is not None


def test_channel_cache_expires_after_ttl(monkeypatch):
    """TTL 경과 시 entry 자동 expire."""
    # ttl 을 직접 조작하기 위해 entry 의 expires_at 을 과거로.
    _channel_cache_put(
        "telegram", "ext-x",
        {"channel_id": uuid4(), "agent_id": None, "config": {}},
    )
    # 강제로 expires_at 을 past 로.
    _channel_cache[("telegram", "ext-x")] = (time.time() - 1, {})
    assert _channel_cache_get("telegram", "ext-x") is None
    # expired 시 자동 삭제.
    assert ("telegram", "ext-x") not in _channel_cache
