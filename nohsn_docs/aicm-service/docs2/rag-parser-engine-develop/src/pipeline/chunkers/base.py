"""BaseChunker ABC -- 모든 청커의 기본 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.pipeline.models.document import ChunkObject, ProcessingConfig
from src.pipeline.models.parse_result import PageContent


class BaseChunker(ABC):
    """청커 추상 기반 클래스."""

    def __init__(self, config: ProcessingConfig) -> None:
        self.max_tokens = config.chunk_size
        self.min_tokens = config.min_chunk_size
        self.overlap = config.chunk_overlap

    @abstractmethod
    async def chunk(
        self,
        pages: list[PageContent],
        *,
        source_file_path: str = "",
        document_id: str = "",
    ) -> list[ChunkObject]:
        """페이지 목록을 청크 목록으로 분할한다.

        source_location 은 원본 TextBlock 에서 상속하여 채운다.
        """
