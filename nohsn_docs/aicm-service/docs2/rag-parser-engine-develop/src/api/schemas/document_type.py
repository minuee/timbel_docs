"""문서타입 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentTypeCreate(BaseModel):
    """문서타입 생성 요청."""

    name: str = Field(..., min_length=1, max_length=100, description="문서타입 이름")
    description: Optional[str] = Field(None, description="문서타입 설명")
    icon: Optional[str] = Field(None, max_length=50, description="UI 아이콘 코드")


class DocumentTypeResponse(BaseModel):
    """문서타입 응답."""

    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str]
    icon: Optional[str]
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}
