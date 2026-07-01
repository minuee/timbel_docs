"""AICM 오브젝트 스토리지 모듈 — MinIO/S3 호환."""

from src.pipeline.storage.config import StorageConfig, storage_config
from src.pipeline.storage.object_store import ObjectStore

__all__ = ["ObjectStore", "StorageConfig", "storage_config"]
