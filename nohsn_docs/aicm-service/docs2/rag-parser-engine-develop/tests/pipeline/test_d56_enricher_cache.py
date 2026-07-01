"""D56 §E PR-E — EnricherRedisCache unit test.

검증:
- cfg_hash 가 prompt/schema/model/params 변경 시 다른 키 생성
- JSON envelope round-trip (str + dict)
- 4KB+ gzip 압축
- Redis 실패 시 in-memory LRU fallback
- Circuit breaker (연속 실패 → 회로 열림)
- 비활성 (ENRICHER_CACHE_ENABLED=false) → silent miss
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.mark.asyncio
async def test_cfg_hash_changes_on_prompt_change():
    """prompt 텍스트 변경 시 cfg_hash 분기 — 자동 invalidation."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c1 = EnricherRedisCache(
        name="test", schema_version="v1", prompt_version="v1",
        prompt_text="prompt A", model_id="m1",
        inference_params={"temperature": 0.2},
    )
    c2 = EnricherRedisCache(
        name="test", schema_version="v1", prompt_version="v1",
        prompt_text="prompt B",  # 변경
        model_id="m1",
        inference_params={"temperature": 0.2},
    )
    assert c1._cfg_hash != c2._cfg_hash
    assert c1.build_key("hash_x") != c2.build_key("hash_x")


@pytest.mark.asyncio
async def test_cfg_hash_changes_on_model_change():
    """model_id 변경 시 cfg_hash 분기."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c1 = EnricherRedisCache(name="t", prompt_text="p", model_id="gemma-4-31b")
    c2 = EnricherRedisCache(name="t", prompt_text="p", model_id="gemma-4-9b")
    assert c1._cfg_hash != c2._cfg_hash


@pytest.mark.asyncio
async def test_cfg_hash_changes_on_inference_params():
    """temperature 변경 시 cfg_hash 분기."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c1 = EnricherRedisCache(name="t", prompt_text="p",
                            inference_params={"temperature": 0.2})
    c2 = EnricherRedisCache(name="t", prompt_text="p",
                            inference_params={"temperature": 0.5})
    assert c1._cfg_hash != c2._cfg_hash


@pytest.mark.asyncio
async def test_serialize_small_json_no_gzip():
    """4 KB 미만 데이터는 J1 헤더 (gzip 미적용)."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c = EnricherRedisCache(name="t", prompt_text="p")
    raw = c._serialize("small string")
    assert raw.startswith(b"J1")


@pytest.mark.asyncio
async def test_serialize_large_data_gzip():
    """4 KB+ 데이터는 G1 헤더 (gzip 압축)."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c = EnricherRedisCache(name="t", prompt_text="p")
    big = {"data": "x" * 10000}
    raw = c._serialize(big)
    assert raw.startswith(b"G1")
    # 압축 효과 검증
    assert len(raw) < 10000


@pytest.mark.asyncio
async def test_roundtrip_string():
    """str round-trip."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c = EnricherRedisCache(name="t", prompt_text="p")
    raw = c._serialize("hello world")
    restored = c._deserialize(raw)
    assert restored == "hello world"


@pytest.mark.asyncio
async def test_roundtrip_dict():
    """dict round-trip."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c = EnricherRedisCache(name="t", prompt_text="p")
    payload = {"keywords": ["a", "b"], "score": 0.5, "nested": {"x": 1}}
    raw = c._serialize(payload)
    restored = c._deserialize(raw)
    assert restored == payload


@pytest.mark.asyncio
async def test_deserialize_cfg_mismatch_returns_none():
    """cfg_hash 다른 envelope 은 None (자동 무효화)."""
    from src.pipeline.enrichers.cache import EnricherRedisCache

    c1 = EnricherRedisCache(name="t", prompt_text="A")
    c2 = EnricherRedisCache(name="t", prompt_text="B")  # 다른 cfg_hash
    raw = c1._serialize("payload")
    assert c1._deserialize(raw) == "payload"
    # c2 는 cfg_hash 가 달라 None 반환
    assert c2._deserialize(raw) is None


@pytest.mark.asyncio
async def test_disabled_returns_none(monkeypatch):
    """ENRICHER_CACHE_ENABLED=false 시 silent miss."""
    monkeypatch.setenv("ENRICHER_CACHE_ENABLED", "false")
    # 모듈 reload (env 캐시 회피)
    if "src.pipeline.enrichers.cache" in sys.modules:
        del sys.modules["src.pipeline.enrichers.cache"]

    from src.pipeline.enrichers.cache import EnricherRedisCache
    c = EnricherRedisCache(name="t", prompt_text="p")
    assert c._enabled is False
    result = await c.get("hash_x")
    assert result is None
    # set 도 no-op (예외 X)
    await c.set("hash_x", "value")
    monkeypatch.delenv("ENRICHER_CACHE_ENABLED")


@pytest.mark.asyncio
async def test_redis_failure_fallback_to_inmem(monkeypatch):
    """Redis 실패 시 in-memory LRU fallback."""
    monkeypatch.setenv("ENRICHER_CACHE_ENABLED", "true")
    if "src.pipeline.enrichers.cache" in sys.modules:
        del sys.modules["src.pipeline.enrichers.cache"]

    from src.pipeline.enrichers.cache import EnricherRedisCache
    c = EnricherRedisCache(name="t", prompt_text="p")

    # Redis 호출 실패 — _get_redis 가 None 반환하도록 강제
    with patch.object(c, "_get_redis", AsyncMock(return_value=None)):
        # set: in-memory 만 저장됨
        await c.set("block_h1", {"data": "fallback"})
        # get: in-memory hit
        result = await c.get("block_h1")
        assert result == {"data": "fallback"}
        assert c.fallback_count == 1


@pytest.mark.asyncio
async def test_circuit_breaker_opens(monkeypatch):
    """연속 실패 시 회로 열림."""
    monkeypatch.setenv("ENRICHER_CACHE_CB_THRESHOLD", "3")
    monkeypatch.setenv("ENRICHER_CACHE_ENABLED", "true")
    if "src.pipeline.enrichers.cache" in sys.modules:
        del sys.modules["src.pipeline.enrichers.cache"]

    from src.pipeline.enrichers.cache import EnricherRedisCache
    c = EnricherRedisCache(name="t", prompt_text="p")

    # mock Redis 가 매번 실패
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=Exception("conn refused"))
    c._redis = mock_redis

    # 3회 실패 → 회로 열림
    for _ in range(3):
        result = await c.get("hash_x")
        assert result is None  # 매번 miss
    # 회로 open
    assert c._cb_open_until > 0
    # 다음 get 은 Redis 호출 안 함 (mock 호출 count 변화 없음)
    prev = mock_redis.get.await_count
    await c.get("hash_y")
    assert mock_redis.get.await_count == prev  # Redis 호출 안 됨


@pytest.mark.asyncio
async def test_get_redis_hit(monkeypatch):
    """Redis 정상 응답 시 hit_count 증가."""
    monkeypatch.setenv("ENRICHER_CACHE_ENABLED", "true")
    if "src.pipeline.enrichers.cache" in sys.modules:
        del sys.modules["src.pipeline.enrichers.cache"]

    from src.pipeline.enrichers.cache import EnricherRedisCache
    c = EnricherRedisCache(name="t", prompt_text="p")

    payload = c._serialize({"k": "v"})
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=payload)
    with patch.object(c, "_get_redis", AsyncMock(return_value=mock_redis)):
        result = await c.get("hash_x")
    assert result == {"k": "v"}
    assert c.hit_count == 1
