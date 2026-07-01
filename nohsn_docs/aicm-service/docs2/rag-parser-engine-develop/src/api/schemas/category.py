"""카테고리 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    """카테고리 생성 요청."""

    name: str = Field(..., min_length=1, max_length=200, description="카테고리 이름")
    description: Optional[str] = Field(None, description="카테고리 설명")
    parent_id: Optional[UUID] = Field(None, description="상위 카테고리 ID (다단계 계층)")
    sort_order: int = Field(default=0, description="정렬 순서")
    icon: Optional[str] = Field(None, max_length=50, description="UI 아이콘(Font Awesome 이름)")


class CategoryUpdate(BaseModel):
    """카테고리 수정 요청."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    icon: Optional[str] = None


class CategoryResponse(BaseModel):
    """카테고리 응답 (트리 구조 지원)."""

    id: UUID
    repository_id: UUID
    name: str
    description: Optional[str]
    parent_id: Optional[UUID]
    sort_order: int
    icon: Optional[str] = None
    is_active: bool
    created_at: datetime
    children: list["CategoryResponse"] = Field(default_factory=list)

    model_config = {"from_attributes": True}
