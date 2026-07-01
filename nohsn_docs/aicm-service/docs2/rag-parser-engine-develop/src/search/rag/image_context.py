"""ImageContextHandler -- 이미지 추출 청크를 검색 및 RAG 컨텍스트에 적절히 포맷.

이미지에서 OCR 또는 Vision으로 추출된 청크는 metadata.is_image = true 를 가진다.

Knowledge Search(사람용):
- "이미지 추출" 배지 태깅
- 원본 페이지/위치 링크 제공

RAG Retrieval(LLM용):
- "[이미지 설명] ..." 접두사를 붙여 LLM이 출처 유형을 인지하도록 함
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.common.logging import get_logger
from src.search.models import SearchHit, SourceLocation

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_RAG_IMAGE_PREFIX = "[이미지 설명]"
_KNOWLEDGE_SEARCH_BADGE = "\U0001f4f7 이미지 추출"  # 📷 이미지 추출


# ---------------------------------------------------------------------------
# Knowledge Search 결과 모델
# ---------------------------------------------------------------------------

class ImageSearchAnnotation(BaseModel):
    """Knowledge Search에서 이미지 청크에 추가되는 어노테이션."""

    badge: str = Field(default=_KNOWLEDGE_SEARCH_BADGE, description="UI 배지 텍스트")
    source_page: int | None = Field(None, description="원본 이미지가 위치한 페이지")
    source_bbox: list[float] | None = Field(
        None, description="원본 이미지 바운딩박스 [x0, y0, x1, y1]"
    )
    file_url: str | None = Field(None, description="원본 파일 URL")
    image_type: str | None = Field(None, description="이미지 타입 (chart, diagram, photo 등)")


# ---------------------------------------------------------------------------
# ImageContextHandler
# ---------------------------------------------------------------------------

class ImageContextHandler:
    """이미지 추출 청크를 RAG 컨텍스트에 적절히 포맷.

    - Knowledge Search: 배지 + 위치 정보 어노테이션 추가
    - RAG Retrieval: 콘텐츠에 "[이미지 설명]" 접두사 추가
    """

    @staticmethod
    def is_image_chunk(chunk: SearchHit) -> bool:
        """청크가 이미지 추출 청크인지 확인.

        Parameters
        ----------
        chunk : SearchHit
            검색 결과 청크

        Returns
        -------
        bool
            이미지 청크 여부
        """
        return bool(chunk.metadata.get("is_image", False))

    def format_for_rag(self, chunk: SearchHit) -> str:
        """RAG 컨텍스트용으로 이미지 청크 콘텐츠를 포맷.

        이미지 청크이면 "[이미지 설명] ..." 접두사를 추가하여
        LLM이 해당 컨텍스트가 이미지에서 추출된 것임을 인지하도록 한다.

        Parameters
        ----------
        chunk : SearchHit
            검색 결과 청크

        Returns
        -------
        str
            포맷된 콘텐츠 문자열
        """
        if not self.is_image_chunk(chunk):
            return chunk.content

        image_type = chunk.metadata.get("image_type", "")
        page_info = ""
        if chunk.source_location.page_number is not None:
            page_info = f" (p.{chunk.source_location.page_number})"

        type_info = ""
        if image_type:
            type_info = f" ({image_type})"

        return f"{_RAG_IMAGE_PREFIX}{type_info}{page_info} {chunk.content}"

    def annotate_for_knowledge_search(self, chunk: SearchHit) -> ImageSearchAnnotation | None:
        """Knowledge Search용 이미지 청크 어노테이션 생성.

        UI에서 이미지 청크를 구분하여 표시하기 위한 메타데이터를 생성한다.

        Parameters
        ----------
        chunk : SearchHit
            검색 결과 청크

        Returns
        -------
        ImageSearchAnnotation | None
            이미지 청크이면 어노테이션 반환, 아니면 None
        """
        if not self.is_image_chunk(chunk):
            return None

        return ImageSearchAnnotation(
            badge=_KNOWLEDGE_SEARCH_BADGE,
            source_page=chunk.source_location.page_number,
            source_bbox=chunk.source_location.bbox,
            file_url=chunk.source_location.file_url,
            image_type=chunk.metadata.get("image_type"),
        )

    def format_chunks_for_rag(self, chunks: list[SearchHit]) -> list[str]:
        """여러 청크를 RAG 컨텍스트용으로 일괄 포맷.

        이미지 청크와 일반 청크를 구분하여 적절한 포맷을 적용한다.

        Parameters
        ----------
        chunks : list[SearchHit]
            검색 결과 청크 리스트

        Returns
        -------
        list[str]
            포맷된 콘텐츠 문자열 리스트
        """
        formatted: list[str] = []
        image_count = 0

        for chunk in chunks:
            content = self.format_for_rag(chunk)
            formatted.append(content)
            if self.is_image_chunk(chunk):
                image_count += 1

        if image_count > 0:
            log.info(
                "image_chunks_formatted_for_rag",
                total_chunks=len(chunks),
                image_chunks=image_count,
            )

        return formatted

    def annotate_search_results(
        self, chunks: list[SearchHit]
    ) -> list[tuple[SearchHit, ImageSearchAnnotation | None]]:
        """Knowledge Search 결과에 이미지 어노테이션을 일괄 부여.

        Parameters
        ----------
        chunks : list[SearchHit]
            검색 결과 청크 리스트

        Returns
        -------
        list[tuple[SearchHit, ImageSearchAnnotation | None]]
            (청크, 어노테이션) 튜플 리스트
        """
        results: list[tuple[SearchHit, ImageSearchAnnotation | None]] = []
        for chunk in chunks:
            annotation = self.annotate_for_knowledge_search(chunk)
            results.append((chunk, annotation))
        return results
