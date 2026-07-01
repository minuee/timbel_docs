"""분류 피드백 통계 API 라우터.

lifecycle_feedback 테이블 기반으로 분류 수정 통계, 사용자별 수정 순위,
SFT 재학습 후보 등을 제공한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, cast, func as sa_func, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.user import UserRole

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 응답 스키마
# ---------------------------------------------------------------------------


class DailyCorrection(BaseModel):
    """일별 수정 건수."""

    date: str = Field(..., description="날짜 (YYYY-MM-DD)")
    count: int = Field(..., description="수정 건수")


class BlockTypeCorrection(BaseModel):
    """블럭 타입별 수정 건수."""

    block_type: str
    count: int


class DomainCorrection(BaseModel):
    """도메인별 수정 건수."""

    field_name: str
    count: int


class NatureFlowItem(BaseModel):
    """nature 수정 흐름 항목 (from -> to)."""

    from_value: str
    to_value: str
    count: int


class ClassificationStatsData(BaseModel):
    """분류 수정 통계 응답 데이터."""

    total_corrections: int = Field(0, description="총 수정 건수")
    daily_corrections: list[DailyCorrection] = Field(default_factory=list)
    most_corrected_block_types: list[BlockTypeCorrection] = Field(default_factory=list)
    most_corrected_fields: list[DomainCorrection] = Field(default_factory=list)
    nature_flow: list[NatureFlowItem] = Field(
        default_factory=list,
        description="nature 필드 수정 흐름 (from -> to)",
    )
    low_confidence_correction_rate: float = Field(
        0.0, description="저신뢰도 블럭 수정률 (%)"
    )


class UserCorrectionItem(BaseModel):
    """사용자별 수정 항목."""

    user_id: str
    correction_count: int


class UserCorrectionsData(BaseModel):
    """사용자별 수정 순위 응답."""

    users: list[UserCorrectionItem] = Field(default_factory=list)


class RetrainingCandidate(BaseModel):
    """SFT 재학습 후보."""

    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    occurrence_count: int = Field(..., description="동일 수정 패턴 반복 횟수")
    example_block_ids: list[str] = Field(default_factory=list)


class RetrainingCandidatesData(BaseModel):
    """SFT 재학습 후보 목록."""

    candidates: list[RetrainingCandidate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 헬퍼: 모델 지연 임포트
# ---------------------------------------------------------------------------


def _get_feedback_model():
    """LifecycleFeedback ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.lifecycle_feedback import LifecycleFeedback

        return LifecycleFeedback
    except Exception as exc:
        logger.warning("lifecycle_feedback_model_import_failed", error=str(exc))
        return None


