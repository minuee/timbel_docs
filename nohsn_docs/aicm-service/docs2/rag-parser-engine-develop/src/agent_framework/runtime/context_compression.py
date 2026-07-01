"""ContextCompressor — Phase 1.6 retriever 강화 (Contextual Compression).

retrieval 결과 chunks 를 LLM 으로 한 번 더 거쳐 query 와 무관한 부분을
잘라낸다 (요약 X — *직접 인용* prefer). 결과:

- token 절감 (각 chunk 1/3~1/2 길이로 압축)
- LLM 집중도 ↑ (prompt 신호 대 잡음 비율 개선)
- 비용 ↓ (LLM 응답 generation 의 input 감소)

원칙:
- 현재 PR 은 *standalone* 모듈 — 호출 callsite 없음. SOP/Tool RAG 통합은
  flag-gated (`FEATURE_CONTEXT_COMPRESSION`). 시연 path 무영향.
- 의존성 추가 X — vLLM 클라이언트 (`src.common.llm`) 재사용.
- LLM 호출 5개 병렬 (asyncio.gather) — 500ms 전체 timeout.
- (query_hash, chunk_id) → 30s LRU cache — 동일 turn 내 재사용 + multi-turn 부분 절약.
- timeout / LLM 실패 시 graceful: *원본 chunk* 그대로 반환 (fail-open).

설계 참조:
- spec: docs/superpowers/specs/2026-05-07-retriever-enhancement.md (TBD)
- 사용자 권고 (2026-05-07): "retrieval → 압축 → prompt inject"
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from src.common.logging import get_logger

log = get_logger(__name__)


# --- Constants ----------------------------------------------------------------

DEFAULT_TIMEOUT_S = 0.5  # 500ms 전체 (parallel)
DEFAULT_PER_CHUNK_TIMEOUT_S = 0.45  # 단일 LLM 호출 timeout (전체보다 약간 짧게)
DEFAULT_PARALLELISM = 5  # asyncio.gather max 동시 호출
CACHE_TTL_S = 30.0
CACHE_MAX_ENTRIES = 1000
DEFAULT_MAX_TOKENS = 256  # 압축 결과는 짧음
DEFAULT_TEMPERATURE = 0.0  # deterministic — "직접 인용" 강제


# --- Public dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """ContextCompressor 입력. retriever 가 반환하는 표준 형식."""

    text: str
    chunk_id: str = ""  # 중복 제거 + cache key
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompressedChunk:
    """ContextCompressor 출력.

    Attributes:
        text: 압축된 본문 (verbatim 인용 — 무관 부분 제거).
            relevant=False 시 빈 문자열.
        original_text: 원본 chunk 본문 (디버그/감사용).
        chunk_id: 원본 chunk_id passthrough.
        score: 원본 score passthrough.
        relevant: True 면 query 와 관련. False 면 LLM 이 무관 판정 → 제외 후보.
        compression_ratio: len(text) / max(len(original_text), 1).
            1.0 = 압축 없음, 0.0 = 완전 제거.
        metadata: 원본 metadata passthrough.
    """

    text: str
    original_text: str
    chunk_id: str = ""
    score: float = 0.0
    relevant: bool = True
    compression_ratio: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


# --- LLM 인터페이스 (loose protocol — 테스트 시 mock 주입) ---------------------


class LLMClientLike(Protocol):
    """src.common.llm.base.BaseLLMClient 호환 최소 인터페이스.

    테스트 시 AsyncMock 으로 주입 — 실 호출 시 Gemma/Qwen client 그대로 사용.
    """

    async def generate(self, request: Any) -> Any: ...


# --- Default prompt (KMS-Plus 톤) ---------------------------------------------

_DEFAULT_COMPRESSION_PROMPT = """\
당신은 검색 결과 압축기입니다. 사용자 질의와 *직접 관련된* 부분만 원문에서 *그대로 인용*하세요.

규칙:
1. 요약 금지 — 문서 원문의 문장/구절을 그대로 복사.
2. 무관한 문장은 제외.
3. 관련 부분이 *전혀 없으면* 정확히 "EMPTY" 만 반환.
4. 출력은 순수 텍스트 — 머리말/꼬리말/설명 X.

사용자 질의:
{query}

원문:
{chunk_text}

