"""Document.status 변경 시 Qdrant/ES payload 를 동기화한다.

문서함에서 문서를 active/deactive 로 토글하면 검색 결과에 즉시 반영되도록
인덱스의 `document_status` payload/필드를 업데이트한다.

재시도 정책:
  - Qdrant/ES 각각 지수 백오프 3회 재시도 (0.2s → 0.4s → 0.8s)
  - 모두 실패해도 예외 전파 X (상위 흐름 차단 금지).
  - 최종 실패 시 processing_meta.payload_sync_failed = {"qdrant": bool, "es": bool, "last_error": "..."}
    로 마킹하여 backfill 스크립트가 감지/재복구 가능하도록 한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.common.constants import QDRANT_COLLECTION_PREFIX
from src.common.logging import get_logger

log = get_logger(__name__)

_MAX_RETRIES = 3
_BASE_BACKOFF_S = 0.2


async def _resolve_tenant_slug(document_id: UUID | str, db: AsyncSession) -> str | None:
    try:
        r = await db.execute(
            text(
                "SELECT t.slug FROM tenants t "
                "JOIN repositories r ON r.tenant_id = t.id "
                "JOIN documents d ON d.repository_id = r.id "
                "WHERE d.id = :doc_id"
            ),
            {"doc_id": str(document_id)},
        )
        row = r.fetchone()
        if not row:
            # D31d Phase 3 §2 — slug not found (RLS context 적용 불가).
            # GPT-5 pre verdict §2/§3: NotFound 류만 RLS 위반으로 분류
            # (transient DB / network 오류 제외).
            try:
                from src.common.metrics import KMS_RLS_VIOLATION_TOTAL

                KMS_RLS_VIOLATION_TOTAL.labels(
                    source="payload_sync",
                    table="documents",
                    operation="tenant_slug_not_found",
                ).inc()
            except Exception:  # noqa: BLE001
                pass
            return None
        return row[0]
    except Exception as exc:
        log.warning("payload_sync_tenant_slug_lookup_failed", document_id=str(document_id), error=str(exc))
        return None


async def _resolve_tenant_id(document_id: UUID | str, db: AsyncSession) -> str | None:
    """Lucas-KMS Phase 2 T2.6 — tenant_id 도 조회 (ES update_by_query filter 용).

    실패 / NotFound 시 None 반환 — caller 가 None 처리.
    """
    try:
        r = await db.execute(
            text(
                "SELECT r.tenant_id FROM repositories r "
                "JOIN documents d ON d.repository_id = r.id "
                "WHERE d.id = :doc_id"
            ),
            {"doc_id": str(document_id)},
        )
        row = r.fetchone()
        if not row:
            return None
        return str(row[0])
    except Exception as exc:
        log.warning(
            "payload_sync_tenant_id_lookup_failed",
            document_id=str(document_id),
            error=str(exc),
        )
        return None


async def _qdrant_set_document_status_once(tenant_slug: str, document_id: UUID | str, new_status: str) -> int:
    """단일 시도. 성공 시 1, 실패 시 예외 전파."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=getattr(settings, "QDRANT_API_KEY", None) or None,
        timeout=30,
    )
    collection = f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"
    flt = Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
    )

    await asyncio.to_thread(
        client.set_payload,
        collection_name=collection,
        payload={"document_status": new_status},
        points=flt,
        wait=True,
    )
    log.info(
        "qdrant_document_status_synced",
        collection=collection,
        document_id=str(document_id),
        new_status=new_status,
    )
    return 1


