from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class CustomToolCreate(BaseModel):
    name: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[a-z][a-z0-9._-]*$",
        description="custom.<name> 형식 권장. ToolPicker / allowed_tools 에 노출되는 이름.",
    )
    description: str = Field(min_length=10, max_length=500)
    category: str = Field(default="custom", max_length=50)
    endpoint_url: str = Field(
        min_length=10,
        max_length=500,
        pattern=r"^https?://",
    )
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    auth_headers: dict[str, str] = Field(
        default_factory=dict,
        description="암호화 저장됨. 실제 webhook 호출 시 자동 주입. 응답에는 노출 X.",
    )
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class CustomToolUpdate(BaseModel):
    description: str | None = None
    category: str | None = None
    endpoint_url: str | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    auth_headers: dict[str, str] | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class CustomToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str
    category: str
    endpoint_url: str
    method: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # auth_headers 는 응답에 노출 X (보안)


class CustomToolTestRequest(BaseModel):
    input_data: dict[str, Any] = Field(default_factory=dict)
