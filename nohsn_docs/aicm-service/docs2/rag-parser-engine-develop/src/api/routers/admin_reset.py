"""Admin Reset — 개발/테스트 용도의 전체 데이터 초기화 엔드포인트.

처리 중 워커 태스크를 실제로 kill 한 뒤, 모든 런타임 데이터 저장소를 비우고
기본 tenant/repository 시드를 복구한다.

운영 배포에서는 절대 노출하지 말 것.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


def _admin_dependencies() -> list:
    """Wave D (KMS-Plus, 2026-04-25) — KMS_RBAC_ENFORCED=true 면 platform admin 요구.

    이 라우터는 cache flush + 전체 reset 같은 파괴적 작업을 노출 — 운영 배포
    에서는 반드시 인증을 강제해야 한다. 기본값(false)은 dev/test 호환을 위해
    남기지만 운영 .env 에선 true 권장.

    2026-04-28 codex 검토: 기존 ``require_role_dep("admin")`` 은 RBAC 순위가
    ``owner > admin`` 이라 일반 사용자(owner role) 가 통과 가능. 시스템
    영역은 ``require_platform_admin`` (preferences.user_groups 'admin' 보유)
    으로 강화.
    """
    if os.environ.get("KMS_RBAC_ENFORCED", "false").lower() == "true":
        from src.api.auth.platform_role import require_platform_admin

        return [Depends(require_platform_admin)]
    return []


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["관리자 초기화"],
    dependencies=_admin_dependencies(),
)


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_REPO_ID = "00000000-0000-0000-0000-000000000001"

WORKER_CONTAINERS = ["kms-pipeline-worker", "kms-chunk-service"]
UPLOAD_DIR = Path("/data/uploads")

DATA_TABLES = [
    "anonymization_logs",
    "api_keys",
    "audit_logs",
    "blocks",
    "categories",
    "chunks",
    "dlq_messages",
    "document_categories",
    "document_types",
    "documents",
    "integrations",
    "lifecycle_feedback",
    "lifecycle_policies",
    "llm_usage",
    "scheduled_actions",
    "search_logs",
    "sections",
    "tenant_links",
    "transition_events",
    "user_repository_access",
    "users",
    "repositories",
    "tenants",
]


class StepResult(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ResetResponse(BaseModel):
    status: str  # "ok" | "partial"
    steps: list[StepResult]


async def _step(name: str, fn: Any, steps: list[StepResult]) -> None:
    try:
        detail = await fn() if asyncio.iscoroutinefunction(fn) else await asyncio.to_thread(fn)
        steps.append(StepResult(name=name, ok=True, detail=str(detail or "")))
        log.info("reset_step_ok", step=name, detail=str(detail or ""))
    except Exception as exc:  # noqa: BLE001
        steps.append(StepResult(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}"))
        log.exception("reset_step_failed", step=name)


# ---------------------------------------------------------------------------
# 개별 스텝
# ---------------------------------------------------------------------------


def _restart_workers() -> str:
    import docker  # type: ignore[import-not-found]

    client = docker.from_env()
    restarted = []
    for name in WORKER_CONTAINERS:
        try:
            c = client.containers.get(name)
            c.restart(timeout=5)
            restarted.append(name)
        except docker.errors.NotFound:  # type: ignore[attr-defined]
            log.warning("reset_worker_not_found", container=name)
    return f"restarted: {', '.join(restarted) or 'none'}"


async def _truncate_postgres() -> str:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        tables_sql = ", ".join(DATA_TABLES)
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"))
            await conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, slug, config, plan, tenant_type, context_config)
                    VALUES (:tid, 'Default Tenant', 'default', '{}'::jsonb, 'free', 'personal', '{}'::jsonb)
                    """
                ),
                {"tid": DEFAULT_TENANT_ID},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO repositories (id, tenant_id, name)
                    VALUES (:rid, :tid, 'Test Repository')
                    """
                ),
                {"rid": DEFAULT_REPO_ID, "tid": DEFAULT_TENANT_ID},
            )
        return f"truncated {len(DATA_TABLES)} tables, reseeded default tenant + repo"
    finally:
        await engine.dispose()


def _reset_qdrant() -> str:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.QDRANT_URL)
    cols = client.get_collections().collections
    deleted = []
    for col in cols:
        name = col.name
        if name.startswith("aicm_") and name.endswith("_blocks"):
            client.delete_collection(collection_name=name)
            deleted.append(name)
    return f"deleted: {', '.join(deleted) or 'none'}"


async def _reset_elasticsearch() -> str:
    from elasticsearch import AsyncElasticsearch

    es = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
    try:
        indices = await es.cat.indices(format="json", h="index")
        targets = [
            i["index"] for i in indices
            if i.get("index", "").startswith("aicm_") and i.get("index", "").endswith("_blocks")
        ]
        for name in targets:
            await es.indices.delete(index=name, ignore_unavailable=True)
        return f"deleted: {', '.join(targets) or 'none'}"
    finally:
        await es.close()


def _reset_minio() -> str:
    from minio import Minio
    from minio.deleteobjects import DeleteObject

    from src.pipeline.storage.config import storage_config as scfg

    client = Minio(
        scfg.MINIO_ENDPOINT,
        access_key=scfg.MINIO_ACCESS_KEY,
        secret_key=scfg.MINIO_SECRET_KEY,
        secure=scfg.MINIO_SECURE,
    )
    buckets = [scfg.MINIO_DOCUMENT_BUCKET, scfg.MINIO_INTERMEDIATE_BUCKET, scfg.MINIO_IMAGE_BUCKET]
    total = 0
    for bucket in buckets:
        if not client.bucket_exists(bucket):
            continue
        objs = client.list_objects(bucket, recursive=True)
        del_iter = (DeleteObject(o.object_name) for o in objs)
        errors = list(client.remove_objects(bucket, del_iter))
        for err in errors:
            log.warning("minio_delete_error", bucket=bucket, error=str(err))
        total += 1
    return f"emptied {total} buckets"


async def _reset_redis() -> str:
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.REDIS_URL)
    try:
        await r.flushall()
        return "flushed"
    finally:
        await r.aclose()


async def _reset_kafka() -> str:
    from aiokafka.admin import AIOKafkaAdminClient

    admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        topics = await admin.list_topics()
        targets = [t for t in topics if t.startswith("aicm.")]
        if targets:
            await admin.delete_topics(targets)
        return f"deleted {len(targets)} topics"
    finally:
        await admin.close()


def _clear_uploads() -> str:
    if not UPLOAD_DIR.exists():
        return "uploads dir not found"
    removed = 0
    for child in UPLOAD_DIR.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                continue
        removed += 1
    return f"removed {removed} entries"


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/cache/flush",
    summary="검색 캐시 강제 무효화 (저장소 단위 또는 전체)",
)
async def flush_search_cache(repository_id: str | None = None) -> dict[str, Any]:
    """검색 캐시 무효화.

    repository_id 가 주어지면 해당 저장소만 (repo_version INCR), 없으면 search_cache 키 전체 삭제.
    """
    import redis.asyncio as aioredis
    from uuid import UUID as _UUID

    from src.search.cache import SearchCache

    if repository_id:
        try:
            repo_uuid = _UUID(repository_id)
        except ValueError:
            return {"status": "error", "detail": "invalid repository_id"}
        new_v = await SearchCache().bump_repo_version(repo_uuid)
        return {"status": "ok", "scope": "repository", "repository_id": repository_id, "new_version": new_v}

    r = aioredis.from_url(settings.REDIS_URL)
    try:
        deleted = 0
        async for key in r.scan_iter(match="aicm:search_cache:*", count=500):
            await r.delete(key)
            deleted += 1
        async for key in r.scan_iter(match="aicm:repo_version:*", count=500):
            await r.delete(key)
            deleted += 1
        return {"status": "ok", "scope": "all", "deleted_keys": deleted}
    finally:
        await r.aclose()


@router.post("/reset", response_model=ResetResponse, summary="전체 초기화 (개발/테스트용)")
async def reset_all() -> ResetResponse:
    """전체 런타임 데이터 초기화 + 처리 중 워커 태스크 kill."""
    steps: list[StepResult] = []

    await _step("restart_workers", _restart_workers, steps)
    await _step("truncate_postgres", _truncate_postgres, steps)
    await _step("reset_qdrant", _reset_qdrant, steps)
    await _step("reset_elasticsearch", _reset_elasticsearch, steps)
    await _step("reset_minio", _reset_minio, steps)
    await _step("reset_redis", _reset_redis, steps)
    await _step("reset_kafka", _reset_kafka, steps)
    await _step("clear_uploads", _clear_uploads, steps)

    status = "ok" if all(s.ok for s in steps) else "partial"
    log.info("reset_all_complete", status=status, steps=[s.model_dump() for s in steps])
    return ResetResponse(status=status, steps=steps)