async def _qdrant_set_document_status(tenant_slug: str, document_id: UUID | str, new_status: str) -> tuple[int, str]:
    """지수 백오프로 3회까지 재시도. (synced_count, last_error) 반환."""
    last_err = ""
    for attempt in range(_MAX_RETRIES):
        try:
            n = await _qdrant_set_document_status_once(tenant_slug, document_id, new_status)
            return n, ""
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < _MAX_RETRIES - 1:
                backoff = _BASE_BACKOFF_S * (2**attempt)
                log.info(
                    "qdrant_sync_retry",
                    document_id=str(document_id),
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error=last_err,
                )
                await asyncio.sleep(backoff)
    log.warning(
        "qdrant_document_status_sync_failed",
        document_id=str(document_id),
        new_status=new_status,
        error=last_err,
        attempts=_MAX_RETRIES,
    )
    return 0, last_err


async def _es_set_document_status_once(
    tenant_slug: str,
    document_id: UUID | str,
    new_status: str,
    tenant_id: str | None = None,
) -> int:
    """단일 시도.

    Lucas-KMS Phase 2 T2.6 — tenant_id 가 주어지면 update_by_query 의 query 에
    must filter 로 추가 (이중 안전망). 미주어 시 legacy 호환 (index name 격리만).
    """
    from elasticsearch import AsyncElasticsearch

    from src.search.es_wrapper import with_tenant_term
    from src.search.hybrid.es_keyword import build_block_es_index_name

    index = build_block_es_index_name(tenant_slug)
    client = AsyncElasticsearch(
        hosts=[settings.ELASTICSEARCH_URL],
        request_timeout=15,
        max_retries=2,
        retry_on_timeout=True,
    )
    try:
        base_q = {"term": {"document_id": str(document_id)}}
        scoped_q = with_tenant_term(base_q, tenant_id)
        resp = await client.update_by_query(
            index=index,
            query=scoped_q,
            script={
                "source": "ctx._source.document_status = params.s",
                "lang": "painless",
                "params": {"s": new_status},
            },
            refresh=True,
            conflicts="proceed",
        )
        updated = resp.get("updated", 0) if isinstance(resp, dict) else getattr(resp, "updated", 0)
        log.info(
            "es_document_status_synced",
            index=index,
            document_id=str(document_id),
            new_status=new_status,
            updated=updated,
        )
        return updated
    finally:
        await client.close()


