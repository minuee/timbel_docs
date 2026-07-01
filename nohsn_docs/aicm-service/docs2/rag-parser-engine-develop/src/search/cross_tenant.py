"""Cross-Tenant 검색 지원 — TenantLink 기반 교차 테넌트 검색."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.models.tenant import Tenant
from src.core.models.tenant_link import TenantLink
from src.search.models import SearchHit, SearchRequest

log = get_logger(__name__)


async def get_active_link(
    db: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
) -> TenantLink | None:
    """활성 상태인 TenantLink를 조회한다.

    Args:
        db: DB 세션
        user_id: 현재 사용자 ID
        tenant_id: 현재 검색 중인 테넌트 ID

    Returns:
        활성 TenantLink 또는 None
    """
    stmt = select(TenantLink).where(
        TenantLink.user_id == user_id,
        TenantLink.status == "active",
        TenantLink.user_consent.is_(True),
        TenantLink.corporate_consent.is_(True),
        (
            (TenantLink.personal_tenant_id == tenant_id)
            | (TenantLink.corporate_tenant_id == tenant_id)
        ),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def get_other_tenant_id(link: TenantLink, current_tenant_id: UUID) -> UUID:
    """링크에서 상대방 테넌트 ID를 반환한다."""
    if link.personal_tenant_id == current_tenant_id:
        return link.corporate_tenant_id
    return link.personal_tenant_id


async def get_tenant_slug(db: AsyncSession, tenant_id: UUID) -> str | None:
    """테넌트 ID로 slug를 조회한다."""
    stmt = select(Tenant.slug).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def apply_link_config(
    request: SearchRequest,
    link_config: dict,
    other_tenant_id: UUID,
) -> SearchRequest:
    """link_config 제한 사항을 검색 요청에 적용한다.

    link_config 예시:
    {
        "allowed_natures": ["fact", "schedule"],
        "blocked_domains": ["personal/health"],
        "max_results": 5
    }

    Args:
        request: 원본 검색 요청
        link_config: 링크 설정
        other_tenant_id: 상대방 테넌트 ID

    Returns:
        제한이 적용된 새 SearchRequest
    """
    # 복사본 생성 (원본 변경 방지)
    cross_request = request.model_copy(
        update={
            "tenant_id": other_tenant_id,
            "repository_ids": None,  # 상대방 테넌트의 전체 저장소 검색
            "repository_id": None,
        }
    )

    # nature 필터 적용
    allowed_natures = link_config.get("allowed_natures")
    if allowed_natures:
        cross_request.nature_filter = allowed_natures

    # 최대 결과 수 제한
    max_results = link_config.get("max_results")
    if max_results:
        cross_request.top_k = min(cross_request.top_k, max_results)

    return cross_request


def tag_cross_tenant_hits(
    hits: list[SearchHit],
    source_tenant_id: UUID,
    source_type: str,
) -> list[SearchHit]:
    """교차 검색 결과에 소스 태그를 추가한다.

    Args:
        hits: 검색 결과 목록
        source_tenant_id: 결과가 나온 테넌트 ID
        source_type: 'personal' 또는 'corporate'

    Returns:
        태그가 추가된 검색 결과
    """
    for hit in hits:
        hit.metadata["source_tenant"] = source_type
        hit.metadata["source_tenant_id"] = str(source_tenant_id)
        hit.metadata["cross_tenant"] = True
    return hits


def merge_results(
    primary_hits: list[SearchHit],
    cross_hits: list[SearchHit],
    max_cross_ratio: float = 0.4,
) -> list[SearchHit]:
    """주 검색 결과와 교차 검색 결과를 병합한다.

    교차 결과가 전체의 max_cross_ratio를 초과하지 않도록 제한.
    스코어 기준 정렬.

    Args:
        primary_hits: 주 테넌트 검색 결과
        cross_hits: 교차 테넌트 검색 결과
        max_cross_ratio: 교차 결과 최대 비율 (기본 40%)

    Returns:
        병합된 검색 결과 (스코어 내림차순)
    """
    total_target = len(primary_hits) + len(cross_hits)
    max_cross = max(1, int(total_target * max_cross_ratio))

    # 교차 결과를 스코어순 정렬 후 제한
    sorted_cross = sorted(cross_hits, key=lambda h: h.score, reverse=True)[:max_cross]

    # 병합 후 전체 스코어순 정렬
    merged = primary_hits + sorted_cross
    merged.sort(key=lambda h: h.score, reverse=True)

    return merged
