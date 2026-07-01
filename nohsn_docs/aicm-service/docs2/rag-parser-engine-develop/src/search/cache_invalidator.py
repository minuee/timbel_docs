"""검색 캐시 무효화 헬퍼.

저장소 데이터가 변경될 때 (문서/블럭 추가·수정·삭제·재인덱스) 호출하여
해당 저장소의 모든 검색 캐시를 자연 무효화한다.

내부적으로 SearchCache.bump_repo_version 한 번 호출 = Redis INCR 한 번. O(1).
"""

from __future__ import annotations

from uuid import UUID

from src.common.logging import get_logger
from src.search.cache import SearchCache

log = get_logger(__name__)


async def invalidate_repository_cache(repository_id: UUID | str) -> None:
    """저장소의 검색 캐시를 무효화한다 (실패해도 본 작업 흐름은 깨지지 않음)."""
    try:
        repo_uuid = repository_id if isinstance(repository_id, UUID) else UUID(str(repository_id))
        await SearchCache().bump_repo_version(repo_uuid)
    except Exception:
        log.warning("invalidate_repository_cache_failed", repository_id=str(repository_id), exc_info=True)
