"""Classification Quality API 라우터 — 분류 품질 평가 (precision/recall/F1).

lifecycle_feedback 데이터를 ground truth로 사용하여
LLM이 생성한 원본 분류와 사용자 수정 결과를 비교한다.

platform_admin 역할 전용.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, select
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


class FieldMetrics(BaseModel):
    """필드별 정밀도/재현율 메트릭."""

    precision: float = Field(0.0, description="정밀도 (LLM이 맞춘 비율)")
    recall: float = Field(0.0, description="재현율 (실제 값 중 LLM이 포착한 비율)")
    f1: float = Field(0.0, description="F1 스코어")
    samples: int = Field(0, description="샘플 수 (correction 피드백 수)")
    accuracy: float = Field(0.0, description="정확도 (수정 불필요 비율)")


class ConfidenceBucket(BaseModel):
    """신뢰도 구간별 실제 정확도."""

    bucket: str = Field(..., description="신뢰도 구간 (예: '0.9-1.0')")
    predicted_confidence: float = Field(0.0, description="예측 신뢰도 평균")
    actual_accuracy: float = Field(0.0, description="실제 정확도")
    sample_count: int = Field(0, description="샘플 수")


class ClassificationQualityData(BaseModel):
    """분류 품질 종합 메트릭."""

    period_days: int
    total_feedback: int = Field(0, description="전체 피드백 수")
    total_corrections: int = Field(0, description="수정(correction) 수")
    total_confirmations: int = Field(0, description="확인(confirmation) 수")
    nature: FieldMetrics = Field(default_factory=FieldMetrics)
    category: FieldMetrics = Field(default_factory=FieldMetrics)
    confidence_calibration: list[ConfidenceBucket] = Field(default_factory=list)


class BlockTypeQualityItem(BaseModel):
    """블럭 타입별 분류 품질."""

    block_type: str
    total_corrections: int
    nature_accuracy: float = Field(0.0, description="nature 정확도")
    category_accuracy: float = Field(0.0, description="category 정확도")
    avg_confidence: float = Field(0.0)


class BlockTypeQualityData(BaseModel):
    """블럭 타입별 분류 품질 응답."""

    period_days: int
    block_types: list[BlockTypeQualityItem] = Field(default_factory=list)


class ConfusionCell(BaseModel):
    """혼동 행렬 셀."""

    actual: str
    predicted: str
    count: int


class ConfusionMatrixData(BaseModel):
    """혼동 행렬 응답."""

    period_days: int
    labels: list[str] = Field(default_factory=list, description="nature 라벨 목록")
    matrix: list[ConfusionCell] = Field(default_factory=list)
    total_samples: int = 0


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


def _safe_extract_value(jsonb_val: dict | list | str | None) -> str:
    """JSONB 값에서 문자열을 안전하게 추출한다."""
    if jsonb_val is None:
        return ""
    if isinstance(jsonb_val, dict):
        return jsonb_val.get("value", str(jsonb_val))
    if isinstance(jsonb_val, list):
        return str(jsonb_val)
    return str(jsonb_val)


def _compute_metrics(corrections: int, confirmations: int) -> FieldMetrics:
    """수정/확인 카운트로부터 precision/recall/accuracy를 계산한다.

    여기서의 정의:
    - accuracy = confirmations / (corrections + confirmations)
      (LLM 분류가 수정 불필요했던 비율)
    - precision = accuracy (LLM이 분류한 것 중 맞은 비율)
    - recall = accuracy (실제 라벨 중 LLM이 올바르게 포착한 비율)
      ※ 단일 라벨 분류에서는 precision ≈ recall ≈ accuracy
    - f1 = 2 * precision * recall / (precision + recall)
    """
    total = corrections + confirmations
    if total == 0:
        return FieldMetrics()

    accuracy = confirmations / total
    precision = accuracy
    recall = accuracy

    f1 = 0.0
    if (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)

    return FieldMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        samples=total,
        accuracy=round(accuracy, 4),
    )


# ---------------------------------------------------------------------------
# 1. GET /quality/classification — 종합 메트릭
# ---------------------------------------------------------------------------


@router.get(
    "/classification",
    response_model=ApiResponse[ClassificationQualityData],
    summary="분류 품질 종합 메트릭 (precision/recall/F1)",
    dependencies=[Depends(require_role(UserRole.platform_admin))],
)
async def get_classification_quality(
    days: int = Query(30, ge=1, le=365, description="조회 기간 (일)"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ClassificationQualityData]:
    """lifecycle_feedback 기반 분류 품질 메트릭을 반환한다.

    - nature/category 필드별 precision, recall, F1
    - 신뢰도 구간별 실제 정확도 (calibration)
    """
    Feedback = _get_feedback_model()
    Block = _get_block_model()
    if Feedback is None:
        return ApiResponse(data=ClassificationQualityData(period_days=days))

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # 전체 피드백 수 (correction + confirmation)
        total_stmt = (
            select(func.count(Feedback.id))
            .where(Feedback.created_at >= since)
        )
        total_feedback = (await db.execute(total_stmt)).scalar() or 0

        # correction 수
        correction_stmt = (
            select(func.count(Feedback.id))
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "correction",
            )
        )
        total_corrections = (await db.execute(correction_stmt)).scalar() or 0

        # confirmation 수
        confirm_stmt = (
            select(func.count(Feedback.id))
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "confirmation",
            )
        )
        total_confirmations = (await db.execute(confirm_stmt)).scalar() or 0

        # nature 필드별 메트릭
        nature_corrections_stmt = (
            select(func.count(Feedback.id))
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "correction",
                Feedback.field_name == "nature",
            )
        )
        nature_corrections = (await db.execute(nature_corrections_stmt)).scalar() or 0

        nature_confirms_stmt = (
            select(func.count(Feedback.id))
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "confirmation",
                Feedback.field_name == "nature",
            )
        )
        nature_confirmations = (await db.execute(nature_confirms_stmt)).scalar() or 0

        nature_metrics = _compute_metrics(nature_corrections, nature_confirmations)

        # category 필드별 메트릭
        cat_corrections_stmt = (
            select(func.count(Feedback.id))
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "correction",
                Feedback.field_name == "domain_category_ids",
            )
        )
        cat_corrections = (await db.execute(cat_corrections_stmt)).scalar() or 0

        cat_confirms_stmt = (
            select(func.count(Feedback.id))
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "confirmation",
                Feedback.field_name == "domain_category_ids",
            )
        )
        cat_confirmations = (await db.execute(cat_confirms_stmt)).scalar() or 0

        category_metrics = _compute_metrics(cat_corrections, cat_confirmations)

        # 신뢰도 calibration (Block.classification_provenance.confidence 기준)
        confidence_calibration: list[ConfidenceBucket] = []
        if Block is not None:
            confidence_calibration = await _compute_confidence_calibration(
                db, Feedback, Block, since
            )

        return ApiResponse(
            data=ClassificationQualityData(
                period_days=days,
                total_feedback=total_feedback,
                total_corrections=total_corrections,
                total_confirmations=total_confirmations,
                nature=nature_metrics,
                category=category_metrics,
                confidence_calibration=confidence_calibration,
            )
        )

    except Exception as exc:
        logger.warning("classification_quality_query_failed", error=str(exc))
        return ApiResponse(data=ClassificationQualityData(period_days=days))


async def _compute_confidence_calibration(
    db: AsyncSession,
    Feedback: type,
    Block: type,
    since: datetime,
) -> list[ConfidenceBucket]:
    """신뢰도 구간별 실제 정확도를 계산한다."""
    buckets: list[ConfidenceBucket] = []

    # 신뢰도 구간 정의
    bucket_ranges = [
        ("0.0-0.2", 0.0, 0.2),
        ("0.2-0.4", 0.2, 0.4),
        ("0.4-0.6", 0.4, 0.6),
        ("0.6-0.8", 0.6, 0.8),
        ("0.8-0.9", 0.8, 0.9),
        ("0.9-1.0", 0.9, 1.0),
    ]

    try:
        for bucket_name, low, high in bucket_ranges:
            # 해당 신뢰도 구간의 블럭 중 피드백이 있는 블럭
            # Block.classification_provenance -> {"confidence": 0.95, ...}
            # 피드백이 correction이면 오답, confirmation이면 정답

            # 수정된 블럭 수 (해당 구간)
            corrections_stmt = (
                select(func.count(func.distinct(Feedback.block_id)))
                .join(Block, Feedback.block_id == Block.id)
                .where(
                    Feedback.created_at >= since,
                    Feedback.feedback_type == "correction",
                    Block.classification_provenance.isnot(None),
                )
            )

            # 확인된 블럭 수 (해당 구간)
            confirmations_stmt = (
                select(func.count(func.distinct(Feedback.block_id)))
                .join(Block, Feedback.block_id == Block.id)
                .where(
                    Feedback.created_at >= since,
                    Feedback.feedback_type == "confirmation",
                    Block.classification_provenance.isnot(None),
                )
            )

            # confidence 필터 — JSONB에서 추출
            # classification_provenance->'confidence' 가 [low, high) 범위
            from sqlalchemy import Float, text
            from sqlalchemy.sql.expression import literal_column

            conf_expr = Block.classification_provenance["confidence"].as_float()

            corr_count = (
                await db.execute(
                    corrections_stmt.where(conf_expr >= low, conf_expr < high)
                )
            ).scalar() or 0

            conf_count = (
                await db.execute(
                    confirmations_stmt.where(conf_expr >= low, conf_expr < high)
                )
            ).scalar() or 0

            total = corr_count + conf_count
            if total == 0:
                continue

            actual_accuracy = conf_count / total
            predicted_confidence = (low + high) / 2

            buckets.append(
                ConfidenceBucket(
                    bucket=bucket_name,
                    predicted_confidence=round(predicted_confidence, 2),
                    actual_accuracy=round(actual_accuracy, 4),
                    sample_count=total,
                )
            )

    except Exception as exc:
        logger.debug("confidence_calibration_failed", error=str(exc))

    return buckets


# ---------------------------------------------------------------------------
# 2. GET /quality/classification/by-block-type — 블럭 타입별
# ---------------------------------------------------------------------------


@router.get(
    "/classification/by-block-type",
    response_model=ApiResponse[BlockTypeQualityData],
    summary="블럭 타입별 분류 품질",
    dependencies=[Depends(require_role(UserRole.platform_admin))],
)
async def get_quality_by_block_type(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[BlockTypeQualityData]:
    """블럭 타입(paragraph, heading, table 등)별 분류 품질을 반환한다."""
    Feedback = _get_feedback_model()
    Block = _get_block_model()
    if Feedback is None or Block is None:
        return ApiResponse(data=BlockTypeQualityData(period_days=days))

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # 블럭 타입별 correction/confirmation 집계
        type_agg_stmt = (
            select(
                Block.block_type,
                Feedback.feedback_type,
                Feedback.field_name,
                func.count(Feedback.id).label("cnt"),
            )
            .join(Block, Feedback.block_id == Block.id)
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type.in_(["correction", "confirmation"]),
            )
            .group_by(Block.block_type, Feedback.feedback_type, Feedback.field_name)
        )
        result = await db.execute(type_agg_stmt)
        rows = result.all()

        # 블럭 타입별 집계
        type_data: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "nature_corrections": 0,
                "nature_confirmations": 0,
                "cat_corrections": 0,
                "cat_confirmations": 0,
                "total_corrections": 0,
            }
        )

        for row in rows:
            block_type = row.block_type
            feedback_type = row.feedback_type
            field_name = row.field_name
            cnt = row.cnt

            if feedback_type == "correction":
                type_data[block_type]["total_corrections"] += cnt
                if field_name == "nature":
                    type_data[block_type]["nature_corrections"] += cnt
                elif field_name == "domain_category_ids":
                    type_data[block_type]["cat_corrections"] += cnt
            elif feedback_type == "confirmation":
                if field_name == "nature":
                    type_data[block_type]["nature_confirmations"] += cnt
                elif field_name == "domain_category_ids":
                    type_data[block_type]["cat_confirmations"] += cnt

        # 평균 신뢰도 조회
        avg_conf_stmt = (
            select(
                Block.block_type,
                func.avg(
                    Block.classification_provenance["confidence"].as_float()
                ).label("avg_conf"),
            )
            .where(
                Block.classification_provenance.isnot(None),
                Block.created_at >= since,
            )
            .group_by(Block.block_type)
        )
        conf_result = await db.execute(avg_conf_stmt)
        avg_conf_map: dict[str, float] = {}
        for row in conf_result.all():
            avg_conf_map[row.block_type] = float(row.avg_conf or 0)

        items: list[BlockTypeQualityItem] = []
        for bt, data in sorted(type_data.items(), key=lambda x: x[1]["total_corrections"], reverse=True):
            nature_total = data["nature_corrections"] + data["nature_confirmations"]
            cat_total = data["cat_corrections"] + data["cat_confirmations"]

            nature_acc = (
                data["nature_confirmations"] / nature_total if nature_total > 0 else 0.0
            )
            cat_acc = (
                data["cat_confirmations"] / cat_total if cat_total > 0 else 0.0
            )

            items.append(
                BlockTypeQualityItem(
                    block_type=bt,
                    total_corrections=data["total_corrections"],
                    nature_accuracy=round(nature_acc, 4),
                    category_accuracy=round(cat_acc, 4),
                    avg_confidence=round(avg_conf_map.get(bt, 0.0), 4),
                )
            )

        return ApiResponse(data=BlockTypeQualityData(period_days=days, block_types=items))

    except Exception as exc:
        logger.warning("quality_by_block_type_failed", error=str(exc))
        return ApiResponse(data=BlockTypeQualityData(period_days=days))


# ---------------------------------------------------------------------------
# 3. GET /quality/classification/confusion-matrix — nature 혼동 행렬
# ---------------------------------------------------------------------------


@router.get(
    "/classification/confusion-matrix",
    response_model=ApiResponse[ConfusionMatrixData],
    summary="nature 분류 혼동 행렬",
    dependencies=[Depends(require_role(UserRole.platform_admin))],
)
async def get_confusion_matrix(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ConfusionMatrixData]:
    """nature 필드의 혼동 행렬을 반환한다.

    old_value(LLM 예측) vs new_value(사용자 정정)를 기반으로
    confusion matrix를 생성한다.
    """
    Feedback = _get_feedback_model()
    if Feedback is None:
        return ApiResponse(data=ConfusionMatrixData(period_days=days))

    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        # nature 수정 피드백: old_value(predicted) -> new_value(actual)
        stmt = (
            select(
                Feedback.old_value,
                Feedback.new_value,
                func.count(Feedback.id).label("cnt"),
            )
            .where(
                Feedback.created_at >= since,
                Feedback.feedback_type == "correction",
                Feedback.field_name == "nature",
            )
            .group_by(Feedback.old_value, Feedback.new_value)
            .order_by(func.count(Feedback.id).desc())
        )
        result = await db.execute(stmt)
        rows = result.all()

        if not rows:
            return ApiResponse(data=ConfusionMatrixData(period_days=days))

        # 라벨 수집 + 혼동 행렬 구성
        labels_set: set[str] = set()
        cells: list[ConfusionCell] = []
        total_samples = 0

        for row in rows:
            predicted = _safe_extract_value(row.old_value)
            actual = _safe_extract_value(row.new_value)
            count = row.cnt

            if not predicted or not actual:
                continue

            labels_set.add(predicted)
            labels_set.add(actual)
            cells.append(
                ConfusionCell(
                    actual=actual,
                    predicted=predicted,
                    count=count,
                )
            )
            total_samples += count

        labels = sorted(labels_set)

        return ApiResponse(
            data=ConfusionMatrixData(
                period_days=days,
                labels=labels,
                matrix=cells,
                total_samples=total_samples,
            )
        )

    except Exception as exc:
        logger.warning("confusion_matrix_query_failed", error=str(exc))
        return ApiResponse(data=ConfusionMatrixData(period_days=days))
