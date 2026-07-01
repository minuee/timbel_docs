"""Repository group Pydantic schemas (Lucas-KMS only).

A named subset of multiple repositories within a tenant, expanded at
search time when callers pass repository_group_id or repository_ids.

Not present in the unified solution.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RepositoryGroupCreate(BaseModel):
    """Group create request."""

    name: str = Field(..., min_length=1, max_length=200, examples=["plan-ops-bundle"])
    description: Optional[str] = Field(None, examples=["plan + ops manuals together"])
    repository_ids: list[UUID] = Field(default_factory=list)
    is_default: bool = Field(False)
    config: dict = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "plan-ops-bundle",
                    "description": "plan + ops manuals together",
                    "repository_ids": [
                        "11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222",
                    ],
                    "is_default": False,
                    "config": {},
                }
            ]
        }
    }


class RepositoryGroupUpdate(BaseModel):
    """Group update request. None fields keep their existing value."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    repository_ids: Optional[list[UUID]] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"name": "plan-ops-bundle-v2", "is_active": True},
            ]
        }
    }


class RepositoryGroupResponse(BaseModel):
    """Group response (with repository_count convenience field)."""

    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str] = None
    repository_ids: list[UUID] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    is_default: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    repository_count: int = 0

    model_config = {"from_attributes": True}


class SetDefaultResponse(BaseModel):
    """set-default endpoint response."""

    group_id: UUID
    is_default: bool = True
    previous_default_group_id: Optional[UUID] = None
