"""설정 해석(Config Resolution) 서비스.

테넌트 config -> 저장소 config -> 개별 오버라이드 순으로 설정을 병합한다.
깊은 딕셔너리 병합을 지원하며, 하위 레벨 설정이 상위를 오버라이드한다.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field

from src.common.logging import get_logger

logger = get_logger(__name__)


class PipelineConfig(BaseModel):
    """파이프라인 처리 설정."""

    chunk_size: int = Field(default=400, description="청크 크기 (토큰)")
    chunk_overlap: int = Field(default=50, description="청크 오버랩 (토큰)")
    ocr_enabled: bool = Field(default=True, description="OCR 활성화 여부")
    contextual_retrieval: bool = Field(
        default=False, description="컨텍스트 검색 활성화 여부"
    )


class SearchConfig(BaseModel):
    """검색 설정."""

    default_top_k: int = Field(default=5, description="기본 검색 결과 수")
    rerank_enabled: bool = Field(default=True, description="리랭킹 활성화 여부")
    dense_weight: float = Field(default=0.6, description="Dense 벡터 가중치")
    sparse_weight: float = Field(default=0.4, description="Sparse 벡터 가중치")


class LLMTaskRouting(BaseModel):
    """LLM 태스크별 라우팅 설정."""

    rag_generation: str = Field(default="claude")
    vision_ocr: str = Field(default="claude")
    metadata_extraction: str = Field(default="claude")
    contextual_retrieval: str = Field(default="claude")
    table_summary: str = Field(default="qwen")
    batch_processing: str = Field(default="qwen")


class LLMConfig(BaseModel):
    """LLM 라우팅 설정."""

    routing_mode: str = Field(default="vllm", description="라우팅 모드 (vllm)")
    vllm_model: str = Field(default="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit")
    task_routing: LLMTaskRouting = Field(default_factory=LLMTaskRouting)


class LimitsConfig(BaseModel):
    """리소스 제한 설정."""

    max_documents: int = Field(default=1000, description="최대 문서 수")
    max_repositories: int = Field(default=3, description="최대 저장소 수")
    search_rate_limit: int = Field(default=100, description="검색 API 초당 제한")


class ProcessingConfig(BaseModel):
    """최종 병합된 처리 설정. 모든 설정 계층을 통합."""

    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)


# -----------------------------------------------------------------------
# 기본 설정 (시스템 레벨 디폴트)
# -----------------------------------------------------------------------

SYSTEM_DEFAULT_CONFIG: dict[str, Any] = ProcessingConfig().model_dump()


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """두 딕셔너리를 깊은 병합한다. override가 base를 덮어쓴다.

    Args:
        base: 기본 설정 딕셔너리
        override: 오버라이드 설정 딕셔너리

    Returns:
        병합된 딕셔너리 (새 객체)
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve_config(
    *,
    tenant_config: dict[str, Any] | None = None,
    repo_config: dict[str, Any] | None = None,
    override: dict[str, Any] | None = None,
) -> ProcessingConfig:
    """설정을 계층적으로 병합하여 최종 ProcessingConfig를 반환한다.

    병합 순서: 시스템 기본값 < 테넌트 설정 < 저장소 설정 < 개별 오버라이드

    Args:
        tenant_config: 테넌트 레벨 설정 (JSONB)
        repo_config: 저장소 레벨 설정 (JSONB)
        override: 개별 오버라이드 (요청 레벨)

    Returns:
        최종 병합된 ProcessingConfig 객체
    """
    merged = copy.deepcopy(SYSTEM_DEFAULT_CONFIG)

    if tenant_config:
        merged = deep_merge(merged, tenant_config)

    if repo_config:
        merged = deep_merge(merged, repo_config)

    if override:
        merged = deep_merge(merged, override)

    logger.debug(
        "config_resolved",
        has_tenant_config=tenant_config is not None,
        has_repo_config=repo_config is not None,
        has_override=override is not None,
    )

    return ProcessingConfig.model_validate(merged)


async def resolve_config_for_repository(
    *,
    tenant_config: dict[str, Any],
    repo_config: dict[str, Any],
) -> ProcessingConfig:
    """테넌트 + 저장소 설정을 병합하여 저장소의 유효 설정을 반환한다.

    Args:
        tenant_config: 테넌트의 config JSONB
        repo_config: 저장소의 config JSONB

    Returns:
        최종 ProcessingConfig 객체
    """
    return resolve_config(
        tenant_config=tenant_config,
        repo_config=repo_config,
    )
