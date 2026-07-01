"""BaseParser ABC -- 모든 파서의 기본 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.pipeline.models.parse_result import ParseResult


class BaseParser(ABC):
    """문서 파서 추상 기반 클래스.

    각 포맷별 파서는 이 클래스를 상속하여 ``parse()`` 를 구현한다.
    파서는 순수하게 *추출*만 담당하며, 후처리(청킹/임베딩)는 별도 파이프라인이 수행한다.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    @abstractmethod
    async def parse(self) -> ParseResult:
        """문서를 파싱하여 구조화된 결과를 반환한다."""
