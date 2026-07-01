"""Qdrant HNSW 파라미터 튜닝 및 컬렉션 최적화."""

from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    CollectionStatus,
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
    VectorsConfig,
)

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


class QdrantOptimizer:
    """
    Qdrant 컬렉션 최적화 관리.

    - HNSW 파라미터 튜닝 (m, ef_construct, ef)
    - 온디스크 벡터 저장소 설정
    - 샤드 설정
    - 컬렉션 정보/통계 조회
    """

    # 기본 HNSW 파라미터
    DEFAULT_M: int = 16
    DEFAULT_EF_CONSTRUCT: int = 200
    DEFAULT_SEARCH_EF: int = 128
    HIGH_QUALITY_SEARCH_EF: int = 256

    # BGE-M3 dense 벡터 차원
    DEFAULT_DENSE_DIM: int = 1024

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncQdrantClient:
        """지연 초기화된 Qdrant 클라이언트 반환."""
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                prefer_grpc=True,
            )
        return self._client

    async def create_optimized_collection(
        self,
        collection_name: str,
        dense_dim: int | None = None,
        m: int | None = None,
        ef_construct: int | None = None,
        on_disk: bool = False,
        shard_number: int = 1,
        replication_factor: int = 1,
    ) -> None:
        """
        최적화된 HNSW 파라미터로 컬렉션 생성.

        Args:
            collection_name: 컬렉션 이름
            dense_dim: Dense 벡터 차원 (기본 1024)
            m: HNSW M 파라미터 (기본 16)
            ef_construct: HNSW 인덱스 구축 시 ef (기본 200)
            on_disk: 벡터를 디스크에 저장할지 여부 (대용량 컬렉션용)
            shard_number: 샤드 수 (대용량 데이터셋용)
            replication_factor: 레플리카 수
        """
        client = await self._get_client()
        effective_dim = dense_dim or self.DEFAULT_DENSE_DIM
        effective_m = m or self.DEFAULT_M
        effective_ef_construct = ef_construct or self.DEFAULT_EF_CONSTRUCT

        hnsw_config = HnswConfigDiff(
            m=effective_m,
            ef_construct=effective_ef_construct,
            full_scan_threshold=10000,
            on_disk=on_disk,
        )

        vectors_config = VectorsConfig(
            **{
                "dense": VectorParams(
                    size=effective_dim,
                    distance=Distance.COSINE,
                    on_disk=on_disk,
                    hnsw_config=hnsw_config,
                ),
            }
        )

        sparse_vectors_config = {
            "sparse": SparseVectorParams(
                index=SparseIndexParams(
                    on_disk=on_disk,
                ),
            ),
        }

        await client.create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config,
            sparse_vectors_config=sparse_vectors_config,
            hnsw_config=hnsw_config,
            shard_number=shard_number,
            replication_factor=replication_factor,
        )

        log.info(
            "optimized_collection_created",
            collection=collection_name,
            m=effective_m,
            ef_construct=effective_ef_construct,
            on_disk=on_disk,
            shard_number=shard_number,
        )

    async def update_hnsw_params(
        self,
        collection_name: str,
        m: int | None = None,
        ef_construct: int | None = None,
        on_disk: bool | None = None,
    ) -> None:
        """
        기존 컬렉션의 HNSW 파라미터 업데이트.

        주의: m과 ef_construct 변경 시 인덱스 재구축이 발생함.
        """
        client = await self._get_client()

        hnsw_config = HnswConfigDiff(
            m=m,
            ef_construct=ef_construct,
            on_disk=on_disk,
        )

        await client.update_collection(
            collection_name=collection_name,
            hnsw_config=hnsw_config,
        )

        log.info(
            "hnsw_params_updated",
            collection=collection_name,
            m=m,
            ef_construct=ef_construct,
            on_disk=on_disk,
        )

    async def update_optimizer_config(
        self,
        collection_name: str,
        indexing_threshold: int | None = None,
        memmap_threshold: int | None = None,
    ) -> None:
        """
        컬렉션의 옵티마이저 설정 업데이트.

        Args:
            indexing_threshold: 인덱싱 임계값 (벡터 수)
            memmap_threshold: memmap 활성화 임계값 (벡터 수)
        """
        client = await self._get_client()

        optimizer_config = OptimizersConfigDiff(
            indexing_threshold=indexing_threshold,
            memmap_threshold=memmap_threshold,
        )

        await client.update_collection(
            collection_name=collection_name,
            optimizer_config=optimizer_config,
        )

        log.info(
            "optimizer_config_updated",
            collection=collection_name,
            indexing_threshold=indexing_threshold,
            memmap_threshold=memmap_threshold,
        )

    async def get_collection_info(self, collection_name: str) -> dict[str, Any]:
        """
        컬렉션 정보 조회.

        반환: 컬렉션 상태, 벡터 수, HNSW 파라미터 등.
        """
        client = await self._get_client()
        info = await client.get_collection(collection_name=collection_name)

        return {
            "collection_name": collection_name,
            "status": info.status.value if isinstance(info.status, CollectionStatus) else str(info.status),
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "segments_count": len(info.segments) if hasattr(info, "segments") and info.segments else None,
            "config": {
                "hnsw_config": {
                    "m": info.config.hnsw_config.m if info.config and info.config.hnsw_config else None,
                    "ef_construct": info.config.hnsw_config.ef_construct if info.config and info.config.hnsw_config else None,
                },
                "optimizer_config": {
                    "indexing_threshold": info.config.optimizer_config.indexing_threshold if info.config and info.config.optimizer_config else None,
                },
            },
        }

    async def get_collection_stats(self, collection_name: str) -> dict[str, Any]:
        """
        컬렉션 상세 통계 조회.

        벡터 수, 디스크 사용량, 인덱스 상태 등.
        """
        client = await self._get_client()
        info = await client.get_collection(collection_name=collection_name)

        stats: dict[str, Any] = {
            "collection_name": collection_name,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
            "status": info.status.value if isinstance(info.status, CollectionStatus) else str(info.status),
        }

        # 인덱싱 상태
        if info.status == CollectionStatus.GREEN:
            stats["indexed"] = True
        else:
            stats["indexed"] = False

        return stats

    async def list_collections(self) -> list[str]:
        """모든 컬렉션 이름 목록 반환."""
        client = await self._get_client()
        collections = await client.get_collections()
        return [c.name for c in collections.collections]
