"""D56 §A PR-A — BGEM3Embedder proxy 모드 unit test.

검증:
- EMBEDDING_PROXY_URL 설정 시 FlagEmbedding import 안 함 (proxy 모드)
- proxy /embed POST 호출 + sparse key int 캐스팅
- 429 / 5xx 재시도 (Retry-After 존중)
- proxy 도달 불가 시 hard fail (RuntimeError)
- 캐시 히트 시 proxy 호출 0
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _make_response(status_code: int = 200, json_data: dict | None = None,
                   headers: dict | None = None) -> MagicMock:
    """httpx.Response mock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    resp.headers = headers or {}
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        req = Request("POST", "http://test/embed")
        real_resp = Response(status_code, request=req)
        real_resp._content = b"err"
        if status_code not in (429, 502, 503, 504):
            resp.raise_for_status = MagicMock(
                side_effect=HTTPStatusError("err", request=req, response=real_resp)
            )
        else:
            resp.raise_for_status = MagicMock()
    else:
        resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_proxy_mode_no_flagembedding_import(monkeypatch):
    """EMBEDDING_PROXY_URL 설정 시 FlagEmbedding 로드 X."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    # settings reload
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    e = BGEM3Embedder()
    assert e._use_proxy is True
    assert e._proxy_url == "http://test:7130"
    # _ensure_model 은 proxy 모드에서 호출되면 raise
    with pytest.raises(RuntimeError, match="proxy mode"):
        e._ensure_model()


@pytest.mark.asyncio
async def test_proxy_embed_single_success(monkeypatch):
    """proxy /embed 200 응답 → EmbeddingResult dense + sparse 정상."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder

    e = BGEM3Embedder(embedding_cache=MagicMock(get=AsyncMock(return_value=None),
                                                 set=AsyncMock()))

    fake_resp = _make_response(200, {
        "dense": [0.1, 0.2, 0.3],
        "sparse": {"33600": 0.25, "31": 0.24},
    })
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_client.is_closed = False

    with patch.object(e, "_get_http_client", AsyncMock(return_value=mock_client)):
        result = await e._embed_via_proxy_one("hello")

    assert result.dense == [0.1, 0.2, 0.3]
    # sparse key int 캐스팅 검증 (GPT-5 권고)
    assert result.sparse == {33600: 0.25, 31: 0.24}
    assert all(isinstance(k, int) for k in result.sparse.keys())


@pytest.mark.asyncio
async def test_proxy_retry_on_429(monkeypatch):
    """429 응답 시 Retry-After 존중 + 재시도."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder

    e = BGEM3Embedder()

    # 첫 호출 429, 두번째 200
    resp_429 = _make_response(429, headers={"Retry-After": "0.01"})
    resp_200 = _make_response(200, {"dense": [1.0], "sparse": {"1": 0.5}})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[resp_429, resp_200])
    mock_client.is_closed = False

    with patch.object(e, "_get_http_client", AsyncMock(return_value=mock_client)):
        result = await e._embed_via_proxy_one("retry test")

    assert result.dense == [1.0]
    assert result.sparse == {1: 0.5}
    assert mock_client.post.await_count == 2


@pytest.mark.asyncio
async def test_proxy_hard_fail_on_unreachable(monkeypatch):
    """proxy 도달 불가 시 RuntimeError (로컬 fallback X — hard fail)."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    import httpx

    e = BGEM3Embedder()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(
        side_effect=httpx.ConnectError("conn refused")
    )
    mock_client.is_closed = False

    with patch.object(e, "_get_http_client", AsyncMock(return_value=mock_client)):
        with pytest.raises(RuntimeError, match="unreachable"):
            await e._embed_via_proxy_one("fail")


