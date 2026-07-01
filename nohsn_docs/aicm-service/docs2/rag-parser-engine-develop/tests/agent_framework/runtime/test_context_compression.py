"""ContextCompressor 테스트.

mock LLM client 로 generate() 시뮬레이션. 압축 결과 / EMPTY / cache /
parallel / timeout fallback 검증.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent_framework.runtime.context_compression import (
    Chunk,
    CompressedChunk,
    ContextCompressor,
)


def _resp(text: str) -> SimpleNamespace:
    """LLMResponse-shaped object — .text 속성."""
    return SimpleNamespace(text=text, model="mock", usage={}, latency_ms=10)


def _make_chunk(text: str, *, chunk_id: str = "", score: float = 0.5) -> Chunk:
    return Chunk(text=text, chunk_id=chunk_id, score=score)


# ---- empty / passthrough ----------------------------------------------------


@pytest.mark.asyncio
async def test_empty_chunks_returns_empty():
    """입력 없으면 LLM 호출 0."""
    llm = AsyncMock()
    cc = ContextCompressor(llm)
    result = await cc.compress("뭐든", [])
    assert result == []
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_query_passthrough():
    """query 비면 모든 chunk 원본 passthrough — LLM 호출 0."""
    llm = AsyncMock()
    cc = ContextCompressor(llm)
    chunks = [_make_chunk("문서 본문 1", chunk_id="a"), _make_chunk("문서 본문 2", chunk_id="b")]
    result = await cc.compress("", chunks)
    assert len(result) == 2
    assert result[0].text == "문서 본문 1"
    assert result[0].compression_ratio == 1.0
    assert result[0].relevant is True
    assert result[1].text == "문서 본문 2"
    llm.generate.assert_not_awaited()


# ---- relevant compression ---------------------------------------------------


@pytest.mark.asyncio
async def test_relevant_chunk_compressed():
    """LLM 이 인용 부분 반환 → CompressedChunk.text = 압축본."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("영업시간은 10시-20시"))
    cc = ContextCompressor(llm)
    chunk = _make_chunk(
        "본 매장은 영업시간은 10시-20시 입니다. 그리고 다른 잡담 무관 정보 많음.",
        chunk_id="c1",
    )
    result = await cc.compress("영업시간 알려줘", [chunk])
    assert len(result) == 1
    out = result[0]
    assert out.text == "영업시간은 10시-20시"
    assert out.relevant is True
    assert 0.0 < out.compression_ratio < 1.0  # 원본보다 짧음
    assert out.original_text == chunk.text
    assert out.chunk_id == "c1"


@pytest.mark.asyncio
async def test_irrelevant_chunk_marked_empty():
    """LLM 이 'EMPTY' 반환 → relevant=False, text=''"""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("EMPTY"))
    cc = ContextCompressor(llm)
    chunk = _make_chunk("완전 다른 주제 — 날씨 정보", chunk_id="c2")
    result = await cc.compress("영업시간?", [chunk])
    assert len(result) == 1
    assert result[0].text == ""
    assert result[0].relevant is False
    assert result[0].compression_ratio == 0.0
    assert result[0].original_text == "완전 다른 주제 — 날씨 정보"


@pytest.mark.asyncio
async def test_empty_response_marked_irrelevant():
    """LLM 이 빈 문자열 / 따옴표 EMPTY 반환 → 무관 처리."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("\"EMPTY\""))
    cc = ContextCompressor(llm)
    chunk = _make_chunk("xyz", chunk_id="c3")
    result = await cc.compress("query", [chunk])
    assert result[0].relevant is False
    assert result[0].text == ""


# ---- parallel ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_5_chunks():
    """5 chunks → LLM 5회 호출. 결과 *순서 유지*."""
    llm = AsyncMock()

    async def fake_generate(req):
        # prompt 안 chunk_text 의 첫 단어를 그대로 반환.
        prompt = getattr(req, "prompt", None) or req.get("prompt")
        # _DEFAULT_COMPRESSION_PROMPT 의 chunk_text 시작 위치 추출.
        marker = "원문:\n"
        idx = prompt.find(marker)
        chunk_text = prompt[idx + len(marker) :].split("\n")[0]
        # 첫 단어 인용.
        first_word = chunk_text.split()[0] if chunk_text.split() else "EMPTY"
        return _resp(first_word)

    llm.generate = AsyncMock(side_effect=fake_generate)
    cc = ContextCompressor(llm, parallelism=5)
    chunks = [
        _make_chunk(f"alpha{i} bravo charlie", chunk_id=f"id{i}", score=float(i))
        for i in range(5)
    ]
    result = await cc.compress("질의", chunks)
    assert len(result) == 5
    assert llm.generate.await_count == 5
    # 순서 유지 — 각 결과 첫 단어가 alpha0..alpha4 순서.
    for i, out in enumerate(result):
        assert out.text == f"alpha{i}"
        assert out.chunk_id == f"id{i}"
        assert out.score == float(i)


# ---- cache ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_llm():
    """동일 (query, chunk_id) → 두 번째 호출은 LLM 호출 0."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("압축결과"))
    cc = ContextCompressor(llm)
    chunk = _make_chunk("본문", chunk_id="c1")
    a = await cc.compress("질의", [chunk])
    b = await cc.compress("질의", [chunk])
    assert llm.generate.await_count == 1
    assert a[0].text == "압축결과"
    assert b[0].text == "압축결과"