async def _es_set_document_status(
    tenant_slug: str,
    document_id: UUID | str,
    new_status: str,
    tenant_id: str | None = None,
) -> tuple[int, str]:
    """지수 백오프로 3회까지 재시도. (updated_count, last_error) 반환.

    Lucas-KMS Phase 2 T2.6 — tenant_id 도 전달 (must filter 강화).
    """
    last_err = ""
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            n = await _es_set_document_status_once(
                tenant_slug, document_id, new_status, tenant_id=tenant_id
            )
            # D31d Phase 3 §3 — success counter (alert §4-#8 분모 용).
            try:
                from src.common.metrics import KMS_ES_INDEX_SUCCESS_TOTAL

                KMS_ES_INDEX_SUCCESS_TOTAL.inc()
            except Exception:  # noqa: BLE001
                pass
            return n, ""
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                backoff = _BASE_BACKOFF_S * (2**attempt)
                log.info(
                    "es_sync_retry",
                    document_id=str(document_id),
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error=last_err,
                )
                # D31d Phase 3 §3 — retry counter (최종 실패 attempt 제외).
                try:
                    from src.common.metrics import (
                        KMS_ES_INDEX_RETRY_TOTAL,
                        classify_es_error,
                    )

                    KMS_ES_INDEX_RETRY_TOTAL.labels(
                        reason=classify_es_error(exc)
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(backoff)
    log.warning(
        "es_document_status_sync_failed",
        document_id=str(document_id),
        new_status=new_status,
        error=last_err,
        attempts=_MAX_RETRIES,
    )
    # D31d Phase 3 §3 — failure counter (최종 실패 — retry 와 중복 X).
    if last_exc is not None:
        try:
            from src.common.metrics import (
                KMS_ES_INDEX_FAILURE_TOTAL,
                classify_es_error,
            )

            KMS_ES_INDEX_FAILURE_TOTAL.labels(
                reason=classify_es_error(last_exc)
            ).inc()
        except Exception:  # noqa: BLE001
            pass
    return 0, last_err


async def _qdrant_set_document_title_once(
    tenant_slug: str, document_id: UUID | str, new_title: str
) -> int:
    """단일 시도. 지정 문서의 모든 포인트에 document_title 을 set_payload 로 주입."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=getattr(settings, "QDRANT_API_KEY", None) or None,
        timeout=30,
    )
    collection = f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"
    flt = Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
    )

    await asyncio.to_thread(
        client.set_payload,
        collection_name=collection,
        payload={"document_title": new_title},
        points=flt,
        wait=True,
    )
    log.info(
        "qdrant_document_title_synced",
        collection=collection,
        document_id=str(document_id),
        new_title=new_title,
    )
    return 1


async def _qdrant_set_document_title(
    tenant_slug: str, document_id: UUID | str, new_title: str
) -> tuple[int, str]:
    """지수 백오프 3회 재시도. (synced_count, last_error) 반환."""
    last_err = ""
    for attempt in range(_MAX_RETRIES):
        try:
            n = await _qdrant_set_document_title_once(tenant_slug, document_id, new_title)
            return n, ""
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < _MAX_RETRIES - 1:
                backoff = _BASE_BACKOFF_S * (2**attempt)
                log.info(
                    "qdrant_title_sync_retry",
                    document_id=str(document_id),
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error=last_err,
                )
                await asyncio.sleep(backoff)
    log.warning(
        "qdrant_document_title_sync_failed",
        document_id=str(document_id),
        new_title=new_title,
        error=last_err,
        attempts=_MAX_RETRIES,
    )
    return 0, last_err


async def _es_set_document_title_once(
    tenant_slug: str,
    document_id: UUID | str,
    new_title: str,
    tenant_id: str | None = None,
) -> int:
    """단일 시도. update_by_query 로 document_title 필드 갱신.

    Lucas-KMS Phase 2 T2.6 — tenant_id 가 주어지면 must filter 에 추가.
    """
    from elasticsearch import AsyncElasticsearch

    from src.search.es_wrapper import with_tenant_term
    from src.search.hybrid.es_keyword import build_block_es_index_name

    index = build_block_es_index_name(tenant_slug)
    client = AsyncElasticsearch(
        hosts=[settings.ELASTICSEARCH_URL],
        request_timeout=15,
        max_retries=2,
        retry_on_timeout=True,
    )
    try:
        base_q = {"term": {"document_id": str(document_id)}}
        scoped_q = with_tenant_term(base_q, tenant_id)
        resp = await client.update_by_query(
            index=index,
            query=scoped_q,
            script={
                "source": "ctx._source.document_title = params.t",
                "lang": "painless",
                "params": {"t": new_title},
            },
            refresh=True,
            conflicts="proceed",
        )
        updated = resp.get("updated", 0) if isinstance(resp, dict) else getattr(resp, "updated", 0)
        log.info(
            "es_document_title_synced",
            index=index,
            document_id=str(document_id),
            new_title=new_title,
            updated=updated,
        )
        return updated
    finally:
        await client.close()


async def _es_set_document_title(
    tenant_slug: str,
    document_id: UUID | str,
    new_title: str,
    tenant_id: str | None = None,
) -> tuple[int, str]:
    """지수 백오프 3회 재시도.

    Lucas-KMS Phase 2 T2.6 — tenant_id 전달 (must filter 강화).
    """
    last_err = ""
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            n = await _es_set_document_title_once(
                tenant_slug, document_id, new_title, tenant_id=tenant_id
            )
            # D31d Phase 3 §3 — success counter.
            try:
                from src.common.metrics import KMS_ES_INDEX_SUCCESS_TOTAL

                KMS_ES_INDEX_SUCCESS_TOTAL.inc()
            except Exception:  # noqa: BLE001
                pass
            return n, ""
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                backoff = _BASE_BACKOFF_S * (2**attempt)
                log.info(
                    "es_title_sync_retry",
                    document_id=str(document_id),
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error=last_err,
                )
                # D31d Phase 3 §3 — retry counter.
                try:
                    from src.common.metrics import (
                        KMS_ES_INDEX_RETRY_TOTAL,
                        classify_es_error,
                    )

                    KMS_ES_INDEX_RETRY_TOTAL.labels(
                        reason=classify_es_error(exc)
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(backoff)
    log.warning(
        "es_document_title_sync_failed",
        document_id=str(document_id),
        new_title=new_title,
        error=last_err,
        attempts=_MAX_RETRIES,
    )
    # D31d Phase 3 §3 — failure counter.
    if last_exc is not None:
        try:
            from src.common.metrics import (
                KMS_ES_INDEX_FAILURE_TOTAL,
                classify_es_error,
            )

            KMS_ES_INDEX_FAILURE_TOTAL.labels(
                reason=classify_es_error(last_exc)
            ).inc()
        except Exception:  # noqa: BLE001
            pass
    return 0, last_err


async def _mark_sync_failure(
    db: AsyncSession,
    document_id: UUID | str,
    new_status: str,
    qdrant_failed: bool,
    es_failed: bool,
    last_error: str,
) -> None:
    """DB processing_meta 에 sync 실패 표식을 남긴다. backfill 스크립트가 이를 감지해 재시도."""
    try:
        patch = {
            "payload_sync_failed": {
                "qdrant": qdrant_failed,
                "es": es_failed,
                "target_status": new_status,
                "last_error": last_error[:500],
                "failed_at": time.time(),
            }
        }
        await db.execute(
            text(
                "UPDATE documents "
                "SET processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                "WHERE id = :did"
            ),
            {"did": str(document_id), "patch": json.dumps(patch)},
        )
        # 호출측 세션을 그대로 쓰되 커밋은 호출측에 맡긴다 (request context 트랜잭션 보호)
    except Exception as exc:
        log.warning(
            "payload_sync_failure_mark_failed",
            document_id=str(document_id),
            error=str(exc),
        )


async def _clear_sync_failure(db: AsyncSession, document_id: UUID | str) -> None:
    """성공적으로 sync 가 끝났을 때 이전 실패 표식을 제거한다."""
    try:
        await db.execute(
            text(
                "UPDATE documents "
                "SET processing_meta = processing_meta - 'payload_sync_failed' "
                "WHERE id = :did "
                "AND processing_meta ? 'payload_sync_failed'"
            ),
            {"did": str(document_id)},
        )
    except Exception as exc:
        log.debug(
            "payload_sync_failure_clear_failed",
            document_id=str(document_id),
            error=str(exc),
        )


async def sync_document_status(
    document_id: UUID | str,
    new_status: str,
    db: AsyncSession,
    tenant_slug: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, int]:
    """DB의 status 변경을 Qdrant/ES 의 document_status payload 로 전파한다.

    - 각 백엔드 최대 3회 재시도 (지수 백오프).
    - 최종 실패 시 processing_meta.payload_sync_failed 에 실패 정보를 기록.
    - 성공 시 기존 실패 표식 제거.

    Args:
        document_id: 대상 문서 UUID
        new_status: 새 status 문자열 (active / pending_review / archived / failed / draft / processing)
        db: AsyncSession (tenant_slug 조회 + 실패 마킹에 사용)
        tenant_slug: 이미 알고 있으면 전달 (DB 조회 생략)
        tenant_id: Lucas-KMS Phase 2 T2.6 — ES must filter 강화용. 없으면 조회.

    Returns:
        {"qdrant": <synced>, "es": <updated>}. 각 백엔드 실패해도 예외 전파 X.
    """
    slug = tenant_slug or await _resolve_tenant_slug(document_id, db)
    if not slug:
        log.warning(
            "payload_sync_skipped_no_slug",
            document_id=str(document_id),
            new_status=new_status,
        )
        return {"qdrant": 0, "es": 0}

    # Lucas-KMS Phase 2 T2.6 — tenant_id 자동 조회 (인자 미명시 시).
    tid = tenant_id or await _resolve_tenant_id(document_id, db)

    qdrant_n, q_err = await _qdrant_set_document_status(slug, document_id, new_status)
    es_n, e_err = await _es_set_document_status(slug, document_id, new_status, tenant_id=tid)

    qdrant_failed = bool(q_err)
    es_failed = bool(e_err)

    if qdrant_failed or es_failed:
        await _mark_sync_failure(
            db,
            document_id,
            new_status,
            qdrant_failed=qdrant_failed,
            es_failed=es_failed,
            last_error=q_err or e_err,
        )
    else:
        await _clear_sync_failure(db, document_id)

    return {"qdrant": qdrant_n, "es": es_n}


async def _qdrant_set_search_excluded_once(tenant_slug: str, document_id: UUID | str, excluded: bool) -> int:
    """Qdrant 블럭 포인트의 search_excluded payload 를 단일 시도로 갱신."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=getattr(settings, "QDRANT_API_KEY", None) or None,
        timeout=30,
    )
    collection = f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"
    flt = Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
    )
    await asyncio.to_thread(
        client.set_payload,
        collection_name=collection,
        payload={"search_excluded": excluded},
        points=flt,
        wait=True,
    )
    log.info(
        "qdrant_search_excluded_synced",
        collection=collection,
        document_id=str(document_id),
        excluded=excluded,
    )
    return 1


