"""D56 §E PR-E — Enricher LLM 결과 Redis cache layer.

설계 (GPT-5 사전 verdict 권고 모두 반영):
- 키: aicm:enricher:{name}:{schema_v}:{prompt_v}:{block_hash}:{cfg_hash}
- cfg_hash = sha256(model_id + inference_params + prompt_text + schema_json) 16자
  → prompt/schema/모델/파라미터 변경 시 자동 cache invalidation (버전 증분 누락 방지)
- 값: JSON envelope (str | dict), 4 KB+ gzip 압축, b"J1"/"G1" 헤더 3바이트
- TTL: env override (ENRICHER_CACHE_TTL_DAYS, enricher 별 override 가능)
- fallback: Redis 실패 시 in-memory LRU (현재 동작과 호환)
- 회귀 0%: cache miss path = 기존 동일. cache hit path = byte-identical (cfg_hash 가 출력 영향
  요인 모두 포함).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from collections import OrderedDict
from typing import Any, Optional

import redis.asyncio as aioredis

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
_KEY_PREFIX = "aicm:enricher"
_DEFAULT_TTL_DAYS = 30
_DEFAULT_COMPRESS_THRESHOLD = 4096  # 4 KB 이상 시 gzip
_DEFAULT_GZIP_LEVEL = 4
_DEFAULT_REDIS_TIMEOUT_OP_MS = 100
_DEFAULT_REDIS_TIMEOUT_CONNECT_MS = 100
_DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5  # 연속 실패 5건 → 회로 열림
_DEFAULT_CIRCUIT_BREAKER_RESET_S = 30
# GPT-5 post WARN: 워커당 메모리 폭증 방지 — 보수적 기본값
_DEFAULT_INMEM_LRU_SIZE = 5000
_DEFAULT_INMEM_TTL_S = 1800  # 30분

_ENV_PREFIX = "ENRICHER_CACHE"


# ---------------------------------------------------------------------------
# 환경변수 헬퍼
# ---------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")


# ---------------------------------------------------------------------------
# 캐시 클라이언트
# ---------------------------------------------------------------------------
class _InMemoryLRU:
    """간단 LRU + TTL — Redis fallback 용. 메모리 상한 보호."""

    def __init__(self, max_size: int = _DEFAULT_INMEM_LRU_SIZE,
                 ttl_s: int = _DEFAULT_INMEM_TTL_S) -> None:
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._max = max_size
        self._ttl = ttl_s

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            self._store.pop(key, None)
            return None
        # touch
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.time(), value)
        while len(self._store) > self._max:
            self._store.popitem(last=False)


class EnricherRedisCache:
    """Redis 기반 enricher 결과 캐시.

    GPT-5 권고:
    - cfg_hash 자동 부착 (prompt/schema/model/params sha 결합 → 회귀 0% 보장)
    - JSON envelope + gzip 압축
    - Redis 실패 시 LRU+TTL fallback (silent)
    - 짧은 timeout + circuit breaker (연속 실패 시 일정 시간 fallback)

    Args:
        name: enricher 이름 (예: "search_summary", "metadata_extractor", "self_verifier")
        schema_version: 출력 스키마 버전 태그 (예: "v1")
        prompt_version: 프롬프트 버전 태그 (예: "v1")
        prompt_text: 실제 프롬프트 텍스트 (cfg_hash 의 일부)
        model_id: LLM 모델 식별자 (예: "gemma-4-31b")
        inference_params: temperature / max_tokens 등 (cfg_hash 의 일부)
        ttl_days: TTL (env override 우선)
        redis_url: 미지정 시 settings.REDIS_URL
    """

    def __init__(
        self,
        name: str,
        schema_version: str = "v1",
        prompt_version: str = "v1",
        prompt_text: str = "",
        model_id: str = "",
        inference_params: dict | None = None,
        ttl_days: int | None = None,
        redis_url: str | None = None,
    ) -> None:
        self._name = name
        self._schema_v = schema_version
        self._prompt_v = prompt_version
        self._model_id = model_id
        self._inf_params = inference_params or {}
        # cfg_hash = prompt + schema + model + params sha (자동 키 분기)
        self._cfg_hash = self._compute_cfg_hash(
            prompt_text=prompt_text,
            schema_version=schema_version,
            prompt_version=prompt_version,
            model_id=model_id,
            inference_params=self._inf_params,
        )
        # TTL: 전역 → enricher 별 override
        global_ttl = _env_int(f"{_ENV_PREFIX}_TTL_DAYS", _DEFAULT_TTL_DAYS)
        per_name = _env_int(
            f"{_ENV_PREFIX}_TTL_DAYS_{name.upper()}", global_ttl
        )
        self._ttl_s = (ttl_days if ttl_days is not None else per_name) * 24 * 3600
        # toggle
        self._enabled = _env_bool(f"{_ENV_PREFIX}_ENABLED", True)
        # Redis
        self._redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[aioredis.Redis] = None
        # LRU fallback (env override 가능)
        inmem_max = _env_int(f"{_ENV_PREFIX}_INMEM_MAX", _DEFAULT_INMEM_LRU_SIZE)
        inmem_ttl = _env_int(f"{_ENV_PREFIX}_INMEM_TTL_S", _DEFAULT_INMEM_TTL_S)
        self._inmem = _InMemoryLRU(max_size=inmem_max, ttl_s=inmem_ttl)
        # Redis 타임아웃 env override (GPT-5 post WARN)
        self._redis_connect_timeout_s = _env_int(
            f"{_ENV_PREFIX}_REDIS_CONNECT_TIMEOUT_MS",
            _DEFAULT_REDIS_TIMEOUT_CONNECT_MS,
        ) / 1000
        self._redis_op_timeout_s = _env_int(
            f"{_ENV_PREFIX}_REDIS_OP_TIMEOUT_MS",
            _DEFAULT_REDIS_TIMEOUT_OP_MS,
        ) / 1000
        # circuit breaker
        self._cb_threshold = _env_int(
            f"{_ENV_PREFIX}_CB_THRESHOLD", _DEFAULT_CIRCUIT_BREAKER_THRESHOLD
        )
        self._cb_reset_s = _env_int(
            f"{_ENV_PREFIX}_CB_RESET_S", _DEFAULT_CIRCUIT_BREAKER_RESET_S
        )
        self._cb_fail_count = 0
        self._cb_open_until: float = 0.0
        # 압축
        self._compress_threshold = _env_int(
            f"{_ENV_PREFIX}_COMPRESS_THRESHOLD", _DEFAULT_COMPRESS_THRESHOLD
        )
        # 메트릭
        self.hit_count = 0
        self.miss_count = 0
        self.error_count = 0
        self.fallback_count = 0

    # ------------------------------------------------------------------
    # cfg_hash + key 빌더
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_cfg_hash(
        prompt_text: str,
        schema_version: str,
        prompt_version: str,
        model_id: str,
        inference_params: dict,
    ) -> str:
        """prompt + schema + model + params sha → 16자 prefix.

        prompt/schema 텍스트 변경 시 자동으로 키 분기 (버전 bump 누락 방지).
        """
        payload = json.dumps(
            {
                "p": prompt_text,
                "sv": schema_version,
                "pv": prompt_version,
                "m": model_id,
                "ip": inference_params,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def build_key(self, block_hash: str) -> str:
        """캐시 키 생성."""
        return (
            f"{_KEY_PREFIX}:{self._name}:{self._schema_v}:{self._prompt_v}:"
            f"{block_hash}:{self._cfg_hash}"
        )

    # ------------------------------------------------------------------
    # Redis 클라이언트 + circuit breaker
    # ------------------------------------------------------------------
    async def _get_redis(self) -> aioredis.Redis | None:
        """Redis 클라이언트 지연 생성 — 회로 열림 시 None."""
        now = time.time()
        if now < self._cb_open_until:
            return None
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(
                    self._redis_url,
                    decode_responses=False,
                    socket_connect_timeout=self._redis_connect_timeout_s,
                    socket_timeout=self._redis_op_timeout_s,
                )
            except Exception:
                self._mark_failure()
                return None
        return self._redis

    def _mark_failure(self) -> None:
        """회로 차단기: 연속 실패 누적 → 일정 시간 fallback only."""
        self._cb_fail_count += 1
        self.error_count += 1
        if self._cb_fail_count >= self._cb_threshold:
            self._cb_open_until = time.time() + self._cb_reset_s
            self._cb_fail_count = 0
            log.warning(
                "enricher_cache_circuit_open",
                name=self._name,
                reset_in_s=self._cb_reset_s,
            )

    def _mark_success(self) -> None:
        self._cb_fail_count = 0

    # ------------------------------------------------------------------
    # 직렬화 (envelope + 압축)
    # ------------------------------------------------------------------
    def _serialize(self, value: Any) -> bytes:
        """JSON envelope + 4KB+ gzip 압축. 헤더 2바이트 (b\"J1\"/b\"G1\")."""
        envelope = {
            "v": 1,
            "t": self._name,
            "sv": self._schema_v,
            "pv": self._prompt_v,
            "cfg": self._cfg_hash,
            "data": value,
        }
        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        if len(body) >= self._compress_threshold:
            return b"G1" + gzip.compress(body, compresslevel=_DEFAULT_GZIP_LEVEL)
        return b"J1" + body

    def _deserialize(self, raw: bytes) -> Any | None:
        """envelope 역직렬화. 실패 시 None (caller 가 miss 처리)."""
        try:
            if raw.startswith(b"G1"):
                body = gzip.decompress(raw[2:])
            elif raw.startswith(b"J1"):
                body = raw[2:]
            else:
                # 옛 포맷 (호환): 직접 JSON 시도
                body = raw
            envelope = json.loads(body)
            # cfg 비교 — 키에 이미 포함되어 있지만 envelope 도 검증
            if envelope.get("cfg") != self._cfg_hash:
                return None
            return envelope.get("data")
        except Exception:
            return None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    async def get(self, block_hash: str) -> Any | None:
        """캐시 조회. miss / 실패 → None.

        병렬 우선순위:
        1. Redis (회로 닫힘 시)
        2. in-memory LRU (Redis 실패 fallback)
        """
        if not self._enabled or not block_hash:
            self.miss_count += 1
            return None
        key = self.build_key(block_hash)

        # 1. Redis 시도
        redis = await self._get_redis()
        if redis is not None:
            try:
                raw = await redis.get(key)
                if raw is not None:
                    val = self._deserialize(raw)
                    if val is not None:
                        self.hit_count += 1
                        self._mark_success()
                        return val
                self._mark_success()
            except Exception as exc:
                log.debug(
                    "enricher_cache_redis_get_failed",
                    name=self._name,
                    error=str(exc)[:120],
                )
                self._mark_failure()

        # 2. in-memory fallback
        val = self._inmem.get(key)
        if val is not None:
            self.fallback_count += 1
            return val
        self.miss_count += 1
        return None

    async def set(self, block_hash: str, value: Any) -> None:
        """캐시 저장. Redis 성공 시 in-mem 저장 생략 (메모리 절약).

        GPT-5 post WARN 반영: Redis 가 정상 동작 중이면 in-mem 은 불필요.
        Redis 실패/회로 차단 시에만 in-mem 으로 보존.
        """
        if not self._enabled or not block_hash:
            return
        key = self.build_key(block_hash)

        redis = await self._get_redis()
        if redis is None:
            # Redis 사용 불가 → in-mem 만 저장
            self._inmem.set(key, value)
            return
        try:
            data = self._serialize(value)
            await redis.set(key, data, ex=self._ttl_s)
            self._mark_success()
        except Exception as exc:
            log.debug(
                "enricher_cache_redis_set_failed",
                name=self._name,
                error=str(exc)[:120],
            )
            self._mark_failure()
            # Redis 실패 시 in-mem fallback 저장
            self._inmem.set(key, value)

    async def aclose(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    # ------------------------------------------------------------------
    # 메트릭
    # ------------------------------------------------------------------
    @property
    def hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0

    def stats(self) -> dict:
        return {
            "name": self._name,
            "hit": self.hit_count,
            "miss": self.miss_count,
            "error": self.error_count,
            "fallback": self.fallback_count,
            "hit_rate": round(self.hit_rate, 4),
            "cfg_hash": self._cfg_hash,
        }
