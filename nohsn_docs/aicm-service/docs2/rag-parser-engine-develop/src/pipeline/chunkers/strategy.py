"""청킹 전략 선택기 -- 난이도 + 콘텐츠 유형에 따라 최적 전략 결정.

specs/02 4.4 구현. Phase 2 에서 TableChunker + HierarchicalChunker 연동.
"""

from __future__ import annotations

from src.common.logging import get_logger
from src.pipeline.chunkers.base import BaseChunker
from src.pipeline.chunkers.hierarchical import HierarchicalChunker
from src.pipeline.chunkers.semantic import SemanticChunker
from src.pipeline.chunkers.table_chunker import TableChunker
from src.pipeline.models.document import (
    ChunkStrategy,
    DocumentObject,
    ProcessingConfig,
    ProcessingDifficulty,
)

log = get_logger(__name__)


class ChunkStrategySelector:
    """난이도 + 콘텐츠 유형에 따라 최적 청킹 전략 조합을 결정한다."""

    def select(
        self,
        doc: DocumentObject,
    ) -> list[tuple[BaseChunker | TableChunker, str]]:
        """문서 객체를 분석하여 (chunker, target_type) 쌍 목록을 반환한다.

        target_type 은 ``"text"`` 또는 ``"table"`` 이다.
        """
        config = doc.config
        strategies: list[tuple[BaseChunker | TableChunker, str]] = []

        # 본문 텍스트 전략
        if doc.difficulty in (ProcessingDifficulty.LOW, ProcessingDifficulty.MEDIUM):
            strategies.append((SemanticChunker(config), "text"))
        else:
            # HIGH / CRITICAL -> HierarchicalChunker 사용
            strategies.append((HierarchicalChunker(config), "text"))

        # 표가 있으면 표 전용 3중 청커 추가
        if doc.tables:
            strategies.append((TableChunker(config), "table"))
            log.info(
                "table_chunking_strategy",
                table_count=len(doc.tables),
                strategy="table_3layer",
            )

        log.info(
            "chunk_strategy_selected",
            difficulty=doc.difficulty.value if doc.difficulty else "unknown",
            strategies=[(type(c).__name__, t) for c, t in strategies],
        )
        return strategies
