"""저장소 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RepositoryCreate(BaseModel):
    """저장소 생성 요청."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="저장소 이름. tenant 내 unique 권장. 한글/영문/숫자 가능.",
        examples=["공공 SaaS 가이드"],
    )
    description: Optional[str] = Field(
        None,
        description="저장소 설명 (선택). 검색 시 도메인 인식용 hint 로도 활용.",
        examples=["조달청 등록 자료 모음 — SaaS 도입 가이드, 보안 요구사항 등"],
    )
    config: dict = Field(
        default_factory=dict,
        description=(
            "저장소별 설정 오버라이드 (선택). "
            "예: `chunk_size`, `embedding_model`, `default_top_k` 등 — "
            "지정 안 하면 tenant 의 기본값 사용."
        ),
        examples=[{"default_top_k": 5, "chunk_size": 800}],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "공공 SaaS 가이드",
                    "description": "조달청 등록 자료 모음",
                    "config": {},
                }
            ]
        }
    }


class RepositoryUpdate(BaseModel):
    """저장소 수정 요청.

    모든 필드 선택 — None 으로 전달된 필드는 기존 값 유지.
    """

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="새 저장소 이름 (선택)",
        examples=["공공 SaaS 가이드 v2"],
    )
    description: Optional[str] = Field(
        None,
        description="새 설명 (선택)",
        examples=["2026년 갱신본"],
    )
    config: Optional[dict] = Field(
        None,
        description="설정 통째 교체 (부분 머지 X)",
        examples=[{"default_top_k": 10}],
    )
    is_active: Optional[bool] = Field(
        None,
        description="활성 상태 토글 — false 로 두면 검색에서 제외됨",
        examples=[True],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"name": "공공 SaaS 가이드 v2", "is_active": True}
            ]
        }
    }


class RepositoryKindSummary(BaseModel):
    """저장소 안 문서 kind 분포 (alembic 068).

    SOP 와 매뉴얼/FAQ/정책/용어집의 분포를 한눈에. is_sop=true 인 doc 또는
    folder.kind='sop' 인 폴더 안 doc 은 *sop* 으로 카운트, 그 외는 폴더 kind
    (없으면 'manual') 그대로.
    """

    sop_doc_count: int = 0
    manual_doc_count: int = 0
    faq_doc_count: int = 0
    policy_doc_count: int = 0
    glossary_doc_count: int = 0


class RepositoryResponse(BaseModel):
    """저장소 응답."""

    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str]
    config: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # 집계 필드 (API에서 계산하여 주입)
    document_count: int = 0
    chunk_count: int = 0
    # alembic 068 — repo 별 kind 분포. 모두 0 일 수 있음 (default 모두 'manual').
    kind_summary: RepositoryKindSummary = Field(default_factory=RepositoryKindSummary)

    model_config = {"from_attributes": True}
