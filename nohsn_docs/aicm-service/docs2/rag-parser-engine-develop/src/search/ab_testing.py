"""A/B 테스팅 프레임워크 -- 검색 파라미터 실험 관리."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.common.logging import get_logger

log = get_logger(__name__)


class ABTestStatus(str, Enum):
    """A/B 테스트 상태."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class VariantConfig(BaseModel):
    """실험 변형 설정."""

    variant_id: str
    name: str
    description: str | None = None
    traffic_ratio: float = 0.5  # 0.0 ~ 1.0

    # 검색 가중치 오버라이드
    dense_weight: float | None = None
    sparse_weight: float | None = None
    keyword_weight: float | None = None

    # 리랭킹 설정 오버라이드
    rerank_enabled: bool | None = None
    rerank_model: str | None = None

    # RRF 설정 오버라이드
    rrf_k: int | None = None

    # 임계값 오버라이드
    min_score_threshold: float | None = None


class ABTestConfig(BaseModel):
    """A/B 테스트 실험 설정."""

    experiment_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str | None = None
    status: ABTestStatus = ABTestStatus.DRAFT
    tenant_id: UUID
    repository_id: UUID | None = None

    variants: list[VariantConfig] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def validate_traffic_ratios(self) -> bool:
        """변형들의 트래픽 비율 합이 1.0인지 검증."""
        total = sum(v.traffic_ratio for v in self.variants)
        return abs(total - 1.0) < 0.01


class ABTestAssignment(BaseModel):
    """사용자/요청에 대한 A/B 테스트 변형 할당."""

    experiment_id: UUID
    variant_id: str
    variant_name: str
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ABTestRouter:
    """
    A/B 테스트 트래픽 라우터.

    사용자 또는 요청 ID를 해싱하여 일관된 변형 할당을 보장한다.
    동일한 사용자는 항상 같은 변형에 할당된다 (deterministic hashing).
    """

    def assign_variant(
        self,
        experiment: ABTestConfig,
        user_id: str | UUID | None = None,
        request_id: str | UUID | None = None,
    ) -> ABTestAssignment | None:
        """
        사용자/요청을 실험 변형에 할당.

        Args:
            experiment: A/B 테스트 설정
            user_id: 사용자 ID (있으면 사용자 기반 할당)
            request_id: 요청 ID (user_id 없으면 요청 기반 할당)

        Returns:
            ABTestAssignment 또는 실험이 비활성 상태면 None
        """
        if experiment.status != ABTestStatus.ACTIVE:
            return None

        if not experiment.variants:
            log.warning(
                "ab_test_no_variants",
                experiment_id=str(experiment.experiment_id),
            )
            return None

        # 해시 기반 일관된 할당
        seed = str(user_id or request_id or uuid4())
        hash_key = f"{experiment.experiment_id}:{seed}"
        hash_value = int(hashlib.sha256(hash_key.encode()).hexdigest(), 16)
        bucket = (hash_value % 10000) / 10000.0  # 0.0 ~ 0.9999

        # 트래픽 비율에 따라 변형 선택
        cumulative = 0.0
        selected_variant = experiment.variants[-1]  # 기본: 마지막 변형

        for variant in experiment.variants:
            cumulative += variant.traffic_ratio
            if bucket < cumulative:
                selected_variant = variant
                break

        assignment = ABTestAssignment(
            experiment_id=experiment.experiment_id,
            variant_id=selected_variant.variant_id,
            variant_name=selected_variant.name,
        )

        log.debug(
            "ab_test_assigned",
            experiment_id=str(experiment.experiment_id),
            variant_id=selected_variant.variant_id,
            seed=seed[:20],
            bucket=round(bucket, 4),
        )

        return assignment

    @staticmethod
    def apply_variant_config(
        base_config: dict,
        variant: VariantConfig,
    ) -> dict:
        """
        변형 설정을 기본 검색 설정에 오버라이드 적용.

        Args:
            base_config: 기본 검색 설정 딕셔너리
            variant: 적용할 변형 설정

        Returns:
            오버라이드된 설정 딕셔너리
        """
        merged = dict(base_config)

        if variant.dense_weight is not None:
            merged["dense_weight"] = variant.dense_weight
        if variant.sparse_weight is not None:
            merged["sparse_weight"] = variant.sparse_weight
        if variant.keyword_weight is not None:
            merged["keyword_weight"] = variant.keyword_weight
        if variant.rerank_enabled is not None:
            merged["rerank_enabled"] = variant.rerank_enabled
        if variant.rerank_model is not None:
            merged["rerank_model"] = variant.rerank_model
        if variant.rrf_k is not None:
            merged["rrf_k"] = variant.rrf_k
        if variant.min_score_threshold is not None:
            merged["min_score_threshold"] = variant.min_score_threshold

        return merged