def _get_block_model():
    """Block ORM 모델을 지연 로딩한다."""
    try:
        from src.core.models.block import Block

        return Block
    except Exception as exc:
        logger.warning("block_model_import_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# 1. GET /feedback-stats/classification
# ---------------------------------------------------------------------------


@router.get(
    "/classification",
    response_model=ApiResponse[ClassificationStatsData],
    summary="분류 수정 통계",
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def get_classification_stats(
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ClassificationStatsData]:
    """분류 수정 통계를 반환한다.

    - 총 수정 건수, 일별 수정 추이
    - 가장 많이 수정된 블럭 타입, 필드
    - nature 수정 흐름 매트릭스
    - 저신뢰도 블럭 수정률
    """
    Feedback = _get_feedback_model()
    Block = _get_block_model()
    if Feedback is None:
        logger.warning("lifecycle_feedback_table_unavailable")
        return ApiResponse(data=ClassificationStatsData())

    since = datetime.now(timezone.utc) - timedelta(days=days)
    base_filters = [
        Feedback.tenant_id == tenant_id,
        Feedback.feedback_type == "correction",
        Feedback.created_at >= since,
    ]

    try:
        # 1) 총 수정 건수
        total_stmt = select(sa_func.count(Feedback.id)).where(*base_filters)
        total_result = await db.execute(total_stmt)
        total_corrections = total_result.scalar_one() or 0

        # 2) 일별 수정 건수
        day_col = sa_func.date_trunc("day", Feedback.created_at).label("day")
        daily_stmt = (
            select(day_col, sa_func.count(Feedback.id).label("count"))
            .where(*base_filters)
            .group_by(day_col)
            .order_by(day_col)
        )
        daily_result = await db.execute(daily_stmt)
        daily_corrections = [
            DailyCorrection(
                date=row.day.strftime("%Y-%m-%d") if row.day else "",
                count=row.count,
            )
            for row in daily_result.all()
        ]

        # 3) 가장 많이 수정된 블럭 타입 (Block 조인)
        most_corrected_block_types: list[BlockTypeCorrection] = []
        if Block is not None:
            bt_stmt = (
                select(
                    Block.block_type,
                    sa_func.count(Feedback.id).label("count"),
                )
                .join(Block, Feedback.block_id == Block.id)
                .where(*base_filters)
                .group_by(Block.block_type)
                .order_by(sa_func.count(Feedback.id).desc())
                .limit(10)
            )
            bt_result = await db.execute(bt_stmt)
            most_corrected_block_types = [
                BlockTypeCorrection(block_type=row.block_type, count=row.count)
                for row in bt_result.all()
            ]

        # 4) 가장 많이 수정된 필드 (field_name별)
        field_stmt = (
            select(
                Feedback.field_name,
                sa_func.count(Feedback.id).label("count"),
            )
            .where(*base_filters)
            .group_by(Feedback.field_name)
            .order_by(sa_func.count(Feedback.id).desc())
            .limit(10)
        )
        field_result = await db.execute(field_stmt)
        most_corrected_fields = [
            DomainCorrection(field_name=row.field_name, count=row.count)
            for row in field_result.all()
        ]

        # 5) nature 수정 흐름 (field_name='nature'인 경우 old_value -> new_value)
        nature_flow: list[NatureFlowItem] = []
        nature_stmt = (
            select(
                Feedback.old_value,
                Feedback.new_value,
                sa_func.count(Feedback.id).label("count"),
            )
            .where(
                *base_filters,
                Feedback.field_name == "nature",
            )
            .group_by(Feedback.old_value, Feedback.new_value)
            .order_by(sa_func.count(Feedback.id).desc())
            .limit(50)
        )
        nature_result = await db.execute(nature_stmt)
        for row in nature_result.all():
            old_val = ""
            new_val = ""
            if row.old_value is not None:
                old_val = (
                    row.old_value.get("value", str(row.old_value))
                    if isinstance(row.old_value, dict)
                    else str(row.old_value)
                )
            if row.new_value is not None:
                new_val = (
                    row.new_value.get("value", str(row.new_value))
                    if isinstance(row.new_value, dict)
                    else str(row.new_value)
                )
            nature_flow.append(
                NatureFlowItem(from_value=old_val, to_value=new_val, count=row.count)
            )

        # 6) 저신뢰도 블럭 수정률
        low_confidence_rate = 0.0
        if Block is not None:
            # 저신뢰도 = classification_provenance.confidence < 0.5
            # 전체 저신뢰도 블럭 수 대비 수정된 블럭 수
            try:
                low_conf_total_stmt = select(sa_func.count(Block.id)).where(
                    Block.repository_id.in_(
                        select(Block.repository_id)
                        .join(Feedback, Feedback.block_id == Block.id)
                        .where(Feedback.tenant_id == tenant_id)
                        .distinct()
                    ),
                    Block.classification_provenance.isnot(None),
                    cast(
                        Block.classification_provenance["confidence"].as_string(),
                        String,
                    ).cast(sa_func.numeric) < 0.5,  # type: ignore[union-attr]
                )
                low_total = (await db.execute(low_conf_total_stmt)).scalar_one() or 0

                if low_total > 0:
                    low_corrected_stmt = (
                        select(sa_func.count(sa_func.distinct(Feedback.block_id)))
                        .join(Block, Feedback.block_id == Block.id)
                        .where(
                            *base_filters,
                            Block.classification_provenance.isnot(None),
                            cast(
                                Block.classification_provenance["confidence"].as_string(),
                                String,
                            ).cast(sa_func.numeric) < 0.5,  # type: ignore[union-attr]
                        )
                    )
                    low_corrected = (await db.execute(low_corrected_stmt)).scalar_one() or 0
                    low_confidence_rate = round(
                        (low_corrected / low_total) * 100, 1
                    )
            except Exception as exc:
                logger.debug("low_confidence_rate_calc_failed", error=str(exc))

        return ApiResponse(
            data=ClassificationStatsData(
                total_corrections=total_corrections,
                daily_corrections=daily_corrections,
                most_corrected_block_types=most_corrected_block_types,
                most_corrected_fields=most_corrected_fields,
                nature_flow=nature_flow,
                low_confidence_correction_rate=low_confidence_rate,
            )
        )

    except Exception as exc:
        logger.warning("classification_stats_query_failed", error=str(exc))
        return ApiResponse(data=ClassificationStatsData())


# ---------------------------------------------------------------------------
# 2. GET /feedback-stats/user-corrections
# ---------------------------------------------------------------------------


@router.get(
    "/user-corrections",
    response_model=ApiResponse[UserCorrectionsData],
    summary="사용자별 수정 순위",
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def get_user_corrections(
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    limit: int = Query(20, ge=1, le=100, description="최대 반환 건수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserCorrectionsData]:
    """사용자별 수정 횟수 순위를 반환한다."""
    Feedback = _get_feedback_model()
    if Feedback is None:
        return ApiResponse(data=UserCorrectionsData())

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        stmt = (
            select(
                cast(Feedback.user_id, String).label("uid"),
                sa_func.count(Feedback.id).label("cnt"),
            )
            .where(
                Feedback.tenant_id == tenant_id,
                Feedback.feedback_type == "correction",
                Feedback.created_at >= since,
                Feedback.user_id.isnot(None),
            )
            .group_by(Feedback.user_id)
            .order_by(sa_func.count(Feedback.id).desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        users = [
            UserCorrectionItem(user_id=row.uid, correction_count=row.cnt)
            for row in result.all()
        ]
        return ApiResponse(data=UserCorrectionsData(users=users))

    except Exception as exc:
        logger.warning("user_corrections_query_failed", error=str(exc))
        return ApiResponse(data=UserCorrectionsData())


# ---------------------------------------------------------------------------
# 3. GET /feedback-stats/retraining-candidates
# ---------------------------------------------------------------------------


@router.get(
    "/retraining-candidates",
    response_model=ApiResponse[RetrainingCandidatesData],
    summary="SFT 재학습 후보 (재현성 높은 수정 패턴)",
    dependencies=[Depends(require_role(UserRole.tenant_admin))],
)
async def get_retraining_candidates(
    days: int = Query(90, ge=1, le=365, description="조회 기간 (일)"),
    limit: int = Query(50, ge=1, le=200, description="최대 반환 건수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RetrainingCandidatesData]:
    """동일 수정 패턴이 반복적으로 발생한 항목을 재학습 후보로 반환한다.

    field_name + old_value + new_value 조합이 2회 이상 발생한 패턴을 추출한다.
    """
    Feedback = _get_feedback_model()
    if Feedback is None:
        return ApiResponse(data=RetrainingCandidatesData())

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # 패턴별 횟수 집계
        stmt = (
            select(
                Feedback.field_name,
                cast(Feedback.old_value, String).label("old_val"),
                cast(Feedback.new_value, String).label("new_val"),
                sa_func.count(Feedback.id).label("cnt"),
                sa_func.array_agg(cast(Feedback.block_id, String)).label("block_ids"),
            )
            .where(
                Feedback.tenant_id == tenant_id,
                Feedback.feedback_type == "correction",
                Feedback.created_at >= since,
            )
            .group_by(Feedback.field_name, cast(Feedback.old_value, String), cast(Feedback.new_value, String))
            .having(sa_func.count(Feedback.id) >= 2)
            .order_by(sa_func.count(Feedback.id).desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        candidates = []
        for row in result.all():
            example_ids = row.block_ids[:5] if row.block_ids else []
            candidates.append(
                RetrainingCandidate(
                    field_name=row.field_name,
                    old_value=row.old_val,
                    new_value=row.new_val,
                    occurrence_count=row.cnt,
                    example_block_ids=example_ids,
                )
            )

        return ApiResponse(data=RetrainingCandidatesData(candidates=candidates))

    except Exception as exc:
        logger.warning("retraining_candidates_query_failed", error=str(exc))
        return ApiResponse(data=RetrainingCandidatesData())
