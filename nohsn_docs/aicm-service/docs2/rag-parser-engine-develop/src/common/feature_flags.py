"""Feature flag — runtime 토글 + env kill-switch + 60s cache (2026-05-07 spec).

Spec: docs/superpowers/specs/2026-05-07-feature-flags-runtime-toggle.md

우선순위 (GPT-5 phase 0 P0 반영):
1. **env override (kill-switch)** — `FEATURE_<NAME>=true|false` 명시 시 무조건 우선.
   운영 중 긴급 비활성을 위해 DB/Redis 보다 위.
2. **tenant DB** — `tenants.feature_flags` JSONB 키. admin UI 가 jsonb_set 으로 영속.
3. **Redis (legacy)** — DB 키 미설정 시만 fallback. 옛 사용처 유지.
4. **default false** — 기본 안전.

캐시:
- per-tenant in-memory dict, TTL 60s, LRU max 1024.
- PATCH 후 ``evict_tenant(tid)`` + Redis pub/sub publish (multi-replica) — 즉시 반영.
- DB 미연결 시 silent fallback (env-only 동작) — 회귀 0.

sync 호출자 호환:
- engine.py / runtime 코드는 sync ``is_enabled()`` 호출.
- 내부 DB lookup 은 sync sqlalchemy create_engine — async 핸들러는 cache hit 비율 높음.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from enum import Enum
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.common.logging import get_logger

log = get_logger(__name__)


class FeatureFlag(str, Enum):
    FAST_INFO_LOOKUP_PLAN = "fast_info_lookup_plan"
    KMS_FIRST_EARLY_RETURN = "kms_first_early_return"
    PLAN_MODEL_SMALL = "plan_model_small"
    PLAN_DEDUPE = "plan_dedupe"
    SKILL_INTENT_RECONCILE = "skill_intent_reconcile"
    LATENCY_PROBE_SSE = "latency_probe_sse"
    PLAN_PARALLEL_STEPS = "plan_parallel_steps"
    # Phase 1.5B-α — Tool RAG (CATEGORY_TOOLS narrowing 대체)
    TOOL_RAG = "tool_rag"
    # Phase 1.5B-β — SOP RAG (kms_sop.search + SopInjectLayer)
    SOP_RAG = "sop_rag"
    # L8 (2026-05-07) — Binding Gate (OOS fast-track).
    BINDING_GATE = "binding_gate"
    # 2026-05-07 — role agent 결정론 fast-track.
    ROLE_FAST_TRACK = "role_fast_track"


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

# ---------------------------------------------------------------------------
# Cache (per-tenant flags, TTL 60s, LRU max 1024)
# ---------------------------------------------------------------------------

_CACHE_TTL_SEC = 60
_CACHE_MAX_ENTRIES = 1024
_cache: "OrderedDict[str, tuple[dict[str, bool], float]]" = OrderedDict()
_cache_lock = threading.Lock()

_engine_singleton: Optional[Engine] = None
_engine_lock = threading.Lock()


def _sync_db_url() -> str:
    """async URL → sync URL (asyncpg → psycopg2)."""
    raw = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://kms:kms_dev_password@postgres:5432/kms_pipeline",
    )
    return raw.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")


def _get_engine() -> Optional[Engine]:
    global _engine_singleton
    if _engine_singleton is not None:
        return _engine_singleton
    with _engine_lock:
        if _engine_singleton is None:
            try:
                _engine_singleton = create_engine(
                    _sync_db_url(),
                    pool_size=2,
                    max_overflow=2,
                    pool_pre_ping=True,
                    pool_recycle=300,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("feature_flag_engine_init_failed", error=str(e))
                return None
    return _engine_singleton


def _fetch_tenant_flags(tenant_id: str) -> dict[str, bool]:
    """tenants.feature_flags 한 번 조회. 실패 시 빈 dict."""
    eng = _get_engine()
    if eng is None:
        return {}
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT feature_flags FROM tenants WHERE id = :tid"),
                {"tid": tenant_id},
            ).first()
        if row is None:
            return {}
        raw = row[0]
        if raw is None:
            return {}
        # asyncpg/psycopg2 호환 — JSONB 가 dict 또는 str 으로 올 수 있음.
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:  # noqa: BLE001
                return {}
        if not isinstance(raw, dict):
            return {}
        # bool 캐스팅 — 잘못된 타입은 false 로 (방어).
        out: dict[str, bool] = {}
        for k, v in raw.items():
            if isinstance(v, bool):
                out[str(k)] = v
            elif isinstance(v, (int, float)):
                out[str(k)] = bool(v)
            elif isinstance(v, str):
                out[str(k)] = v.strip().lower() in _TRUE_VALUES
        return out
    except Exception as e:  # noqa: BLE001
        log.warning(
            "feature_flag_db_lookup_failed", tenant_id=tenant_id, error=str(e)
        )
        return {}


def _cache_get(tenant_id: str) -> Optional[dict[str, bool]]:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(tenant_id)
        if entry is None:
            return None
        flags, expiry = entry
        if expiry < now:
            _cache.pop(tenant_id, None)
            return None
        # LRU bump
        _cache.move_to_end(tenant_id)
        return flags


def _cache_put(tenant_id: str, flags: dict[str, bool]) -> None:
    now = time.time()
    with _cache_lock:
        _cache[tenant_id] = (flags, now + _CACHE_TTL_SEC)
        _cache.move_to_end(tenant_id)
        # LRU eviction
        while len(_cache) > _CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)


def _get_tenant_flags_cached(tenant_id: str) -> dict[str, bool]:
    cached = _cache_get(tenant_id)
    if cached is not None:
        return cached
    flags = _fetch_tenant_flags(tenant_id)
    _cache_put(tenant_id, flags)
    return flags


def evict_tenant(tenant_id: str) -> None:
    """admin PATCH 직후 (commit 후) 호출 — 즉시 반영."""
    with _cache_lock:
        _cache.pop(tenant_id, None)
    # multi-replica: Redis pub/sub publish — 다른 replica 의 cache 도 evict.
    try:
        from src.common.redis import get_sync_redis  # type: ignore

        client = get_sync_redis()
        client.publish("feature_flag_evict", tenant_id)
    except Exception:  # noqa: BLE001
        pass  # silent — single-replica 또는 Redis 미가용 환경 호환.


def evict_all() -> None:
    """전체 cache flush — 디버그/테스트 용."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# env / Redis
