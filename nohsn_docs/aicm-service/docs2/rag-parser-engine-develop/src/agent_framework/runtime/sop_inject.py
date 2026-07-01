"""SopInjectLayer — Phase 1.5B-β SOP RAG injection layer.

plan_orchestrator 가 매 turn 의 prompt 빌드 직전 호출하는 *얇은 모듈*.

원칙:
- evidence (kms_rag) 와 분리: SOP 는 instruction (정책/절차).
- failure_response_patterns 는 *deterministic include* — RAG 결과와 별개로 항상.
- destructive intent 시 force top_k=20 — *모든* SOP chunks 강제 retrieve.
- per (agent_id, query_hash) 30s cache (in-memory + best-effort Redis).
- prefetch — 첫 turn 시 SOP 전체 metadata 로드 (lightweight chunks_count 등).

Round 1 (이번 PR): 코드만 존재. plan_orchestrator 통합은 Round 2 (FEATURE_SOP_RAG).

설계 참조:
- ``docs/superpowers/specs/2026-05-06-agent-guardrails-and-dynamic-sop-design.md`` §9.3
- ``docs/superpowers/plans/2026-05-07-master-plan-phase-1.5.md`` §B-2 β
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import UUID

from src.common.logging import get_logger

log = get_logger(__name__)


# 30s — query 결과 cache. 짧게 잡아 SOP 변경이 다음 turn 에 반영.
_DEFAULT_CACHE_TTL_S = 30.0
# prefetch metadata 캐시 TTL — 5 분 (agent 변경은 admin 액션이라 빈도 낮음).
_PREFETCH_TTL_S = 300.0

# B1 (2026-05-07) — adaptive token budgeter.
# system 한도. 4500 = 31B inference 안전선 (전체 8192 ctx 의 ~55%).
DEFAULT_SYSTEM_BUDGET_TOKENS = 4500
# 엔진 고정 overhead — system 헤더 / 접두 문구 / 경고 등. GPT-5 P1.
ENGINE_SYSTEM_OVERHEAD_TOKENS = 150
# chunk 한 개당 헤더 (## heading + tag) 추가 overhead 추정.
PER_CHUNK_OVERHEAD_TOKENS = 20

# #76 (2026-05-19) — SOP inject 기본값. env override 로 운영 튜닝 가능.
# [feedback_no_hardcoding_first_principle] — magic number 제거, 상수화.
DEFAULT_SOP_INJECT_TOP_K = 5
# SOP search per-turn 한계 시간 (fail-open). KMS 장애가 답변 장애로 전파되지 않게.
DEFAULT_SOP_INJECT_TIMEOUT_MS = 1500


def get_sop_inject_top_k() -> int:
    """env `SOP_INJECT_TOP_K` override (default 5, clamp 1..20)."""
    try:
        v = int(os.environ.get("SOP_INJECT_TOP_K", DEFAULT_SOP_INJECT_TOP_K))
    except (ValueError, TypeError):
        return DEFAULT_SOP_INJECT_TOP_K
    return max(1, min(v, 20))


def get_sop_inject_timeout_ms() -> int:
    """env `SOP_INJECT_TIMEOUT_MS` override (default 1500, clamp 100..10000)."""
    try:
        v = int(os.environ.get("SOP_INJECT_TIMEOUT_MS", DEFAULT_SOP_INJECT_TIMEOUT_MS))
    except (ValueError, TypeError):
        return DEFAULT_SOP_INJECT_TIMEOUT_MS
    return max(100, min(v, 10000))


def is_sop_rag_enabled_default_on() -> bool:
    """#76 (2026-05-19) — SOP RAG inject 활성 여부 (default on).

    env ``FEATURE_SOP_RAG=false`` 만 강제 off (운영 kill-switch). default True.
    engine.AgentEngine._is_sop_rag_enabled 와 동일 로직 — engine /
    tool_calling_loop / sop_inject_builder 가 모두 동일 진실원을 본다.

    GPT-5.5 post-commit verdict (2026-05-19) 권고 1 반영: kill-switch 가
    *path 독립* 으로 작동하도록 helper 화. tool_calling_loop path 가
    engine 의 method 를 호출 안 해 발생한 silent bypass 차단.
    """
    try:
        from src.common.feature_flags import FeatureFlag, _env_explicit
        env_val = _env_explicit(FeatureFlag.SOP_RAG)
        if env_val is not None:
            return env_val
        return True
    except Exception:  # noqa: BLE001
        return True


def _is_cjk_or_hangul(ch: str) -> bool:
    """CJK / 한글 / 가나 / 히라가나 / 한자 — token 비율 ~1.0~1.2 char/tok."""
    cp = ord(ch)
    return (
        0xAC00 <= cp <= 0xD7A3  # 한글 음절
        or 0x1100 <= cp <= 0x11FF  # 한글 자모
        or 0x3040 <= cp <= 0x309F  # 히라가나
        or 0x30A0 <= cp <= 0x30FF  # 가타카나
        or 0x4E00 <= cp <= 0x9FFF  # CJK Unified
        or 0x3400 <= cp <= 0x4DBF  # CJK Ext A
        or 0xF900 <= cp <= 0xFAFF  # CJK 호환
    )


def estimate_tokens(text: str) -> int:
    """CJK-aware token 추정 (GPT-5 P0 fix).

    BPE 기준 한국어/한자 = ~1.0-1.2 char/tok. 영어 ~ 4 char/tok. 기호 ~ 2.5 char/tok.
    최종: ``max(weighted_est, ceil(len/3))`` — 보수 상한 (영어 과대추정 완화 —
    GPT-5 P1, 2026-05-07).

    tiktoken dependency 회피. 회귀 0 (기존 호출은 모두 default 경로).
    """
    if not text:
        return 0
    cjk = 0
    ascii_ = 0
    for ch in text:
        if ord(ch) < 128:
            ascii_ += 1
        elif _is_cjk_or_hangul(ch):
            cjk += 1
    other = len(text) - ascii_ - cjk
    weighted = (
        math.ceil(ascii_ / 4)
        + math.ceil(cjk / 1.1)
        + math.ceil(other / 2.5)
    )
    # 보수 상한 — len/3 (영어 4 char/tok 대비 ~33% 마진).
    # GPT-5 P1: len/2 는 영어 ASCII 위주에서 2x 과대추정 → greedy 조기 stop.
    safe_floor = math.ceil(len(text) / 3)
    return max(weighted, safe_floor)


@dataclass(frozen=True)
class SopChunk:
    """SopInjectLayer 가 반환하는 chunk 형식.

    is_failure_pattern 은 deterministic include (failure_response_patterns
    섹션에서 직접 추출된 chunk) 인지 표시. RAG 검색 결과와 구분.
    """

    text: str
    score: float
    repo_id: UUID
    document_id: UUID
    is_failure_pattern: bool = False
    heading: str = ""
    chunk_index: int = 0


@dataclass
class _CacheEntry:
    chunks: list[SopChunk]
    expires_at: float


@dataclass
class _PrefetchEntry:
    """Lightweight metadata — 첫 turn 시 로드.

    Round 1 에선 sop_repo_ids 와 ``failure_response_patterns`` 섹션 텍스트 정도만
    캐싱. 실 chunk metadata (count 등) 는 Qdrant scroll 추가시 확장.
    """

    sop_repo_ids: list[UUID]
    failure_response_patterns: str
    expires_at: float


def _query_hash(query: str) -> str:
    """short stable hash — cache key 의 일부."""
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]


def extract_failure_response_patterns(guidelines_md: str) -> str:
    """guidelines_md 에서 ``## 실패 응답 패턴`` (또는 영문 ``## failure_response_patterns``)
    섹션의 본문을 추출.

    스펙: 다음 ``## ...`` (level-2) 헤딩 직전까지.

    탐색 대상 헤딩 (case-insensitive, 공백 normalize):
    - ``## 실패 응답 패턴``
    - ``## failure_response_patterns``
    - ``## failure response patterns``

    누락 시 빈 문자열.
    """
    if not guidelines_md:
        return ""

    # 라인 단위로 처리하여 다음 H2 까지 추출.
    lines = guidelines_md.splitlines()
    n = len(lines)

    target_re = re.compile(
        r"^\s*##\s+(?:실패\s*응답\s*패턴|failure[_\s]response[_\s]patterns)\s*$",
        re.IGNORECASE,
    )
    h2_re = re.compile(r"^\s*##\s+\S")

    start = -1
    for i, line in enumerate(lines):
        if target_re.match(line):
            start = i + 1
            break
    if start < 0:
        return ""

    # 다음 H2 까지.
    end = n
    for j in range(start, n):
        if h2_re.match(lines[j]):
            end = j
            break
    body = "\n".join(lines[start:end]).strip()
    return body


class SopInjectLayer:
    """plan_orchestrator 가 호출하는 SOP injection 어댑터.

    Args:
        tool_call: ``async (tool_name: str, args: dict) -> dict`` — 보통
            ``ToolRegistry.call`` 를 wrap.
        cache_ttl_s: query 캐시 TTL (default 30s).
        redis: optional ``redis.asyncio.Redis`` — 분산 cache. None 이면 in-memory only.
        clock: ``Callable[[], float]`` — 테스트 시간 주입용.
    """

    def __init__(
        self,
        tool_call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        *,
        cache_ttl_s: float = _DEFAULT_CACHE_TTL_S,
        redis: Any = None,
        clock: Callable[[], float] | None = None,
    ):
        self._tool_call = tool_call
        self._cache_ttl_s = cache_ttl_s
        self._redis = redis
        self._clock = clock or time.monotonic
        # in-memory query cache
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = asyncio.Lock()
        # prefetch metadata cache
        self._prefetch: dict[UUID, _PrefetchEntry] = {}
        self._prefetch_lock = asyncio.Lock()

    # --- prefetch ---------------------------------------------------------

    async def prefetch(
        self,
        agent_id: UUID,
        guidelines_md: str,
        sop_repo_ids: list[UUID],
    ) -> None:
        """첫 turn 시 lightweight metadata 로드.

        - failure_response_patterns 섹션 추출 → in-memory.
        - sop_repo_ids 캐싱.

        실패해도 raise 안 함. 단순 캐시 ahead.
        """
        try:
            failure_patterns = extract_failure_response_patterns(guidelines_md or "")
            entry = _PrefetchEntry(
                sop_repo_ids=list(sop_repo_ids or []),
                failure_response_patterns=failure_patterns,
                expires_at=self._clock() + _PREFETCH_TTL_S,
            )
            async with self._prefetch_lock:
                self._prefetch[agent_id] = entry
            log.debug(
                "sop_inject_prefetch_loaded",
                agent_id=str(agent_id),
                has_failure_patterns=bool(failure_patterns),
                sop_repo_count=len(entry.sop_repo_ids),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("sop_inject_prefetch_failed", error=str(exc))

    def get_prefetched(self, agent_id: UUID) -> _PrefetchEntry | None:
        """test/debug — 현재 prefetch 상태 조회."""
        entry = self._prefetch.get(agent_id)
        if entry is None or entry.expires_at < self._clock():
            return None
        return entry

    # --- main entry -------------------------------------------------------

    async def fetch_chunks(
        self,
        agent_id: UUID,
        query: str,
        *,
        top_k: int = 5,
        destructive: bool = False,
        guidelines_md: str | None = None,
        system_budget_tokens: int | None = None,
        pre_used_tokens: int = 0,
    ) -> list[SopChunk]:
        """매 turn 호출. SOP chunks 반환 — B1 adaptive token budgeter (2026-05-07).

        Args:
            agent_id: SOP repo lookup 대상.
            query: 사용자 발화 + agent goal 결합 query (caller 가 결정).
            top_k: 기본 검색 chunk 수 (default 5).
            destructive: True 면 force top_k=20 — 후보 폭만 늘림 (실제 inject 는
                여전히 budget 안 cap 적용 — GPT-5 P0).
            guidelines_md: prefetch 우선, 없으면 즉시 failure_response_patterns
                추출용으로 사용. None 이면 prefetch 캐시만 사용.
            system_budget_tokens: caller (engine) 가 전달한 system 한도. None
                이면 budget 적용 안 함 — 기존 동작 (회귀 0).
            pre_used_tokens: 이미 binding_policy + guidelines_md + engine
                overhead 로 사용된 token. greedy packing 의 budget 계산에 사용.

        Returns:
            ``list[SopChunk]`` — failure_response_patterns chunk(s) 가 *항상* 앞.

        Notes:
            - failure_response_patterns 는 RAG 결과 *후에 dedupe 없이 추가*.
              chunk.is_failure_pattern=True 로 표시.
            - cache hit 도 destructive force 시 *우회* (retrieve 강제).
              destructive=False 호출만 cache.
            - system_budget_tokens 가 주어지면 greedy packing — chunk 한 개씩
              추가하며 ``estimate_tokens(text) + PER_CHUNK_OVERHEAD`` 가 남은
              budget 안일 때만 포함. 초과 직전 stop.
            - failure_response_patterns 는 budget 무관 *항상 포함* (deterministic
              안전 신호). budget 이 너무 작으면 caller 가 처리.
        """
        # destructive 시 후보 폭 상향 (실제 cap 은 budget 에서 결정).
        effective_top_k = 20 if destructive else max(1, min(int(top_k or 5), 20))

        rag_chunks: list[SopChunk] = []

        # cache lookup — destructive 시 skip (force retrieve).
        cache_key = f"{agent_id}:{_query_hash(query)}:{effective_top_k}"
        cache_hit = False
        if not destructive:
            entry = await self._cache_get(cache_key)
            if entry is not None:
                rag_chunks = list(entry.chunks)
                cache_hit = True
                log.debug(
                    "sop_inject_cache_hit",
                    agent_id=str(agent_id),
                    chunks=len(rag_chunks),
                )

        # cache miss → kms_sop.search 호출.
        if not cache_hit:
            try:
                result = await self._tool_call(
                    "kms_sop.search",
                    {
                        "query": query,
                        "agent_id": str(agent_id),
                        "top_k": effective_top_k,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("sop_inject_search_call_failed", error=str(exc))
                result = {"success": False, "chunks": []}

            for c in result.get("chunks", []) or []:
                try:
                    rag_chunks.append(
                        SopChunk(
                            text=str(c.get("text") or ""),
                            score=float(c.get("score") or 0.0),
                            repo_id=UUID(str(c.get("repo_id"))),
                            document_id=UUID(str(c.get("document_id"))),
                            is_failure_pattern=False,
                            heading=str(c.get("heading") or ""),
                            chunk_index=int(c.get("chunk_index") or 0),
                        )
                    )
                except (ValueError, TypeError):
                    # malformed chunk — drop.
                    continue

            # non-destructive 결과만 캐시.
            if not destructive:
                await self._cache_put(cache_key, rag_chunks)

        # failure_response_patterns deterministic include.
        # prefetch 우선, 없으면 caller 가 넘긴 guidelines_md 에서 즉시 추출.
        failure_text = ""
        prefetched = self.get_prefetched(agent_id)
        if prefetched is not None and prefetched.failure_response_patterns:
            failure_text = prefetched.failure_response_patterns
        elif guidelines_md:
            failure_text = extract_failure_response_patterns(guidelines_md)

        out: list[SopChunk] = []
        budget_used = 0
        budget_remaining = -1  # -1 = unbounded (budget 미적용)
        packed_count = 0

        if failure_text.strip():
            out.append(
                SopChunk(
                    text=failure_text,
                    score=1.0,  # deterministic — 최상위 priority signal
                    repo_id=UUID(int=0),
                    document_id=UUID(int=0),
                    is_failure_pattern=True,
                    heading="failure_response_patterns",
                    chunk_index=-1,
                )
            )

        # B1 (2026-05-07) — adaptive token budgeter.
        # system_budget_tokens 가 주어지면 greedy pack. 미주어지면 옛 동작 (회귀 0).
        if system_budget_tokens is not None:
            budget = max(0, int(system_budget_tokens) - int(pre_used_tokens or 0))
            # failure_text 토큰도 budget 에서 차감 (deterministic include 후).
            if failure_text.strip():
                budget -= estimate_tokens(failure_text) + PER_CHUNK_OVERHEAD_TOKENS
            budget_remaining = budget
            for c in rag_chunks:
                need = (
                    estimate_tokens(c.text or "")
                    + estimate_tokens(c.heading or "")
                    + PER_CHUNK_OVERHEAD_TOKENS
                )
                if need <= budget_remaining:
                    out.append(c)
                    budget_remaining -= need
                    budget_used += need
                    packed_count += 1
                else:
                    # budget 초과 직전 stop (greedy).
                    break
        else:
            # legacy path (회귀 0) — 모두 추가.
            out.extend(rag_chunks)
            packed_count = len(rag_chunks)

        log.info(
            "sop_inject_fetch_chunks_done",
            agent_id=str(agent_id),
            destructive=destructive,
            destructive_capped=bool(
                destructive and system_budget_tokens is not None
            ),
            top_k=effective_top_k,
            cache_hit=cache_hit,
            rag_count=len(rag_chunks),
            packed_count=packed_count,
            includes_failure_pattern=bool(failure_text),
            budget_total=system_budget_tokens,
            pre_used=pre_used_tokens,
            budget_used=budget_used,
            budget_remaining=budget_remaining,
        )
        return out

    # --- cache helpers ----------------------------------------------------

    async def _cache_get(self, key: str) -> _CacheEntry | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at < self._clock():
                self._cache.pop(key, None)
                return None
            return entry

    async def _cache_put(self, key: str, chunks: list[SopChunk]) -> None:
        entry = _CacheEntry(
            chunks=list(chunks),
            expires_at=self._clock() + self._cache_ttl_s,
        )
        async with self._cache_lock:
            # 단순 LRU 미구현 — 갯수 폭주 방지로 200 cap.
            if len(self._cache) >= 200:
                # 만료 항목 우선 정리.
                now = self._clock()
                stale = [k for k, v in self._cache.items() if v.expires_at < now]
                for k in stale:
                    self._cache.pop(k, None)
                # 그래도 200 넘으면 가장 오래된 entry drop.
                if len(self._cache) >= 200:
                    oldest_k = min(
                        self._cache.keys(),
                        key=lambda k: self._cache[k].expires_at,
                    )
                    self._cache.pop(oldest_k, None)
            self._cache[key] = entry

    async def clear_cache(self) -> None:
        """test 도우미 — 모든 cache flush."""
        async with self._cache_lock:
            self._cache.clear()
        async with self._prefetch_lock:
            self._prefetch.clear()