@pytest.mark.asyncio
async def test_proxy_batch_parallel(monkeypatch):
    """배치 호출 시 asyncio.gather 로 N 병렬."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    e = BGEM3Embedder()

    fake_resp = _make_response(200, {"dense": [0.5], "sparse": {"7": 1.0}})
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_client.is_closed = False

    with patch.object(e, "_get_http_client", AsyncMock(return_value=mock_client)):
        results = await e._embed_via_proxy_batch(["a", "b", "c"])

    assert len(results) == 3
    assert all(r.dense == [0.5] for r in results)
    assert mock_client.post.await_count == 3


@pytest.mark.asyncio
async def test_proxy_cache_hit_skips_proxy(monkeypatch):
    """캐시 히트 시 proxy 호출 0."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder, EmbeddingResult

    cached = EmbeddingResult(dense=[9.9], sparse={42: 1.0})
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=cached)
    mock_cache.set = AsyncMock()

    e = BGEM3Embedder(embedding_cache=mock_cache)

    # _embed_via_proxy_one mock — 호출되면 fail
    with patch.object(e, "_embed_via_proxy_one",
                      AsyncMock(side_effect=AssertionError("proxy should NOT be called"))):
        result = await e.embed_single("cached text")

    assert result.dense == [9.9]
    assert result.sparse == {42: 1.0}
    mock_cache.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_proxy_retry_on_500(monkeypatch):
    """500 응답도 재시도 (GPT-5 post v1: 모든 5xx 재시도)."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    e = BGEM3Embedder()

    resp_500 = _make_response(500)
    resp_200 = _make_response(200, {"dense": [2.0], "sparse": {"5": 0.7}})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[resp_500, resp_200])
    mock_client.is_closed = False

    with patch.object(e, "_get_http_client", AsyncMock(return_value=mock_client)):
        result = await e._embed_via_proxy_one("retry 500")

    assert result.dense == [2.0]
    assert result.sparse == {5: 0.7}
    assert mock_client.post.await_count == 2


@pytest.mark.asyncio
async def test_proxy_no_sleep_on_last_attempt(monkeypatch):
    """마지막 retry 시도에서 sleep 생략 (GPT-5 post v1: 불필요 대기 방지)."""
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "http://test:7130")
    from src.common import config
    config.settings.EMBEDDING_PROXY_URL = "http://test:7130"  # type: ignore

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    e = BGEM3Embedder()

    # 모든 시도 500 응답 — 마지막 시도 후에는 sleep 호출되지 않아야 함
    resp_500 = _make_response(500)
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=resp_500)
    mock_client.is_closed = False

    sleep_calls: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    import src.pipeline.embedders.bge_m3 as bge_mod
    with patch.object(e, "_get_http_client", AsyncMock(return_value=mock_client)):
        with patch.object(bge_mod.asyncio, "sleep", fake_sleep):
            with pytest.raises(RuntimeError, match="unreachable"):
                await e._embed_via_proxy_one("always 500")

    # MAX_RETRIES=3 → 시도 4회 (attempt 0/1/2/3), sleep 은 처음 3회만 (attempt < MAX)
    # _PROXY_MAX_RETRIES = 3 → sleep 호출 횟수 == 3 (마지막 시도는 break 로 sleep 없음)
    assert len(sleep_calls) == 3, (
        f"sleep should be called 3 times (attempts 0,1,2), got {len(sleep_calls)}"
    )


@pytest.mark.asyncio
async def test_local_mode_when_proxy_unset(monkeypatch):
    """EMBEDDING_PROXY_URL 미설정 시 로컬 모드 (use_proxy=False)."""
    monkeypatch.delenv("EMBEDDING_PROXY_URL", raising=False)
    from src.common import config
    # 사전에 settings 가 .env 로 채워졌을 수 있어 명시 빈 문자열
    config.settings.EMBEDDING_PROXY_URL = ""  # type: ignore

    # bge_m3 모듈 reload (settings 캐시 회피)
    if "src.pipeline.embedders.bge_m3" in sys.modules:
        del sys.modules["src.pipeline.embedders.bge_m3"]

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    e = BGEM3Embedder()
    assert e._use_proxy is False
