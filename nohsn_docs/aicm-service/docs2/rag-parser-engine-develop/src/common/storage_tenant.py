"""Multi-store tenant isolation helper (Phase 2.7).

KMS-Plus 의 다중 스토어 — MinIO / Redis / Kafka — 에서 tenant_id 격리를
일관되게 강제하기 위한 키/엔벨로프 생성 헬퍼.

배경 (spec Section 8.4-8.6):
- MinIO: object key 에 ``{tenant_id}/`` prefix 강제 (또는 ``lucas-{tenant_id}`` bucket)
- Redis: 모든 key 에 ``lucas:{tenant_id}:`` prefix 강제 (공유 key 는 ``lucas:_shared:``)
- Kafka: producer 가 message body 에 ``tenant_id`` 필드를 *반드시* 포함

본 모듈은 *헬퍼만* 제공한다. 호출처는 점진적으로 마이그레이션한다 — 기존
key/bucket scheme 은 fallback 으로 *유지* 하여 운영 중 redeploy 시 데이터
손실을 방지한다 (backward compatibility).

설계 원칙:
- 하드코딩 X — tenant_id 는 항상 변수
- 기존 백엔드 재작성 X — wrapper 도입 + 호출처 점진 update
- KMS / Lucas (agent) 양쪽 모두 동일 helper 사용 → cross-tenant 차단 일관성
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# 공통 상수
# ---------------------------------------------------------------------------

#: KMS-Plus 공통 prefix. 기존 ``aicm:`` 와 구분되어 점진 마이그레이션 가능.
LUCAS_PREFIX = "lucas"

#: 공유 key (tenant 무관) 명시용 sentinel.
SHARED_TENANT_SENTINEL = "_shared"


# ---------------------------------------------------------------------------
# Tenant ID normalization
# ---------------------------------------------------------------------------

def normalize_tenant_id(tenant_id: str | UUID | None) -> str:
    """tenant_id 를 안전한 문자열로 정규화한다.

    - UUID → str(UUID)
    - None → SHARED_TENANT_SENTINEL (공유 자원으로 명시)
    - 공백/특수문자가 포함된 문자열은 그대로 두되, 빈 문자열은 sentinel 로 폴백.

    Args:
        tenant_id: 정규화할 테넌트 식별자.

    Returns:
        정규화된 문자열 식별자.

    Note:
        의도적으로 None 을 *조용히* sentinel 로 변환하지 않고, *명시적* sentinel
        반환만 허용한다. 호출처에서 None 을 넘기는 것은 명백한 호출 실수일 수
        있으므로 ValueError 로 막아야 안전하다 — 단, MinIO ``upload_document``
        같이 *반드시* tenant_id 가 있는 경로에서만 enforce 한다. 공유 cache 처럼
        의도적으로 tenant 무관인 경우는 ``redis_shared_key`` 를 사용해야 한다.
    """
    if tenant_id is None:
        return SHARED_TENANT_SENTINEL
    if isinstance(tenant_id, UUID):
        return str(tenant_id)
    s = str(tenant_id).strip()
    if not s:
        return SHARED_TENANT_SENTINEL
    return s


def require_tenant_id(tenant_id: str | UUID | None) -> str:
    """tenant_id 가 반드시 있어야 하는 경로용 strict 검증.

    Raises:
        ValueError: tenant_id 가 None 이거나 빈 문자열일 때.
    """
    if tenant_id is None:
        raise ValueError("tenant_id required (None not allowed in strict path)")
    normalized = normalize_tenant_id(tenant_id)
    if normalized == SHARED_TENANT_SENTINEL:
        raise ValueError(
            "tenant_id required (empty value resolves to shared sentinel)"
        )
    return normalized


# ---------------------------------------------------------------------------
# MinIO object key helper
# ---------------------------------------------------------------------------

def minio_key(tenant_id: str | UUID, *parts: str) -> str:
    """MinIO object key 를 tenant prefix 와 함께 생성한다.

    형식: ``{tenant_id}/{parts[0]}/{parts[1]}/...``

    Args:
        tenant_id: 테넌트 ID (strict — None/empty 금지).
        *parts: object key 의 path 조각 (예: ``document_id, "parsed.json"``).

    Returns:
        ``{tenant_id}/document_id/parsed.json`` 형태의 키.

    Raises:
        ValueError: tenant_id 가 None/empty 거나 parts 가 비었을 때.

    Example:
        >>> minio_key("t1", "doc-42", "parsed.json")
        't1/doc-42/parsed.json'
    """
    t = require_tenant_id(tenant_id)
    if not parts:
        raise ValueError("minio_key: at least one path part required")
    cleaned = [str(p).strip().strip("/").strip() for p in parts]
    cleaned = [p for p in cleaned if p]
    if not cleaned:
        raise ValueError("minio_key: all path parts were empty after stripping")
    return f"{t}/" + "/".join(cleaned)


def minio_key_has_tenant_prefix(object_key: str, tenant_id: str | UUID) -> bool:
    """기존 object_key 가 이미 tenant prefix 를 포함하는지 검사 (backward compat).

    이미 ``{tenant_id}/...`` 로 시작하면 True — 재 prefix 시 ``t1/t1/doc-42``
    같은 이중 prefix 를 방지하는 데 사용한다.
    """
    t = normalize_tenant_id(tenant_id)
    if not t or t == SHARED_TENANT_SENTINEL:
        return False
    return object_key.startswith(f"{t}/")


# ---------------------------------------------------------------------------
# Redis key helper
# ---------------------------------------------------------------------------

def redis_key(tenant_id: str | UUID, *parts: str) -> str:
    """Redis key 에 ``lucas:{tenant_id}:`` prefix 를 강제로 부여한다.

    형식: ``lucas:{tenant_id}:{parts[0]}:{parts[1]}:...``

    Args:
        tenant_id: 테넌트 ID (strict).
        *parts: key 구성 조각.

    Returns:
        ``lucas:t1:cache:doc-42`` 형태의 키.

    Raises:
        ValueError: tenant_id 가 strict 조건을 위배하거나 parts 가 비었을 때.

    Example:
        >>> redis_key("t1", "cache", "doc-42")
        'lucas:t1:cache:doc-42'
    """
    t = require_tenant_id(tenant_id)
    if not parts:
        raise ValueError("redis_key: at least one part required")
    cleaned = [str(p).strip().strip(":").strip() for p in parts]
    cleaned = [p for p in cleaned if p]
    if not cleaned:
        raise ValueError("redis_key: all parts were empty after stripping")
    return f"{LUCAS_PREFIX}:{t}:" + ":".join(cleaned)


def redis_shared_key(*parts: str) -> str:
    """tenant 무관 공유 Redis key — ``lucas:_shared:`` prefix.

    공유 key 는 호출 시점에 *명시적* 으로 표시되어야 cross-tenant 데이터
    오염을 막을 수 있다. silent 한 'tenant_id=None → 공유' 경로는 피한다.

    Example:
        >>> redis_shared_key("vllm_health")
        'lucas:_shared:vllm_health'
    """
    if not parts:
        raise ValueError("redis_shared_key: at least one part required")
    cleaned = [str(p).strip().strip(":").strip() for p in parts]
    cleaned = [p for p in cleaned if p]
    if not cleaned:
        raise ValueError("redis_shared_key: all parts were empty after stripping")
    return f"{LUCAS_PREFIX}:{SHARED_TENANT_SENTINEL}:" + ":".join(cleaned)


def redis_key_extract_tenant(key: str) -> str | None:
    """Redis key 에서 tenant_id 부분을 추출 (감사/통계용).

    Returns:
        ``lucas:{tenant_id}:...`` 의 tenant 부분. ``_shared`` 또는 비-lucas key
        면 None.
    """
    if not key.startswith(f"{LUCAS_PREFIX}:"):
        return None
    rest = key[len(LUCAS_PREFIX) + 1:]
    if rest.startswith(f"{SHARED_TENANT_SENTINEL}:"):
        return None
    parts = rest.split(":", 1)
    if not parts or not parts[0]:
        return None
    return parts[0]


# ---------------------------------------------------------------------------
# Kafka envelope helper
# ---------------------------------------------------------------------------

def kafka_envelope(
    tenant_id: str | UUID,
    payload: dict[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Kafka producer payload 에 tenant_id 를 *반드시* 포함시킨다.

    Consumer 측은 envelope 의 ``tenant_id`` 를 추출해 RLS context 를 설정한다.
    이 헬퍼는 producer 측 누락을 방지하는 *결정적* 진입점이다.

    Args:
        tenant_id: 테넌트 ID (strict).
        payload: 원본 이벤트 dict (shallow copy 됨, 원본 미변경).
        overwrite: payload 에 이미 ``tenant_id`` 가 있을 때 덮어쓸지 여부.
            False (기본) — 기존 값이 다르면 ValueError. True — 강제 덮어쓰기.

    Returns:
        ``tenant_id`` 가 보장된 새 dict.

    Raises:
        ValueError: tenant_id strict 위배, payload 가 dict 아님, 또는 기존
            tenant_id 와 충돌 (overwrite=False).

    Example:
        >>> kafka_envelope("t1", {"document_id": "d1"})
        {'document_id': 'd1', 'tenant_id': 't1'}
    """
    t = require_tenant_id(tenant_id)
    if not isinstance(payload, dict):
        raise ValueError("kafka_envelope: payload must be a dict")

    envelope = dict(payload)
    existing = envelope.get("tenant_id")
    if existing is not None:
        existing_norm = normalize_tenant_id(existing)
        if existing_norm != t and not overwrite:
            raise ValueError(
                f"kafka_envelope: tenant_id mismatch — "
                f"payload has {existing_norm!r}, expected {t!r}"
            )
    envelope["tenant_id"] = t
    return envelope


def kafka_payload_get_tenant(payload: dict[str, Any]) -> str | None:
    """Kafka consumer 측 — payload 에서 tenant_id 추출 (없으면 None).

    Returns:
        정규화된 tenant_id 또는 None (payload 누락 시).
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get("tenant_id")
    if raw is None:
        return None
    return normalize_tenant_id(raw)


__all__ = [
    "LUCAS_PREFIX",
    "SHARED_TENANT_SENTINEL",
    "normalize_tenant_id",
    "require_tenant_id",
    "minio_key",
    "minio_key_has_tenant_prefix",
    "redis_key",
    "redis_shared_key",
    "redis_key_extract_tenant",
    "kafka_envelope",
    "kafka_payload_get_tenant",
]