관련 부분 (verbatim):"""


# --- TTL LRU cache ------------------------------------------------------------


class _TTLCache:
    """OrderedDict 기반 (query_hash, chunk_id) → CompressedChunk LRU.

    단일 asyncio loop 가정 — thread safe 아님.
    """

    def __init__(self, max_size: int = CACHE_MAX_ENTRIES, ttl_s: float = CACHE_TTL_S, *, clock: Callable[[], float] | None = None) -> None:
        self._max = max_size
        self._ttl = ttl_s
        self._clock = clock or time.monotonic
        self._data: OrderedDict[tuple[str, str], tuple[float, CompressedChunk]] = OrderedDict()

    def get(self, key: tuple[str, str]) -> Optional[CompressedChunk]:
        item = self._data.get(key)
        if item is None:
            return None
        ts, value = item
        if self._clock() - ts > self._ttl:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: tuple[str, str], value: CompressedChunk) -> None:
        self._data[key] = (self._clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


# --- Helpers ------------------------------------------------------------------


def _query_hash(query: str) -> str:
    """short stable hash — cache key 의 일부."""
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]


def _chunk_key(chunk: Chunk) -> str:
    """chunk_id 비어있으면 본문 hash 로 대체."""
    if chunk.chunk_id:
        return chunk.chunk_id
    return hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()[:16]


def _is_empty_response(text: str) -> bool:
    """LLM 이 'EMPTY' / 빈 응답 / whitespace 만 반환했는지 판정."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    # 'EMPTY' literal — 대소문자 무시.
    if stripped.upper() == "EMPTY":
        return True
    # 따옴표로 감싸진 EMPTY 도 허용.
    if stripped.upper().strip("\"'") == "EMPTY":
        return True
    return False


# --- ContextCompressor -------------------------------------------------------


