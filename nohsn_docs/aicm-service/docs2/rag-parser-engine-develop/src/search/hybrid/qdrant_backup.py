"""Qdrant 스냅샷 백업 및 복구."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient

from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


class QdrantBackupManager:
    """
    Qdrant 스냅샷 백업 및 복구 관리.

    - 컬렉션별 스냅샷 생성
    - 스냅샷 로컬 다운로드
    - 스냅샷으로부터 복구
    - 스냅샷 목록 조회
    """

    DEFAULT_BACKUP_DIR: str = "/data/backups/qdrant"

    def __init__(
        self,
        client: AsyncQdrantClient | None = None,
        backup_dir: str | None = None,
    ) -> None:
        self._client = client
        self._backup_dir = backup_dir or self.DEFAULT_BACKUP_DIR

    async def _get_client(self) -> AsyncQdrantClient:
        """지연 초기화된 Qdrant 클라이언트 반환."""
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                prefer_grpc=False,  # 스냅샷 API는 HTTP 사용
            )
        return self._client

    async def create_snapshot(self, collection_name: str) -> dict[str, Any]:
        """
        컬렉션 스냅샷 생성.

        Args:
            collection_name: 스냅샷을 생성할 컬렉션 이름

        Returns:
            스냅샷 정보 (이름, 크기, 생성시간)
        """
        client = await self._get_client()

        snapshot = await client.create_snapshot(collection_name=collection_name)

        result = {
            "collection_name": collection_name,
            "snapshot_name": snapshot.name,
            "creation_time": str(snapshot.creation_time) if snapshot.creation_time else None,
            "size": snapshot.size,
        }

        log.info(
            "qdrant_snapshot_created",
            collection=collection_name,
            snapshot=snapshot.name,
            size=snapshot.size,
        )

        return result

    async def create_all_snapshots(self) -> list[dict[str, Any]]:
        """
        모든 컬렉션의 스냅샷 생성.

        Returns:
            각 컬렉션의 스냅샷 정보 리스트
        """
        client = await self._get_client()
        collections = await client.get_collections()

        results: list[dict[str, Any]] = []
        for collection in collections.collections:
            try:
                snapshot_info = await self.create_snapshot(collection.name)
                results.append(snapshot_info)
            except Exception:
                log.exception(
                    "qdrant_snapshot_creation_failed",
                    collection=collection.name,
                )
                results.append({
                    "collection_name": collection.name,
                    "error": "snapshot_creation_failed",
                })

        log.info("qdrant_all_snapshots_created", count=len(results))
        return results

    async def download_snapshot(
        self,
        collection_name: str,
        snapshot_name: str,
        target_dir: str | None = None,
    ) -> str:
        """
        스냅샷을 로컬 파일시스템에 다운로드.

        Args:
            collection_name: 컬렉션 이름
            snapshot_name: 스냅샷 이름
            target_dir: 저장 경로 (기본: backup_dir/collection_name/)

        Returns:
            다운로드된 파일 경로
        """
        client = await self._get_client()
        effective_dir = target_dir or os.path.join(self._backup_dir, collection_name)

        # 디렉토리 생성
        Path(effective_dir).mkdir(parents=True, exist_ok=True)

        target_path = os.path.join(effective_dir, snapshot_name)

        # qdrant_client의 snapshot download 사용
        snapshot_bytes = await client.get_snapshot(
            collection_name=collection_name,
            snapshot_name=snapshot_name,
        )

        # snapshot_bytes가 bytes인 경우 직접 쓰기
        if isinstance(snapshot_bytes, bytes):
            with open(target_path, "wb") as f:
                f.write(snapshot_bytes)
        else:
            # AsyncIterator인 경우
            with open(target_path, "wb") as f:
                async for chunk in snapshot_bytes:
                    f.write(chunk)

        file_size = os.path.getsize(target_path)

        log.info(
            "qdrant_snapshot_downloaded",
            collection=collection_name,
            snapshot=snapshot_name,
            path=target_path,
            size=file_size,
        )

        return target_path

    async def restore_snapshot(
        self,
        collection_name: str,
        snapshot_path: str,
    ) -> None:
        """
        로컬 스냅샷 파일로부터 컬렉션 복구.

        주의: 기존 컬렉션이 있으면 삭제 후 복구됨.

        Args:
            collection_name: 복구할 컬렉션 이름
            snapshot_path: 스냅샷 파일 경로
        """
        client = await self._get_client()

        if not os.path.exists(snapshot_path):
            raise FileNotFoundError(f"스냅샷 파일을 찾을 수 없습니다: {snapshot_path}")

        # 기존 컬렉션 존재 여부 확인
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]

        if collection_name in existing:
            log.warning(
                "qdrant_restore_delete_existing",
                collection=collection_name,
            )
            await client.delete_collection(collection_name=collection_name)

        # 스냅샷 업로드로 복구
        await client.recover_snapshot(
            collection_name=collection_name,
            location=snapshot_path,
        )

        log.info(
            "qdrant_snapshot_restored",
            collection=collection_name,
            snapshot_path=snapshot_path,
        )

    async def list_snapshots(self, collection_name: str) -> list[dict[str, Any]]:
        """
        컬렉션의 스냅샷 목록 조회.

        Args:
            collection_name: 컬렉션 이름

        Returns:
            스냅샷 정보 리스트 (이름, 크기, 생성시간)
        """
        client = await self._get_client()

        snapshots = await client.list_snapshots(collection_name=collection_name)

        results: list[dict[str, Any]] = []
        for snap in snapshots:
            results.append({
                "snapshot_name": snap.name,
                "creation_time": str(snap.creation_time) if snap.creation_time else None,
                "size": snap.size,
            })

        log.info(
            "qdrant_snapshots_listed",
            collection=collection_name,
            count=len(results),
        )

        return results

    async def delete_snapshot(
        self,
        collection_name: str,
        snapshot_name: str,
    ) -> None:
        """
        컬렉션의 스냅샷 삭제.

        Args:
            collection_name: 컬렉션 이름
            snapshot_name: 삭제할 스냅샷 이름
        """
        client = await self._get_client()

        await client.delete_snapshot(
            collection_name=collection_name,
            snapshot_name=snapshot_name,
        )

        log.info(
            "qdrant_snapshot_deleted",
            collection=collection_name,
            snapshot=snapshot_name,
        )
