"""Qdrant 컬렉션 자동 생성/관리 헬퍼.

블럭 파이프라인용 테넌트 단일 컬렉션(aicm_{tenant_slug}_blocks)을
필요 시점에 자동 생성한다.
"""

from __future__ import annotations

import asyncio

from src.common.config import settings
from src.common.constants import QDRANT_COLLECTION_PREFIX
from src.common.logging import get_logger

log = get_logger(__name__)

# 이미 확인한 컬렉션을 프로세스 내에서 캐싱 (중복 API 호출 방지)
_ensured_collections: set[str] = set()


def build_block_collection_name(tenant_slug: str) -> str:
    """블럭 컬렉션 이름을 생성한다. 형식: aicm_{tenant_slug}_blocks."""
    return f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_blocks"


async def ensure_block_collection(tenant_slug: str) -> None:
    """테넌트의 블럭 컬렉션이 존재하지 않으면 생성한다.

    - Dense 벡터: 1024차원 (BGE-M3), cosine distance
    - Sparse 벡터: named "sparse"
    - Payload 인덱스: document_id, repository_id, block_type, block_index
    """
    collection_name = build_block_collection_name(tenant_slug)

    # 프로세스 내 캐시 확인 (이미 보장된 컬렉션)
    if collection_name in _ensured_collections:
        return

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            Distance,
            PayloadSchemaType,
            SparseVectorParams,
            VectorParams,
        )

        client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
        )

        # 동기 클라이언트이므로 to_thread 사용
        exists = await asyncio.to_thread(client.collection_exists, collection_name)
        if not exists:
            await asyncio.to_thread(
                client.create_collection,
                collection_name=collection_name,
                vectors_config={
                    "dense": VectorParams(
                        size=1024,
                        distance=Distance.COSINE,
                        on_disk=True,
                    ),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                },
            )

            # Payload 인덱스 생성
            for field_name, field_type in [
                ("document_id", PayloadSchemaType.KEYWORD),
                ("repository_id", PayloadSchemaType.KEYWORD),
                ("block_type", PayloadSchemaType.KEYWORD),
                ("block_index", PayloadSchemaType.INTEGER),
            ]:
                await asyncio.to_thread(
                    client.create_payload_index,
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )

            # Ontology payload indices (Phase A-3)
            for onto_field, onto_type in [
                ("nature", PayloadSchemaType.KEYWORD),
                ("validity_status", PayloadSchemaType.KEYWORD),
                ("domain_category_ids", PayloadSchemaType.KEYWORD),
                ("speakers", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    await asyncio.to_thread(
                        client.create_payload_index,
                        collection_name=collection_name,
                        field_name=onto_field,
                        field_schema=onto_type,
                    )
                except Exception:
                    # Index may already exist — skip gracefully
                    pass

            log.info("block_collection_created", collection=collection_name)
        else:
            log.debug("block_collection_already_exists", collection=collection_name)

        _ensured_collections.add(collection_name)

    except ImportError:
        log.warning("qdrant_client_not_installed_skipping_collection_creation")
    except Exception as exc:
        log.warning(
            "block_collection_ensure_failed",
            collection=collection_name,
            error=str(exc),
        )


def reset_collection_cache() -> None:
    """테스트용: 프로세스 내 캐시를 초기화한다."""
    _ensured_collections.clear()
