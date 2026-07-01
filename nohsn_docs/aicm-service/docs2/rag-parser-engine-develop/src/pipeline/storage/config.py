"""MinIO/S3 오브젝트 스토리지 설정."""

from pydantic_settings import BaseSettings


class StorageConfig(BaseSettings):
    """MinIO/S3 스토리지 환경 변수 설정.

    .env 파일 또는 환경 변수로 오버라이드 가능.
    """

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False

    MINIO_DOCUMENT_BUCKET: str = "aicm-documents"
    MINIO_INTERMEDIATE_BUCKET: str = "aicm-intermediate"
    MINIO_IMAGE_BUCKET: str = "aicm-images"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


storage_config = StorageConfig()
