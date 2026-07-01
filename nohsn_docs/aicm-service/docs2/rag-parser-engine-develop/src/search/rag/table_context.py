"""TableAwareContextBuilder -- 표 청크 검색 시 멀티 레이어 컨텍스트 확장."""

from __future__ import annotations

from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    FieldCondition,
    Filter,
    MatchValue,
)

from src.common.config import settings
from src.common.logging import get_logger
from src.search.models import SearchHit, SourceLocation

log = get_logger(__name__)

# 표 관련 레이어 식별자
TABLE_LAYERS: frozenset[str] = frozenset({"row_nl", "table_markdown", "table_summary"})

# 보강 우선순위 (낮은 숫자가 높은 우선순위)
_LAYER_PRIORITY: dict[str, int] = {
    "table_summary": 0,
    "table_markdown": 1,
    "row_nl": 2,
}


def _count_tokens(text: str) -> int:
    """간이 토큰 수 추정 (한국어 기준 ~3.5자/토큰, 영문 ~4자/토큰)."""
    if not text:
        return 0
    korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    total_chars = len(text)
    if total_chars == 0:
        return 0
    korean_ratio = korean_chars / total_chars
    avg_chars_per_token = 3.5 * korean_ratio + 4.0 * (1 - korean_ratio)
    return max(1, int(total_chars / avg_chars_per_token))


def is_table_chunk(hit: SearchHit) -> bool:
    """SearchHit이 표 청크인지 확인."""
    layer = hit.metadata.get("layer", "")
    return layer in TABLE_LAYERS


def _extract_table_key(hit: SearchHit) -> tuple[UUID, int] | None:
    """표 청크에서 (document_id, table_index) 키를 추출."""
    table_index = hit.source_location.table_index
    if table_index is None:
        table_index = hit.metadata.get("table_index")
    if table_index is None:
        return None
    return (hit.document_id, int(table_index))


