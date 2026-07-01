"""API Key Pydantic 스키마 및 ORM 재노출.

ORM 모델은 src.core.models.api_key.APIKey를 단일 출처(SSOT)로 사용한다.
이 모듈에서는 APIKey를 APIKeyORM 으로 별칭하여 기존 코드 호환을 유지한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ORM 모델은 core에서 가져온다 (테이블 중복 방지)
from src.core.models.api_key import APIKey as APIKeyORM  # noqa: F401


# ---------------------------------------------------------------------------
# Pydantic 스키마
# ---------------------------------------------------------------------------

class APIKeyRecord(BaseModel):
    """API Key 검증 후 반환되는 레코드."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    name: str
    key_hash: str
    key_prefix: str
    scopes: list[str]
    rate_limit: int = 100
    allowed_repository_ids: list[uuid.UUID] | None = None
    expires_at: datetime | None = None
    is_active: bool = True
    last_used_at: datetime | None = None
    usage_count: int = 0

    model_config = {"from_attributes": True}


class APIKeyCreateRequest(BaseModel):
    """API Key 생성 요청."""

    name: str = Field(..., min_length=1, max_length=200)
    scopes: list[str] = Field(..., min_length=1)
    rate_limit: int = Field(default=100, ge=1, le=10000)
    user_id: uuid.UUID | None = Field(default=None, description="바인딩할 사용자 ID")
    allowed_repository_ids: list[uuid.UUID] | None = Field(
        default=None, description="허용할 저장소 ID 목록 (None=전체)"
    )
    expires_at: datetime | None = None


class APIKeyCreateResponse(BaseModel):
    """API Key 생성 응답 — api_key 원본은 이 시점에만 반환."""

    api_key: str
    key_id: uuid.UUID
    name: str
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None = None


class APIKeyListItem(BaseModel):
    """API Key 목록 아이템 (원본 키 미포함)."""

    key_id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    rate_limit: int
    user_id: uuid.UUID | None = None
    allowed_repository_ids: list[uuid.UUID] | None = None
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    usage_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyListResponse(BaseModel):
    """API Key 목록 응답."""

    keys: list[APIKeyListItem]


VALID_SCOPES = {"search", "ask", "upload", "webhook", "inbound"}