async def _es_set_search_excluded_once(
    tenant_slug: str,
    document_id: UUID | str,
    excluded: bool,
    tenant_id: str | None = None,
) -> int:
    """ES 블럭 도큐먼트의 search_excluded 필드를 단일 시도로 갱신.

    Lucas-KMS Phase 2 T2.6 — tenant_id 가 주어지면 must filter 에 추가.
    """
    from elasticsearch import AsyncElasticsearch

    from src.search.es_wrapper import with_tenant_term
    from src.search.hybrid.es_keyword import build_block_es_index_name

    index = build_block_es_index_name(tenant_slug)
    client = AsyncElasticsearch(
        hosts=[settings.ELASTICSEARCH_URL],
        request_timeout=15,
        max_retries=2,
        retry_on_timeout=True,
    )
    try:
        base_q = {"term": {"document_id": str(document_id)}}
        scoped_q = with_tenant_term(base_q, tenant_id)
        resp = await client.update_by_query(
            index=index,
            query=scoped_q,
            script={
                "source": "ctx._source.search_excluded = params.v",
                "lang": "painless",
                "params": {"v": excluded},
            },
            refresh=True,
            conflicts="proceed",
        )
        updated = resp.get("updated", 0) if isinstance(resp, dict) else getattr(resp, "updated", 0)
        log.info(
            "es_search_excluded_synced",
            index=index,
            document_id=str(document_id),
            excluded=excluded,
            updated=updated,
        )
        return updated
    finally:
        await client.close()