class TableAwareContextBuilder:
    """
    검색 결과에 표 청크가 포함되면, 해당 표의 다른 레이어 청크를 자동으로 함께 가져온다.

    예: "M10x50 볼트 단가?" 질의로 Row NL 청크가 검색되면,
        같은 표의 Markdown 청크 + Summary 청크를 보강 컨텍스트로 추가.
        -> LLM이 개별 셀 + 주변 행 + 표 전체 맥락을 모두 참고하여 답변.
    """

    def __init__(self, qdrant_client: AsyncQdrantClient | None = None) -> None:
        self._qdrant_client = qdrant_client

    async def _get_client(self) -> AsyncQdrantClient:
        """지연 초기화된 Qdrant 클라이언트 반환."""
        if self._qdrant_client is None:
            self._qdrant_client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
                prefer_grpc=True,
            )
        return self._qdrant_client

    async def enrich_table_context(
        self,
        hits: list[SearchHit],
        collection_name: str,
        max_context_tokens: int = 2000,
    ) -> list[SearchHit]:
        """
        표 청크가 포함된 검색 결과를 보강.

        Args:
            hits: 원본 검색 결과
            collection_name: Qdrant 컬렉션 이름
            max_context_tokens: 최대 토큰 예산

        Returns:
            보강된 SearchHit 리스트 (원본 + 형제 청크)
        """
        enriched: list[SearchHit] = list(hits)
        token_budget = max_context_tokens

        # 기존 hits 토큰 소비량 계산
        for hit in hits:
            token_budget -= _count_tokens(hit.content)

        if token_budget <= 0:
            log.info("table_context_no_budget", remaining_tokens=token_budget)
            return enriched

        # 이미 포함된 chunk_id 집합 (중복 방지)
        seen_chunk_ids: set[str] = {str(h.chunk_id) for h in hits}

        # 표별로 형제 청크 fetch
        fetched_tables: set[tuple[UUID, int]] = set()

        for hit in hits:
            if not is_table_chunk(hit):
                continue

            table_key = _extract_table_key(hit)
            if table_key is None or table_key in fetched_tables:
                continue
            fetched_tables.add(table_key)

            document_id, table_index = table_key
            siblings = await self._fetch_table_siblings(
                collection_name=collection_name,
                document_id=document_id,
                table_index=table_index,
                exclude_chunk_ids=seen_chunk_ids,
            )

            # 우선순위별 정렬 후 토큰 예산 내에서 추가
            prioritized = self._prioritize(siblings, hit)
            for sibling in prioritized:
                tokens = _count_tokens(sibling.content)
                if token_budget - tokens < 0:
                    break
                enriched.append(sibling)
                seen_chunk_ids.add(str(sibling.chunk_id))
                token_budget -= tokens

            log.info(
                "table_context_enriched",
                document_id=str(document_id),
                table_index=table_index,
                siblings_added=len(enriched) - len(hits),
                remaining_tokens=token_budget,
            )

        return enriched

    async def _fetch_table_siblings(
        self,
        collection_name: str,
        document_id: UUID,
        table_index: int,
        exclude_chunk_ids: set[str] | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        """같은 표의 형제 청크를 Qdrant payload 필터로 조회."""
        try:
            client = await self._get_client()

            # document_id + table_index 필터
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(document_id)),
                    ),
                    FieldCondition(
                        key="source_location.table_index",
                        match=MatchValue(value=table_index),
                    ),
                ]
            )

            # scroll 로 청크 조회 (벡터 검색 아님)
            points, _next_page = await client.scroll(
                collection_name=collection_name,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )

            siblings: list[SearchHit] = []
            exclude = exclude_chunk_ids or set()

            for point in points:
                chunk_id_str = str(point.id)
                if chunk_id_str in exclude:
                    continue

                payload = point.payload or {}
                layer = payload.get("metadata", {}).get("layer", "")
                if layer not in TABLE_LAYERS:
                    continue

                hit = self._point_to_hit(point)
                siblings.append(hit)

            return siblings

        except Exception:
            log.exception(
                "table_siblings_fetch_failed",
                collection=collection_name,
                document_id=str(document_id),
                table_index=table_index,
            )
            return []

    @staticmethod
    def _prioritize(siblings: list[SearchHit], original_hit: SearchHit) -> list[SearchHit]:
        """
        보강 우선순위 결정.

        1. Summary 청크 (표 전체 맥락)
        2. 원본 hit 주변 행의 Markdown 그룹 (인접 비교)
        3. 나머지 Row NL (조건부 필터링 지원)
        """
        def sort_key(s: SearchHit) -> tuple[int, int]:
            layer = s.metadata.get("layer", "")
            priority = _LAYER_PRIORITY.get(layer, 99)
            # Markdown 그룹은 원본 hit의 paragraph_index에 가까운 순
            paragraph_idx = s.source_location.paragraph_index or 0
            original_idx = original_hit.source_location.paragraph_index or 0
            distance = abs(paragraph_idx - original_idx)
            return (priority, distance)

        return sorted(siblings, key=sort_key)

    @staticmethod
    def _point_to_hit(point: object) -> SearchHit:
        """Qdrant point를 SearchHit으로 변환."""
        payload = point.payload or {}
        source_loc_data = payload.get("source_location", {})

        page_range = source_loc_data.get("page_range")
        if page_range and isinstance(page_range, (list, tuple)) and len(page_range) == 2:
            page_range = list(page_range)
        else:
            page_range = None

        bbox = source_loc_data.get("bbox")
        if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bbox = list(bbox)
        else:
            bbox = None

        return SearchHit(
            chunk_id=UUID(str(point.id)) if not isinstance(point.id, UUID) else point.id,
            document_id=UUID(
                payload.get("document_id", "00000000-0000-0000-0000-000000000000")
            ),
            document_title=payload.get("document_title", ""),
            section_title=payload.get("section_title"),
            content=payload.get("content", ""),
            document_type=payload.get("document_type"),
            category_names=payload.get("category_names", []),
            metadata=payload.get("metadata", {}),
            source_location=SourceLocation(
                file_path=source_loc_data.get("file_path", ""),
                file_url=source_loc_data.get("file_url"),
                page_number=source_loc_data.get("page_number"),
                page_range=page_range,
                start_char_offset=source_loc_data.get("start_char_offset"),
                end_char_offset=source_loc_data.get("end_char_offset"),
                bbox=bbox,
                heading_path=source_loc_data.get("heading_path", []),
                sheet_name=source_loc_data.get("sheet_name"),
                table_index=source_loc_data.get("table_index"),
                paragraph_index=source_loc_data.get("paragraph_index"),
            ),
        )