@pytest.mark.asyncio
async def test_cache_per_chunk_id_isolation():
    """같은 query, *다른* chunk_id → 별도 LLM 호출."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("압축"))
    cc = ContextCompressor(llm)
    a = _make_chunk("본문 A", chunk_id="cA")
    b = _make_chunk("본문 B", chunk_id="cB")
    await cc.compress("질의", [a, b])
    assert llm.generate.await_count == 2


@pytest.mark.asyncio
async def test_cache_ttl_expires():
    """TTL 경과 시 재호출."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("압축"))
    fake_now = [1000.0]

    def clock() -> float:
        return fake_now[0]

    cc = ContextCompressor(llm, cache_ttl_s=30.0, clock=clock)
    chunk = _make_chunk("본문", chunk_id="c1")
    await cc.compress("q", [chunk])
    fake_now[0] = 1100.0  # 100s 경과
    await cc.compress("q", [chunk])
    assert llm.generate.await_count == 2


# ---- fail-open --------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_chunk_timeout_fallback():
    """단일 LLM 호출 timeout → 해당 chunk 만 원본 passthrough."""
    llm = AsyncMock()

    async def slow(req):
        await asyncio.sleep(2.0)
        return _resp("never")

    llm.generate = AsyncMock(side_effect=slow)
    cc = ContextCompressor(llm, per_chunk_timeout_s=0.05, timeout_s=0.5)
    chunk = _make_chunk("원본 본문", chunk_id="c1")
    result = await cc.compress("질의", [chunk])
    # fail-open — 원본 그대로.
    assert len(result) == 1
    assert result[0].text == "원본 본문"
    assert result[0].compression_ratio == 1.0
    assert result[0].relevant is True


@pytest.mark.asyncio
async def test_llm_exception_fallback():
    """LLM 예외 → 해당 chunk 원본 passthrough."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("vllm down"))
    cc = ContextCompressor(llm)
    chunks = [_make_chunk("X", chunk_id="c1"), _make_chunk("Y", chunk_id="c2")]
    result = await cc.compress("q", chunks)
    assert len(result) == 2
    assert result[0].text == "X"
    assert result[1].text == "Y"
    assert all(r.relevant is True for r in result)


@pytest.mark.asyncio
async def test_global_timeout_fallback():
    """전체 timeout 초과 → 미완 chunks 원본 passthrough."""
    llm = AsyncMock()

    async def slow(req):
        await asyncio.sleep(2.0)
        return _resp("late")

    llm.generate = AsyncMock(side_effect=slow)
    cc = ContextCompressor(
        llm,
        per_chunk_timeout_s=5.0,  # per-chunk 은 길지만
        timeout_s=0.05,  # 글로벌은 50ms
        parallelism=2,
    )
    chunks = [_make_chunk(f"본문{i}", chunk_id=f"c{i}") for i in range(3)]
    result = await cc.compress("q", chunks)
    assert len(result) == 3
    # 전부 원본 passthrough (compression_ratio=1.0).
    for c, r in zip(chunks, result):
        assert r.text == c.text
        assert r.compression_ratio == 1.0


@pytest.mark.asyncio
async def test_extract_text_handles_dict_response():
    """LLMResponse 가 dict 형이어도 .text 추출."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value={"text": "압축결과", "usage": {}})
    cc = ContextCompressor(llm)
    chunk = _make_chunk("원본", chunk_id="c1")
    result = await cc.compress("q", [chunk])
    assert result[0].text == "압축결과"
    assert result[0].relevant is True


@pytest.mark.asyncio
async def test_chunk_without_id_uses_text_hash():
    """chunk_id 비어있어도 cache key 생성 (text hash)."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("ok"))
    cc = ContextCompressor(llm)
    c1 = _make_chunk("본문 X")  # chunk_id 없음
    await cc.compress("q", [c1])
    await cc.compress("q", [c1])  # 동일 본문 → cache hit
    assert llm.generate.await_count == 1


def test_dataclass_immutable():
    cc = CompressedChunk(text="t", original_text="o", chunk_id="c")
    with pytest.raises((AttributeError, Exception)):
        cc.text = "x"  # type: ignore[misc]