class ContextCompressor:
    """retrieval chunks → LLM 압축 → CompressedChunk 리스트.

    Args:
        llm_client: ``BaseLLMClient`` 호환 — ``await llm_client.generate(LLMRequest)``.
            테스트 시 AsyncMock 주입 가능.
        prompt_template: chunk 압축 prompt — ``{query}`` / ``{chunk_text}`` 포함.
            None 이면 default (verbatim quote KOR/ENG).
        timeout_s: 전체 압축 (parallel) timeout. 초과 시 fail-open (원본 반환).
        per_chunk_timeout_s: 단일 LLM 호출 timeout.
        parallelism: 동시 LLM 호출 max — semaphore 로 제한.
        cache_ttl_s: (query_hash, chunk_id) cache TTL.
        clock: 테스트 시간 주입.

    공개 메서드:
        compress(query, chunks) → list[CompressedChunk]
            - cache hit chunks 는 LLM 호출 0
            - cache miss chunks 만 5개씩 병렬 LLM 호출
            - 결과 'EMPTY' / 무응답 chunks 는 relevant=False
    """

    def __init__(
        self,
        llm_client: LLMClientLike,
        *,
        prompt_template: Optional[str] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        per_chunk_timeout_s: float = DEFAULT_PER_CHUNK_TIMEOUT_S,
        parallelism: int = DEFAULT_PARALLELISM,
        cache_ttl_s: float = CACHE_TTL_S,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._llm = llm_client
        self._prompt = prompt_template or _DEFAULT_COMPRESSION_PROMPT
        self._timeout_s = float(timeout_s)
        self._per_chunk_timeout_s = float(per_chunk_timeout_s)
        self._parallelism = max(1, int(parallelism))
        self._max_tokens = int(max_tokens)
        self._temperature = float(temperature)
        self._cache = _TTLCache(max_size=CACHE_MAX_ENTRIES, ttl_s=cache_ttl_s, clock=clock)
        self._clock = clock or time.monotonic

    # ----- public API -----

    async def compress(
        self,
        query: str,
        chunks: list[Chunk],
    ) -> list[CompressedChunk]:
        """chunks 압축. 빈 입력 / 빈 query → passthrough 빈 리스트.

        Args:
            query: 사용자 질의 (failure 압축 prompt 의 {query}).
            chunks: retriever 결과.

        Returns:
            list[CompressedChunk] — 입력과 *동일 순서*. relevant=False 라도
            리스트에 포함 (caller 가 filter 결정). compression_ratio 로
            압축 정도 측정 가능.

        Behavior:
            - query 비어있으면: 모든 chunk 를 passthrough (compression_ratio=1.0).
            - 전체 timeout 초과: 미완료 chunks 는 *원본* CompressedChunk 로 fail-open.
            - LLM 단일 호출 실패 (timeout / 예외): 해당 chunk 만 fail-open.
        """
        if not chunks:
            return []

        q = (query or "").strip()
        if not q:
            return [self._passthrough(c) for c in chunks]

        qhash = _query_hash(q)
        results: list[Optional[CompressedChunk]] = [None] * len(chunks)

        # cache pass — hit 인 항목 채워두고, miss 만 LLM 호출 대상.
        miss_indices: list[int] = []
        for i, c in enumerate(chunks):
            key = (qhash, _chunk_key(c))
            cached = self._cache.get(key)
            if cached is not None:
                results[i] = cached
            else:
                miss_indices.append(i)

        if miss_indices:
            await self._compress_misses(q, qhash, chunks, miss_indices, results)

        # None 이 남으면 (글로벌 timeout 후 미완) 원본 passthrough 로 채움.
        out: list[CompressedChunk] = []
        for i, r in enumerate(results):
            if r is None:
                out.append(self._passthrough(chunks[i]))
            else:
                out.append(r)
        return out

    def clear_cache(self) -> None:
        """test/운영 점검용."""
        self._cache.clear()

    # ----- internals -----

    async def _compress_misses(
        self,
        query: str,
        qhash: str,
        chunks: list[Chunk],
        miss_indices: list[int],
        results: list[Optional[CompressedChunk]],
    ) -> None:
        """LLM 호출 — semaphore 제한 + 전체 timeout."""
        sem = asyncio.Semaphore(self._parallelism)

        async def _one(idx: int) -> None:
            chunk = chunks[idx]
            async with sem:
                compressed = await self._compress_one(query, chunk)
            # cache 저장 (relevant 무관 — 'EMPTY' 캐시도 의미 있음)
            self._cache.set((qhash, _chunk_key(chunk)), compressed)
            results[idx] = compressed

        tasks = [asyncio.create_task(_one(i)) for i in miss_indices]
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning(
                "context_compression_global_timeout",
                timeout_s=self._timeout_s,
                pending=sum(1 for t in tasks if not t.done()),
            )
            # 미완 task cancel — caller 가 fail-open 으로 원본 inject.
            for t in tasks:
                if not t.done():
                    t.cancel()
            # cancel 정리 대기 (suppress).
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:  # noqa: BLE001
                pass

    async def _compress_one(self, query: str, chunk: Chunk) -> CompressedChunk:
        """단일 chunk 압축. timeout / 예외 → fail-open (원본)."""
        prompt = self._prompt.format(query=query, chunk_text=chunk.text)
        try:
            response = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=self._per_chunk_timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning(
                "context_compression_per_chunk_timeout",
                chunk_id=chunk.chunk_id,
                timeout_s=self._per_chunk_timeout_s,
            )
            return self._passthrough(chunk)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "context_compression_llm_failed",
                chunk_id=chunk.chunk_id,
                error=str(exc),
            )
            return self._passthrough(chunk)

        text = self._extract_text(response)
        if _is_empty_response(text):
            return CompressedChunk(
                text="",
                original_text=chunk.text,
                chunk_id=chunk.chunk_id,
                score=chunk.score,
                relevant=False,
                compression_ratio=0.0,
                metadata=dict(chunk.metadata),
            )

        # 압축률 계산
        compressed = text.strip()
        original_len = max(len(chunk.text), 1)
        ratio = min(1.0, len(compressed) / original_len)
        return CompressedChunk(
            text=compressed,
            original_text=chunk.text,
            chunk_id=chunk.chunk_id,
            score=chunk.score,
            relevant=True,
            compression_ratio=ratio,
            metadata=dict(chunk.metadata),
        )

    async def _call_llm(self, prompt: str) -> Any:
        """LLMRequest 빌드 + generate.

        BaseLLMClient.generate(LLMRequest) → LLMResponse 가정.
        테스트 시 AsyncMock 으로 임의 객체 반환 가능 — _extract_text 가 흡수.
        """
        # lazy import — 의존성 사이클 회피.
        try:
            from src.common.llm.base import LLMRequest

            req = LLMRequest(
                prompt=prompt,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
        except Exception:  # noqa: BLE001
            # LLMRequest import 실패 — fallback dict (mock 호환).
            req = {  # type: ignore[assignment]
                "prompt": prompt,
                "max_tokens": self._max_tokens,
                "temperature": self._temperature,
            }
        return await self._llm.generate(req)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """LLMResponse / dict / str 등에서 본문 추출."""
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        # pydantic LLMResponse → .text
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        # dict 형
        if isinstance(response, dict):
            for key in ("text", "content", "output"):
                v = response.get(key)
                if isinstance(v, str):
                    return v
        return ""

    @staticmethod
    def _passthrough(chunk: Chunk) -> CompressedChunk:
        """fail-open / no-op — 원본 그대로."""
        return CompressedChunk(
            text=chunk.text,
            original_text=chunk.text,
            chunk_id=chunk.chunk_id,
            score=chunk.score,
            relevant=True,
            compression_ratio=1.0,
            metadata=dict(chunk.metadata),
        )