class ABTestManager:
    """
    A/B 테스트 관리자.

    인메모리 저장소로 실험을 관리한다.
    프로덕션에서는 PostgreSQL로 교체 예정.
    """

    def __init__(self) -> None:
        self._experiments: dict[UUID, ABTestConfig] = {}
        self._router = ABTestRouter()

    def create_experiment(self, config: ABTestConfig) -> ABTestConfig:
        """새 실험 생성."""
        if not config.validate_traffic_ratios():
            raise ValueError("변형 트래픽 비율의 합이 1.0이어야 합니다.")

        config.experiment_id = config.experiment_id or uuid4()
        config.created_at = datetime.now(timezone.utc)
        config.updated_at = datetime.now(timezone.utc)
        self._experiments[config.experiment_id] = config

        log.info(
            "ab_test_created",
            experiment_id=str(config.experiment_id),
            name=config.name,
            variant_count=len(config.variants),
        )
        return config

    def get_experiment(self, experiment_id: UUID) -> ABTestConfig | None:
        """실험 조회."""
        return self._experiments.get(experiment_id)

    def list_experiments(
        self,
        tenant_id: UUID,
        status: ABTestStatus | None = None,
    ) -> list[ABTestConfig]:
        """테넌트의 실험 목록 조회."""
        result = [
            exp
            for exp in self._experiments.values()
            if exp.tenant_id == tenant_id
        ]
        if status is not None:
            result = [exp for exp in result if exp.status == status]
        return sorted(result, key=lambda x: x.created_at, reverse=True)

    def activate_experiment(self, experiment_id: UUID) -> ABTestConfig | None:
        """실험 활성화."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None
        exp.status = ABTestStatus.ACTIVE
        exp.started_at = datetime.now(timezone.utc)
        exp.updated_at = datetime.now(timezone.utc)
        log.info("ab_test_activated", experiment_id=str(experiment_id))
        return exp

    def complete_experiment(self, experiment_id: UUID) -> ABTestConfig | None:
        """실험 종료."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None
        exp.status = ABTestStatus.COMPLETED
        exp.ended_at = datetime.now(timezone.utc)
        exp.updated_at = datetime.now(timezone.utc)
        log.info("ab_test_completed", experiment_id=str(experiment_id))
        return exp

    def assign_variant(
        self,
        experiment_id: UUID,
        user_id: str | UUID | None = None,
        request_id: str | UUID | None = None,
    ) -> ABTestAssignment | None:
        """실험에 변형 할당."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None
        return self._router.assign_variant(exp, user_id, request_id)

    def get_active_experiment_for_tenant(
        self,
        tenant_id: UUID,
        repository_id: UUID | None = None,
    ) -> ABTestConfig | None:
        """테넌트에 활성화된 실험 반환 (가장 최근 것)."""
        active = [
            exp
            for exp in self._experiments.values()
            if exp.tenant_id == tenant_id
            and exp.status == ABTestStatus.ACTIVE
            and (repository_id is None or exp.repository_id == repository_id)
        ]
        if not active:
            return None
        return max(active, key=lambda x: x.started_at or x.created_at)
