"""문서 버전 관리 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class VersionHistoryItem(BaseModel):
    """버전 이력 항목."""

    document_id: UUID
    version: int
    status: str
    title: str
    created_at: datetime
    created_by: Optional[UUID] = None
    chunk_count: int = 0
    source_file: Optional[str] = None


class VersionUploadResponse(BaseModel):
    """새 버전 업로드 응답."""

    archived_document_id: UUID
    new_document_id: UUID
    old_version: int
    new_version: int
    status: str = "processing"
    message: str = "새 버전이 업로드되었습니다. 처리가 완료되면 검색 가능합니다."


class RollbackResponse(BaseModel):
    """롤백 응답."""

    archived_document_id: UUID
    restored_document_id: UUID
    restored_version: int
    message: str = "버전이 롤백되었습니다."
