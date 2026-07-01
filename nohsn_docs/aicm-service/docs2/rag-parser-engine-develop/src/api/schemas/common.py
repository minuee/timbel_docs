"""공통 API 응답 스키마."""

from datetime import datetime
from typing import Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """에러 상세 정보."""

    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ApiResponse(BaseModel, Generic[T]):
    """공통 API 응답 래퍼.

    성공 시 data 에 결과를 담고, 실패 시 error 에 에러 정보를 담는다.
    """

    success: bool = True
    data: Optional[T] = None
    error: Optional[ErrorDetail] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """커서 기반 페이지네이션 응답.

    Attributes:
        items: 결과 목록
        next_cursor: 다음 페이지 커서 (없으면 마지막 페이지)
        total_count: 전체 건수 (선택적, 비용이 클 수 있음)
    """

    items: list[T]
    next_cursor: Optional[str] = None
    total_count: Optional[int] = None


class ErrorResponse(BaseModel):
    """에러 응답 최상위 스키마."""

    error: ErrorDetail