# ---------------------------------------------------------------------------


def _env_explicit(flag: FeatureFlag) -> Optional[bool]:
    """env 가 명시적 true/false 값을 가지면 반환, unset 또는 unknown 이면 None.

    GPT-5 P0 — env 가 kill-switch 우선 (DB/Redis 보다 위). FEATURE_SOP_RAG=false
    는 모든 tenant DB 값을 압도해 즉시 강제 비활성.
    """
    raw = os.environ.get(f"FEATURE_{flag.value.upper()}")
    if raw is None:
        return None
    norm = raw.strip().lower()
    if norm in _TRUE_VALUES:
        return True
    if norm in _FALSE_VALUES:
        return False
    return None


def _env_enabled(flag: FeatureFlag) -> bool:
    """legacy alias — env true 만 검사. 기존 호출자 호환."""
    return _env_explicit(flag) is True


def _redis_enabled(flag: FeatureFlag, tenant_id: str) -> bool:
    """Redis 조회 — 미가용/오류 시 silent false. legacy fallback 전용."""
    try:
        from src.common.redis import get_sync_redis  # type: ignore

        client = get_sync_redis()
        key = f"feature_flag:{flag.value}:tenant:{tenant_id}"
        val = client.get(key)
        if val is None:
            return False
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        return str(val).strip().lower() in _TRUE_VALUES
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_enabled(flag: FeatureFlag, *, tenant_id: Optional[str] = None) -> bool:
    """flag 활성 여부.

    우선순위:
    1. env 변수 (FEATURE_<NAME>=true|false) — kill-switch.
    2. tenants.feature_flags[<flag>] — admin UI 토글.
    3. Redis legacy key — DB 미설정 시만.
    4. default false.
    """
    # 1. env override (kill-switch — DB 토글을 압도).
    env_val = _env_explicit(flag)
    if env_val is not None:
        return env_val

    # 2. tenant DB lookup (60s cache).
    if tenant_id:
        try:
            flags = _get_tenant_flags_cached(str(tenant_id))
            if flag.value in flags:
                return bool(flags[flag.value])
        except Exception as e:  # noqa: BLE001
            log.warning(
                "feature_flag_cache_lookup_failed",
                flag=flag.value,
                tenant_id=tenant_id,
                error=str(e),
            )

    # 3. Redis legacy fallback.
    if tenant_id and _redis_enabled(flag, str(tenant_id)):
        return True

    # 4. default false.
    return False


def get_all_flags(tenant_id: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """모든 FeatureFlag 의 effective 값 + source 반환.

    GET /api/v1/admin/settings/feature-flags 응답용.
    Returns: {flag_name: {value: bool, source: 'env'|'db'|'redis'|'default'}}
    """
    out: dict[str, dict[str, Any]] = {}
    db_flags: dict[str, bool] = {}
    if tenant_id:
        try:
            db_flags = _get_tenant_flags_cached(str(tenant_id))
        except Exception:  # noqa: BLE001
            db_flags = {}

    for flag in FeatureFlag:
        env_val = _env_explicit(flag)
        if env_val is not None:
            out[flag.value] = {"value": env_val, "source": "env"}
            continue
        if flag.value in db_flags:
            out[flag.value] = {"value": bool(db_flags[flag.value]), "source": "db"}
            continue
        if tenant_id and _redis_enabled(flag, str(tenant_id)):
            out[flag.value] = {"value": True, "source": "redis"}
            continue
        out[flag.value] = {"value": False, "source": "default"}
    return out
