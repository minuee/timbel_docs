"""Tool RAG core module — Phase 1.5B-α (B 옵션 scope).

`plan_orchestrator` 의 `CATEGORY_TOOLS` 하드코딩 narrowing 을 BGE-M3 + Qdrant
retrieval 로 대체한다. utterance_classifier 는 *유지* — 이 모듈은 narrowing
경로만 대체한다.

이번 PR 은 *standalone module* 만 — `plan_orchestrator` 통합은 Round 2.
`FEATURE_TOOL_RAG=false` (default) 이므로 시연 path 무영향.

핵심 책임:
  - `upsert_tool(tool_meta)` — 도구 메타 → BGE-M3 임베딩 → Qdrant upsert
  - `delete_tool(name)` — Qdrant delete by stable id
  - `retrieve(query, top_k, allowed_tools)` — query embedding → top_k 검색
    + allowed_tools 교집합 (Phase 1.5A 권한 보존)
  - `reconcile(tools)` — 부팅 시 registry vs Qdrant drift 자동 정합

cross-cutting:
  - 200ms timeout (asyncio.wait_for) — caller 가 fallback 가능하게 빠른 실패
  - circuit breaker — 5xx 5회 누적 시 OPEN 5분, 그 동안 즉시 빈 리스트
  - LRU 캐시 — query embedding (1000 entry / 5분 TTL) + retrieve 결과 (30초)
  - cold-start fallback — 캐시 비어있을 때 retrieval 실패 시 빈 리스트 →
    caller 가 CATEGORY_TOOLS fallback

설계 원칙:
  - 코드 호출 안 됨 (flag-gated) — 시연 path 보존이 1순위
  - 임베딩 / Qdrant 클라이언트는 lazy init (테스트 시 mock 주입 가능)
  - 모든 외부 호출은 timeout + 예외 swallow → caller 가 빈 리스트 받음
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional

from src.common.logging import get_logger

log = get_logger(__name__)


# ----- Constants -----

COLLECTION_NAME = "tool_catalog_v1"
DENSE_DIM = 1024  # BGE-M3 dense
DEFAULT_TIMEOUT_S = 0.2  # 200 ms
DEFAULT_TOP_K = 8

# circuit breaker
CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_OPEN_SECONDS = 5 * 60  # 5 분

# LRU 캐시
QUERY_EMBED_LRU_SIZE = 1000
QUERY_EMBED_TTL_S = 5 * 60  # 5 분
RETRIEVE_LRU_SIZE = 1000
RETRIEVE_TTL_S = 30  # 30 초

# 임베딩 입력 길이 — BGE-M3 권고 max length 512 토큰. char 기준 보수적으로 잘라
# token 폭주 방지 (한 char ≈ 0.5~1 token).
MAX_EMBED_INPUT_CHARS = 1500


# ----- Public dataclasses -----

@dataclass
class ToolCandidate:
    """Tool RAG retrieve 결과 한 건.

    LLM plan prompt 의 "available tools" 섹션 입력으로 사용된다.
    """
    name: str
    score: float
    description: str
    triggered_by_intents: list[str] = field(default_factory=list)


# ----- Internal helpers -----

def _stable_point_id(tool_name: str) -> str:
    """tool name → stable hex point id (Qdrant 가 받는 형식).

    Qdrant 는 PointStruct.id 로 unsigned int 또는 UUID/hex 문자열 허용.
    sha1 prefix 16 char (hex) 사용 — 충돌 위험 ≈ 0 (도구 ~수백개).
    """
    h = hashlib.sha1(tool_name.encode("utf-8")).hexdigest()
    # Qdrant accepts int, UUID, or string-of-int.
    # sha1 hex 16 → uuid-shape conversion 가장 안전.
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _build_embed_text(meta: dict[str, Any]) -> str:
    """도구 메타 → BGE-M3 임베딩 입력 문자열.

    포맷 (spec §2.1 변형):
        {name}\n{description}\n의도: a | b | c\n예시: u1 | u2 | u3

    spec 의 변형 — 줄바꿈 + label 로 BGE-M3 가 의도/예시 섹션 구분 가능하게.
    truncate 는 char 단위 (BGE-M3 token 한도 512 보수적 회피).
    """
    name = (meta.get("name") or "").strip()
    description = (meta.get("description") or "").strip()
    intents = meta.get("triggered_by_intents") or []
    utterances = meta.get("example_utterances") or []
    if not isinstance(intents, list):
        intents = list(intents)  # type: ignore[arg-type]
    if not isinstance(utterances, list):
        utterances = list(utterances)  # type: ignore[arg-type]

    intents_str = " | ".join(str(x) for x in intents if x)
    # 예시는 상위 3 개 — 너무 길면 의도 신호 희석
    utter_str = " | ".join(str(x) for x in utterances[:3] if x)

    parts = [name]
    if description:
        parts.append(description)
    parts.append(f"의도: {intents_str}")
    parts.append(f"예시: {utter_str}")
    text = "\n".join(parts)
    if len(text) > MAX_EMBED_INPUT_CHARS:
        text = text[:MAX_EMBED_INPUT_CHARS]
    return text


# ----- Time-aware LRU cache -----

class _TTLCache:
    """OrderedDict 기반 size+TTL LRU. 단일 process / 단일 thread 가정.

    Tool RAG 는 plan_orchestrator 단일 호출 흐름에서만 쓰이므로 thread safe
    아님으로 충분 (asyncio 단일 loop).
    """
    def __init__(self, max_size: int, ttl_seconds: float) -> None:
        self._max = max_size
        self._ttl = ttl_seconds
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    def get(self, key: Any) -> Optional[Any]:
        item = self._data.get(key)
        if item is None:
            return None
        ts, value = item
        if time.monotonic() - ts > self._ttl:
            # expired
            self._data.pop(key, None)
            return None
        # LRU bump
        self._data.move_to_end(key)
        return value

    def set(self, key: Any, value: Any) -> None:
        self._data[key] = (time.monotonic(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


# ----- Circuit breaker -----

class _CircuitBreaker:
    """단순 카운트형 breaker — 실패 N회 누적 → OPEN T초 → 자동 close.

    half-open 상태 없음 — T초 후 첫 호출 시도, 실패 시 다시 OPEN.
    """
    def __init__(
        self,
        failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
        open_seconds: float = CIRCUIT_OPEN_SECONDS,
    ) -> None:
        self._threshold = failure_threshold
        self._open_seconds = open_seconds
        self._failure_count = 0
        self._opened_at: Optional[float] = None

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def opened_at(self) -> Optional[float]:
        return self._opened_at

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._open_seconds:
            # auto close — 실패 카운트 reset
            self._opened_at = None
            self._failure_count = 0
            return False
        return True

    def record_success(self) -> None:
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._opened_at = time.monotonic()


# ----- ToolRAG class -----

# Type aliases for injected backends — 테스트 시 mock 주입.
EmbedFn = Callable[[str], Awaitable[list[float]]]
QdrantBackend = Any  # AsyncQdrantClient 또는 mock


class ToolRAG:
    """Tool RAG core.

    인스턴스는 부팅 시 한 번 생성 — engine init 또는 startup hook 에서
    `await tool_rag.reconcile(registry.list_meta())` 호출하면 Qdrant 와
    registry 가 drift 정합된다.

    `FEATURE_TOOL_RAG=false` 이면 caller 가 이 인스턴스를 *호출 안 함* —
    인스턴스 생성만으로 부수효과 0.
    """

    def __init__(
        self,
        qdrant_url: Optional[str] = None,
        embedding_url: Optional[str] = None,
        collection: str = COLLECTION_NAME,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        # 테스트 / 통합 시 백엔드 주입
        embed_fn: Optional[EmbedFn] = None,
        qdrant_client: Optional[QdrantBackend] = None,
    ) -> None:
        self._qdrant_url = qdrant_url
        self._embedding_url = embedding_url
        self._collection = collection
        self._timeout_s = timeout_s

        # lazy backends
        self._embed_fn: Optional[EmbedFn] = embed_fn
        self._qdrant: Optional[QdrantBackend] = qdrant_client

        # 캐시 / circuit
        self._embed_cache = _TTLCache(QUERY_EMBED_LRU_SIZE, QUERY_EMBED_TTL_S)
        self._retrieve_cache = _TTLCache(RETRIEVE_LRU_SIZE, RETRIEVE_TTL_S)
        self._breaker = _CircuitBreaker()

    # ----- backend lazy init -----

    async def _get_embed_fn(self) -> EmbedFn:
        """BGE-M3 임베딩 함수 — search.embedding_proxy 의 dense vector만 추출."""
        if self._embed_fn is not None:
            return self._embed_fn

        from src.search.embedding_proxy import EmbeddingProxyClient
        client = EmbeddingProxyClient(proxy_url=self._embedding_url)

        async def _embed(text: str) -> list[float]:
            dense, _sparse = await client.embed(text)
            return dense

        self._embed_fn = _embed
        return self._embed_fn

    async def _get_qdrant(self) -> QdrantBackend:
        """AsyncQdrantClient — 기존 search 모듈과 동일 패턴."""
        if self._qdrant is not None:
            return self._qdrant
        from qdrant_client import AsyncQdrantClient
        from src.common.config import settings
        url = self._qdrant_url or settings.QDRANT_URL
        api_key = (settings.QDRANT_API_KEY or "").strip() or None
        self._qdrant = AsyncQdrantClient(
            url=url, api_key=api_key, prefer_grpc=False, timeout=15
        )
        return self._qdrant

    # ----- query embedding (with cache + circuit) -----

    async def _embed_query(self, query: str) -> Optional[list[float]]:
        """query → BGE-M3 dense vector. 캐시 hit 시 임베딩 호출 0.

        circuit OPEN / timeout / 예외 시 None 반환 (caller 가 빈 리스트 fallback).
        """
        cached = self._embed_cache.get(query)
        if cached is not None:
            return cached

        if self._breaker.is_open():
            log.debug("tool_rag_circuit_open_skip_embed", query_len=len(query))
            return None

        try:
            embed_fn = await self._get_embed_fn()
            vector = await asyncio.wait_for(embed_fn(query), timeout=self._timeout_s)
            if not vector:
                # 빈 vector = 임베딩 실패 → 카운트
                self._breaker.record_failure()
                return None
            self._embed_cache.set(query, vector)
            self._breaker.record_success()
            return vector
        except asyncio.TimeoutError:
            log.warning("tool_rag_embed_timeout", timeout_s=self._timeout_s)
            self._breaker.record_failure()
            return None
        except Exception as exc:
            log.warning("tool_rag_embed_failed", error=str(exc))
            self._breaker.record_failure()
            return None

    # ----- public API -----

    async def upsert_tool(self, tool_meta: dict[str, Any]) -> bool:
        """도구 한 개 → BGE-M3 임베딩 → Qdrant upsert (idempotent).

        Args:
            tool_meta: dict with keys:
                - name: str (필수)
                - description: str
                - triggered_by_intents: list[str]
                - example_utterances: list[str]
                - category: str (옵션, payload 만)
                - is_implemented: bool (옵션, payload 만)
                - 기타 보안 메타 (requires_sender_tier, scope, requires_confirm)

        Returns:
            성공 시 True. 실패 시 False (best-effort — caller 는 raise 안 함 가정).
        """
        name = (tool_meta.get("name") or "").strip()
        if not name:
            log.warning("tool_rag_upsert_missing_name", meta=tool_meta)
            return False

        # circuit OPEN 시에도 upsert 는 시도 — register 는 cold path
        try:
            embed_text = _build_embed_text(tool_meta)
            embed_fn = await self._get_embed_fn()
            vector = await asyncio.wait_for(
                embed_fn(embed_text), timeout=max(self._timeout_s, 1.0)
            )
            if not vector:
                log.warning("tool_rag_upsert_empty_vector", name=name)
                return False

            from qdrant_client.models import PointStruct
            payload = {
                "name": name,
                "description": tool_meta.get("description", ""),
                "category": tool_meta.get("category", ""),
                "triggered_by_intents": list(tool_meta.get("triggered_by_intents") or []),
                "example_utterances": list(tool_meta.get("example_utterances") or []),
                "is_implemented": bool(tool_meta.get("is_implemented", True)),
            }
            # 보안 메타 (있으면 보존)
            for key in ("requires_sender_tier", "scope", "requires_confirm"):
                if key in tool_meta:
                    payload[key] = tool_meta[key]

            point = PointStruct(
                id=_stable_point_id(name),
                vector={"dense": vector},
                payload=payload,
            )
            qdrant = await self._get_qdrant()
            await qdrant.upsert(collection_name=self._collection, points=[point])

            # 캐시 무효화 — 새 도구가 결과에 들어오게
            self._retrieve_cache.clear()

            log.info("tool_rag_upsert_ok", name=name, dense_dim=len(vector))
            return True
        except Exception as exc:
            log.warning("tool_rag_upsert_failed", name=name, error=str(exc))
            return False

    async def delete_tool(self, name: str) -> bool:
        """tool name → Qdrant delete by stable id (idempotent)."""
        name = (name or "").strip()
        if not name:
            return False
        try:
            from qdrant_client.models import PointIdsList
            qdrant = await self._get_qdrant()
            await qdrant.delete(
                collection_name=self._collection,
                points_selector=PointIdsList(points=[_stable_point_id(name)]),
            )
            self._retrieve_cache.clear()
            log.info("tool_rag_delete_ok", name=name)
            return True
        except Exception as exc:
            log.warning("tool_rag_delete_failed", name=name, error=str(exc))
            return False

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        allowed_tools: Optional[Iterable[str]] = None,
        tenant_id: Optional[str] = None,
    ) -> list[ToolCandidate]:
        """query → top_k tool candidates.

        흐름:
          1. (query, tenant_id) 캐시 hit 시 즉시 반환
          2. circuit OPEN 시 빈 리스트 (caller fallback)
          3. query → BGE-M3 dense vector (200ms timeout)
          4. Qdrant search top_k (200ms timeout)
          5. allowed_tools 가 set 이면 교집합 (Phase 1.5A 권한 보존)
          6. 결과 캐시 + 반환

        Args:
            query: 사용자 발화 (e.g. "메일 보내줘")
            top_k: 검색 후보 수 (default 8 — spec §2.4)
            allowed_tools: agent.allowed_tools (None 이면 필터 없음)
            tenant_id: 캐시 키 분리용 (None 이면 글로벌 캐시)

        Returns:
            ToolCandidate 리스트. 실패 / fallback 필요 시 빈 리스트.
            *empty list 는 caller 의 CATEGORY_TOOLS fallback 신호*.
        """
        if not query:
            return []

        allowed_set: Optional[frozenset[str]] = None
        if allowed_tools is not None:
            allowed_set = frozenset(str(x) for x in allowed_tools if x)

        # 캐시 — query+tenant+top_k+allowed 조합으로 키 생성
        cache_key = (
            query,
            tenant_id or "",
            int(top_k),
            allowed_set,
        )
        cached = self._retrieve_cache.get(cache_key)
        if cached is not None:
            return list(cached)  # 방어적 복사

        # circuit OPEN — 즉시 빈 리스트 (caller fallback)
        if self._breaker.is_open():
            log.debug(
                "tool_rag_circuit_open_skip_retrieve",
                opened_at=self._breaker.opened_at,
            )
            return []

        vector = await self._embed_query(query)
        if vector is None:
            return []

        # Qdrant search
        try:
            qdrant = await self._get_qdrant()
            response = await asyncio.wait_for(
                qdrant.query_points(
                    collection_name=self._collection,
                    query=vector,
                    using="dense",
                    limit=top_k,
                    with_payload=True,
                ),
                timeout=self._timeout_s,
            )
            points = (
                response.points if hasattr(response, "points")
                else (response or [])
            )
        except asyncio.TimeoutError:
            log.warning("tool_rag_search_timeout", timeout_s=self._timeout_s)
            self._breaker.record_failure()
            return []
        except Exception as exc:
            log.warning("tool_rag_search_failed", error=str(exc))
            self._breaker.record_failure()
            return []

        self._breaker.record_success()

        # 결과 → ToolCandidate 변환
        candidates: list[ToolCandidate] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            name = payload.get("name") or ""
            if not name:
                continue
            if allowed_set is not None and name not in allowed_set:
                continue
            candidates.append(ToolCandidate(
                name=name,
                score=float(getattr(point, "score", 0.0) or 0.0),
                description=payload.get("description", "") or "",
                triggered_by_intents=list(
                    payload.get("triggered_by_intents") or []
                ),
            ))

        self._retrieve_cache.set(cache_key, candidates)
        return list(candidates)

    async def reconcile(
        self,
        tools: Iterable[dict[str, Any]],
    ) -> dict[str, int]:
        """registry vs Qdrant drift 자동 정합 (부팅 hook).

        Args:
            tools: 현재 registry 의 모든 도구 메타. (name 필수)

        Returns:
            {"upserted": N, "deleted": M, "skipped": K} — best-effort 통계.

        실패한 항목은 log warning 만 — 부팅 차단 X (운영 안정성).
        """
        tool_list = [t for t in tools if (t.get("name") or "").strip()]
        registry_names = {t["name"].strip() for t in tool_list}

        upserted = 0
        skipped = 0
        deleted = 0

        # 1) registry 의 모든 도구 upsert
        for meta in tool_list:
            ok = await self.upsert_tool(meta)
            if ok:
                upserted += 1
            else:
                skipped += 1

        # 2) Qdrant 에 있는데 registry 에 없는 항목 삭제
        try:
            qdrant = await self._get_qdrant()
            existing_names = await self._list_existing_names(qdrant)
            for name in existing_names:
                if name not in registry_names:
                    if await self.delete_tool(name):
                        deleted += 1
        except Exception as exc:
            log.warning("tool_rag_reconcile_drift_check_failed", error=str(exc))

        log.info(
            "tool_rag_reconciled",
            upserted=upserted,
            deleted=deleted,
            skipped=skipped,
            registry_size=len(tool_list),
        )
        return {"upserted": upserted, "deleted": deleted, "skipped": skipped}

    async def _list_existing_names(self, qdrant: QdrantBackend) -> set[str]:
        """Qdrant 의 모든 point payload.name → set.

        scroll 로 전체 payload 수집. 도구 수는 ~수백개라 1 batch 면 충분.
        실패 시 빈 set (drift 삭제 skip).
        """
        try:
            scroll_result = await qdrant.scroll(
                collection_name=self._collection,
                limit=500,
                with_payload=True,
                with_vectors=False,
            )
            # qdrant_client.scroll → (points, next_offset)
            if isinstance(scroll_result, tuple):
                points = scroll_result[0]
            else:
                points = getattr(scroll_result, "points", []) or []
            names: set[str] = set()
            for p in points:
                payload = getattr(p, "payload", None) or {}
                name = payload.get("name") or ""
                if name:
                    names.add(name)
            return names
        except Exception as exc:
            log.warning("tool_rag_scroll_failed", error=str(exc))
            return set()

    async def ensure_collection(self) -> bool:
        """Qdrant collection 존재 보장 (idempotent).

        부팅 시 reconcile 전에 호출. 이미 있으면 no-op.
        """
        try:
            from qdrant_client.models import (
                Distance,
                VectorParams,
            )
            qdrant = await self._get_qdrant()
            existing = await qdrant.get_collections()
            existing_names = {c.name for c in (existing.collections or [])}
            if self._collection in existing_names:
                return True
            await qdrant.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "dense": VectorParams(size=DENSE_DIM, distance=Distance.COSINE),
                },
            )
            log.info("tool_rag_collection_created", name=self._collection)
            return True
        except Exception as exc:
            log.warning(
                "tool_rag_ensure_collection_failed",
                name=self._collection,
                error=str(exc),
            )
            return False

    # ----- introspection (테스트 / 운영 점검용) -----

    @property
    def circuit_breaker(self) -> _CircuitBreaker:
        return self._breaker

    @property
    def collection(self) -> str:
        return self._collection

    def clear_caches(self) -> None:
        """수동 캐시 비우기 — 운영 점검용."""
        self._embed_cache.clear()
        self._retrieve_cache.clear()