async def sync_search_excluded(
    document_id: UUID | str,
    excluded: bool,
    db: AsyncSession,
    tenant_slug: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, int]:
    """DB 의 search_excluded 변경을 Qdrant/ES payload 로 전파한다.

    실패해도 예외 전파 X — 검색 제외 토글은 즉각성보다 안정성 우선.

    Args:
        document_id: 대상 문서 UUID
        excluded: True 이면 검색 제외, False 이면 복원
        db: AsyncSession (tenant_slug 조회용)
        tenant_slug: 이미 알고 있으면 전달 (DB 조회 생략)
        tenant_id: Lucas-KMS Phase 2 T2.6 — ES must filter 강화. 없으면 조회.

    Returns:
        {"qdrant": <synced>, "es": <updated>}.
    """
    slug = tenant_slug or await _resolve_tenant_slug(document_id, db)
    if not slug:
        log.warning(
            "search_excluded_sync_skipped_no_slug",
            document_id=str(document_id),
            excluded=excluded,
        )
        return {"qdrant": 0, "es": 0}

    # Lucas-KMS Phase 2 T2.6 — tenant_id 자동 조회.
    tid = tenant_id or await _resolve_tenant_id(document_id, db)

    qdrant_n = 0
    es_n = 0

    for attempt in range(_MAX_RETRIES):
        try:
            qdrant_n = await _qdrant_set_search_excluded_once(slug, document_id, excluded)
            break
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_BASE_BACKOFF_S * (2**attempt))
            else:
                log.warning("qdrant_search_excluded_sync_failed", document_id=str(document_id), error=err)

    for attempt in range(_MAX_RETRIES):
        try:
            es_n = await _es_set_search_excluded_once(slug, document_id, excluded, tenant_id=tid)
            # D31d Phase 3 §3 — success counter.
            try:
                from src.common.metrics import KMS_ES_INDEX_SUCCESS_TOTAL

                KMS_ES_INDEX_SUCCESS_TOTAL.inc()
            except Exception:  # noqa: BLE001
                pass
            break
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            if attempt < _MAX_RETRIES - 1:
                # D31d Phase 3 §3 — retry counter.
                try:
                    from src.common.metrics import (
                        KMS_ES_INDEX_RETRY_TOTAL,
                        classify_es_error,
                    )

                    KMS_ES_INDEX_RETRY_TOTAL.labels(
                        reason=classify_es_error(exc)
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(_BASE_BACKOFF_S * (2**attempt))
            else:
                log.warning("es_search_excluded_sync_failed", document_id=str(document_id), error=err)
                # D31d Phase 3 §3 — failure counter (최종 실패).
                try:
                    from src.common.metrics import (
                        KMS_ES_INDEX_FAILURE_TOTAL,
                        classify_es_error,
                    )

                    KMS_ES_INDEX_FAILURE_TOTAL.labels(
                        reason=classify_es_error(exc)
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass

    return {"qdrant": qdrant_n, "es": es_n}


async def sync_document_title(
    document_id: UUID | str,
    new_title: str,
    db: AsyncSession,
    tenant_slug: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, int]:
    """DB 의 title 변경을 Qdrant/ES 의 document_title payload 로 전파한다.

    title 은 검색 결과 UI 에 노출되는 단순 표시 필드 (필터 X) 이므로 실패해도
    검색 기능은 지속된다. `sync_document_status` 와 달리 실패 마킹은 하지 않고
    로그만 남긴다 — 운영 중 제목 변경은 드물고 다음 변경 시 재동기화 가능.

    Args:
        document_id: 대상 문서 UUID
        new_title: 새 title 문자열
        db: AsyncSession (tenant_slug 조회용)
        tenant_slug: 이미 알고 있으면 전달 (DB 조회 생략)
        tenant_id: Lucas-KMS Phase 2 T2.6 — ES must filter 강화. 없으면 조회.

    Returns:
        {"qdrant": <synced>, "es": <updated>}. 각 백엔드 실패해도 예외 전파 X.
    """
    slug = tenant_slug or await _resolve_tenant_slug(document_id, db)
    if not slug:
        log.warning(
            "payload_title_sync_skipped_no_slug",
            document_id=str(document_id),
            new_title=new_title,
        )
        return {"qdrant": 0, "es": 0}

    # Lucas-KMS Phase 2 T2.6 — tenant_id 자동 조회.
    tid = tenant_id or await _resolve_tenant_id(document_id, db)

    qdrant_n, _q_err = await _qdrant_set_document_title(slug, document_id, new_title)
    es_n, _e_err = await _es_set_document_title(slug, document_id, new_title, tenant_id=tid)
    return {"qdrant": qdrant_n, "es": es_n}
