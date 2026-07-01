"""BaseSegmenter ABC — 모든 블럭 세그멘터의 기본 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.pipeline.models.block import BlockObject
from src.pipeline.models.document import ProcessingConfig
from src.pipeline.models.parse_result import ParseResult


class BaseSegmenter(ABC):
    """블럭 세그멘터 추상 기반 클래스."""

    def __init__(self, config: ProcessingConfig) -> None:
        self.config = config
        self.block_max_tokens = config.block_max_tokens

    @abstractmethod
    async def segment(
        self,
        parse_result: ParseResult,
        *,
        document_id: UUID,
    ) -> list[BlockObject]:
        """ParseResult 를 순서 있는 블럭 목록으로 분할한다.

        Parameters
        ----------
        parse_result : ParseResult
            파서 출력 (페이지, 표, 이미지 포함)
        document_id : UUID
            소속 문서 ID

        Returns
        -------
        list[BlockObject]
            block_index 순서로 정렬된 블럭 목록
        """
