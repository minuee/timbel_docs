"""A/B 테스트 API 라우터 -- 검색 실험 관리."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.middleware.rbac import require_role
from src.core.models.user import UserRole
from src.search.ab_testing import (
    ABTestConfig,
    ABTestManager,
    ABTestStatus,
    VariantConfig,
)

logger = get_logger(__name__)

router = APIRouter()

# 싱글톤 매니저 인스턴스 (Phase 3에서 DB 기반으로 교체 예정)
_manager = ABTestManager()


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class VariantConfigRequest(BaseModel):
    """변형 설정 요청."""

    variant_id: str
    name: str
    description: str | None = None
    traffic_ratio: float = Field(0.5, ge=0.0, le=1.0)

    dense_weight: float | None = None
    sparse_weight: float | None = None
    keyword_weight: float | None = None
    rerank_enabled: bool | None = None
    rerank_model: str | None = None
    rrf_k: int | None = None
    min_score_threshold: float | None = None


class ABTestCreateRequest(BaseModel):
    """A/B 테스트 생성 요청."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    repository_id: UUID | None = None
    variants: list[VariantConfigRequest] = Field(..., min_length=2)


class ABTestResponse(BaseModel):
    """A/B 테스트 응답."""

    experiment_id: UUID
    name: str
    description: str | None = None
    status: str
    tenant_id: UUID
    repository_id: UUID | None = None
    variants: list[dict]
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None


class ABTestListResponse(BaseModel):
    """A/B 테스트 목록 응답."""

    experiments: list[ABTestResponse]
    total_count: int


# ---------------------------------------------------------------------------
# API 엔드포인트
# ---------------------------------------------------------------------------


def _config_to_response(config: ABTestConfig) -> ABTestResponse:
    """ABTestConfig를 응답 스키마로 변환."""
    return ABTestResponse(
        experiment_id=config.experiment_id,
        name=config.name,
        description=config.description,
        status=config.status.value,
        tenant_id=config.tenant_id,
        repository_id=config.repository_id,
        variants=[v.model_dump() for v in config.variants],
        created_at=config.created_at.isoformat(),
        started_at=config.started_at.isoformat() if config.started_at else None,
        ended_at=config.ended_at.isoformat() if config.ended_at else None,
    )


@router.get(
    "",
    response_model=ApiResponse[ABTestListResponse],
    summary="A/B 테스트 목록 조회",
    dependencies=[Depends(require_role(UserRole.repo_admin))],
)
async def list_ab_tests(
    status: str | None = Query(None, description="상태 필터 (draft, active, paused, completed)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[ABTestListResponse]:
    """테넌트의 A/B 테스트 목록을 조회한다."""
    status_filter = ABTestStatus(status) if status else None
    experiments = _manager.list_experiments(tenant_id=tenant_id, status=status_filter)

    return ApiResponse(
        data=ABTestListResponse(
            experiments=[_config_to_response(e) for e in experiments],
            total_count=len(experiments),
        )
    )


@router.post(
    "",
    response_model=ApiResponse[ABTestResponse],
    summary="A/B 테스트 생성",
    dependencies=[Depends(require_role(UserRole.repo_admin))],
)
async def create_ab_test(
    body: ABTestCreateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[ABTestResponse]:
    """새 A/B 테스트를 생성한다."""
    variants = [
        VariantConfig(
            variant_id=v.variant_id,
            name=v.name,
            description=v.description,
            traffic_ratio=v.traffic_ratio,
            dense_weight=v.dense_weight,
            sparse_weight=v.sparse_weight,
            keyword_weight=v.keyword_weight,
            rerank_enabled=v.rerank_enabled,
            rerank_model=v.rerank_model,
            rrf_k=v.rrf_k,
            min_score_threshold=v.min_score_threshold,
        )
        for v in body.variants
    ]

    config = ABTestConfig(
        name=body.name,
        description=body.description,
        tenant_id=tenant_id,
        repository_id=body.repository_id,
        variants=variants,
    )

    try:
        created = _manager.create_experiment(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "ab_test_created_via_api",
        experiment_id=str(created.experiment_id),
        name=created.name,
    )

    return ApiResponse(data=_config_to_response(created))


@router.get(
    "/{experiment_id}",
    response_model=ApiResponse[ABTestResponse],
    summary="A/B 테스트 상세 조회",
    dependencies=[Depends(require_role(UserRole.repo_admin))],
)
async def get_ab_test(
    experiment_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[ABTestResponse]:
    """특정 A/B 테스트의 상세 정보를 조회한다."""
    exp = _manager.get_experiment(experiment_id)
    if exp is None or exp.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="실험을 찾을 수 없습니다.")

    return ApiResponse(data=_config_to_response(exp))


@router.post(
    "/{experiment_id}/activate",
    response_model=ApiResponse[ABTestResponse],
    summary="A/B 테스트 활성화",
    dependencies=[Depends(require_role(UserRole.repo_admin))],
)
async def activate_ab_test(
    experiment_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[ABTestResponse]:
    """A/B 테스트를 활성화한다."""
    exp = _manager.get_experiment(experiment_id)
    if exp is None or exp.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="실험을 찾을 수 없습니다.")

    activated = _manager.activate_experiment(experiment_id)
    if activated is None:
        raise HTTPException(status_code=400, detail="활성화에 실패했습니다.")

    return ApiResponse(data=_config_to_response(activated))


@router.post(
    "/{experiment_id}/complete",
    response_model=ApiResponse[ABTestResponse],
    summary="A/B 테스트 종료",
    dependencies=[Depends(require_role(UserRole.repo_admin))],
)
async def complete_ab_test(
    experiment_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[ABTestResponse]:
    """A/B 테스트를 종료한다."""
    exp = _manager.get_experiment(experiment_id)
    if exp is None or exp.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="실험을 찾을 수 없습니다.")

    completed = _manager.complete_experiment(experiment_id)
    if completed is None:
        raise HTTPException(status_code=400, detail="종료에 실패했습니다.")

    return ApiResponse(data=_config_to_response(completed))
