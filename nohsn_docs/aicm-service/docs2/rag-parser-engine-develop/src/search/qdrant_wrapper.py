"""Lucas-KMS Phase 2 T2.5 — Qdrant tenant-aware wrapper (이중 안전망).

이 모듈은 raw ``QdrantClient`` / ``AsyncQdrantClient`` 직접 호출 대신 사용해야 하는
얇은 wrapper 를 제공한다. 목표:

1. *모든* upsert payload 에 ``tenant_id`` (+선택 ``tenant_slug``) 가 들어가도록 강제.
2. *모든* search 시 payload-level ``tenant_id`` ``must`` filter 가 적용되도록 강제.
3. collection naming 은 기존 ``build_collection_name`` / ``build_tenant_collection_name``
   함수를 그대로 사용 — 회귀 방지 (변경 X).
4. raw client 접근 site 가 새로 추가되는 것을 검색 (grep) 으로 식별 가능하도록 wrapper
   진입점 단일화.

사용자 절칙:
- 하드코딩 X — tenant_id 는 호출자가 반드시 인자로 명시.
- 기존 백엔드 재작성 X — 본 모듈은 추가 안전망. 기존 QdrantClient API 시그니처 보존.
"""
from __future__ import annotations

from typing import Any

from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchValue,
)

from src.common.logging import get_logger
from src.search.hybrid.qdrant_dense import (
    build_collection_name,
    build_tenant_collection_name,
)

log = get_logger(__name__)


class TenantPayloadError(ValueError):
    """payload 에 tenant_id 가 누락된 경우. cross-tenant 누수 방어 fail-fast."""


def assert_payload_has_tenant_id(payload: dict[str, Any], context: str = "") -> None:
    """payload 가 tenant_id 를 포함하는지 검증. 누락 시 즉시 raise.

    Args:
        payload: Qdrant point payload (upsert 전).
        context: log/exception 용 호출 site 식별자.

    Raises:
        TenantPayloadError — payload 에 ``tenant_id`` 키가 없거나 빈 값.
    """
    tid = payload.get("tenant_id")
    if not tid:
        raise TenantPayloadError(
            f"qdrant_upsert_missing_tenant_id: context={context!r} payload_keys="
            f"{sorted(payload.keys())!r}"
        )


def build_tenant_must_filter(
    tenant_id: str,
    extra_conditions: list[FieldCondition] | None = None,
) -> Filter:
    """tenant_id 를 ``must`` filter 의 *첫* 조건으로 강제하는 헬퍼.

    raw ``Filter(must=[...])`` 를 직접 빌드하는 코드 대신 본 함수를 통해 빌드해야
    cross-tenant filter 누락이 방지된다.

    Args:
        tenant_id: 호출자 tenant UUID/str — 빈 값이면 ``ValueError``.
        extra_conditions: 추가 ``must`` 조건 (repo, status 등).

    Returns:
        ``Filter(must=[tenant_id 조건, *extra_conditions])``.
    """
    if not tenant_id:
        raise TenantPayloadError(
            f"build_tenant_must_filter_missing_tenant_id: tenant_id={tenant_id!r}"
        )
    conditions: list[FieldCondition] = [
        FieldCondition(
            key="tenant_id",
            match=MatchValue(value=str(tenant_id)),
        )
    ]
    if extra_conditions:
        conditions.extend(extra_conditions)
    return Filter(must=conditions)


async def tenant_aware_upsert(
    client: Any,
    *,
    collection_name: str,
    tenant_id: str,
    points: list[Any],
    tenant_slug: str | None = None,
) -> int:
    """tenant_id 가 *모든* point payload 에 들어있는지 검증하고 upsert 호출.

    raw ``client.upsert(...)`` 직접 호출 대신 본 wrapper 통과 시 cross-tenant
    누수 차단 보장.

    Args:
        client: Qdrant client (sync/async — wrapper 가 모두 처리).
        collection_name: 사전 빌드된 collection 이름 (``build_collection_name``).
        tenant_id: 호출자 tenant UUID/str — 모든 payload 와 일치 검증.
        points: ``PointStruct`` 리스트. 각 ``.payload`` 에 tenant_id 필수.
        tenant_slug: 선택 — payload 보강용 (없으면 skip).

    Returns:
        upsert 된 point 수.

    Raises:
        TenantPayloadError — payload tenant_id 누락 / 불일치.
    """
    if not tenant_id:
        raise TenantPayloadError(
            f"tenant_aware_upsert_missing_tenant_id: collection={collection_name!r}"
        )
    tid = str(tenant_id)

    # 각 point payload 검증 — 없으면 보강, 있으면 일치 확인.
    for p in points:
        payload = getattr(p, "payload", None)
        if payload is None:
            raise TenantPayloadError(
                f"tenant_aware_upsert_point_without_payload: collection={collection_name!r}"
            )
        existing = payload.get("tenant_id")
        if not existing:
            payload["tenant_id"] = tid
            if tenant_slug and not payload.get("tenant_slug"):
                payload["tenant_slug"] = tenant_slug
        elif str(existing) != tid:
            raise TenantPayloadError(
                f"tenant_aware_upsert_tenant_mismatch: "
                f"expected={tid!r} got={existing!r} collection={collection_name!r}"
            )

    import asyncio
    import inspect

    upsert_fn = client.upsert
    if inspect.iscoroutinefunction(upsert_fn):
        await upsert_fn(collection_name=collection_name, points=points)
    else:
        await asyncio.to_thread(
            upsert_fn,
            collection_name=collection_name,
            points=points,
        )
    return len(points)


__all__ = [
    "TenantPayloadError",
    "assert_payload_has_tenant_id",
    "build_collection_name",
    "build_tenant_collection_name",
    "build_tenant_must_filter",
    "tenant_aware_upsert",
]
