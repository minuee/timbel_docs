"""Table 3-Layer Chunker -- 행 NL / Markdown 그룹 / LLM 요약 3중 청킹.

Phase 2 Task B-3. 가장 복잡한 신규 기능.

Layer 1 (Row NL):
    각 행을 "[표제목] 헤더1 값1, 헤더2 값2, ..." 자연어 문장으로 변환.
    개별 셀 조회 검색 히트율 극대화.

Layer 2 (Markdown Group):
    헤더 + N행 단위 Markdown 표 그룹.
    인접 행 비교, 범위 조회에 최적화.

Layer 3 (Summary):
    LLM이 표 전체를 1-2문장으로 요약.
    집계/전체 맥락 질의에 최적화.
"""

from __future__ import annotations

import hashlib
from typing import Optional
from uuid import UUID, uuid4

from src.common.logging import get_logger
from src.pipeline.models.document import (
    ChunkObject,
    ChunkStrategy,
    ProcessingConfig,
    SourceLocation,
    TableChunkConfig,
)
from src.pipeline.models.parse_result import TableContent

log = get_logger(__name__)


class TableChunker:
    """표 3중 레이어 청커.

    BaseChunker를 상속하지 않고 독립 인터페이스를 사용한다.
    표는 PageContent 가 아닌 TableContent 단위로 처리하기 때문이다.
    """

    def __init__(self, config: ProcessingConfig) -> None:
        self.config = config
        self.table_config: TableChunkConfig = config.table_chunk

    async def chunk(
        self,
        table: TableContent,
        *,
        document_id: str = "",
        source_file_path: str = "",
        table_title: str = "",
    ) -> list[ChunkObject]:
        """단일 표를 3중 레이어로 청킹한다.

        Parameters
        ----------
        table : TableContent
            파서가 추출한 표 콘텐츠
        document_id : str
            문서 UUID 문자열
        source_file_path : str
            원본 파일 경로
        table_title : str
            표 제목 (있는 경우)

        Returns
        -------
        list[ChunkObject]
            3개 레이어의 청크 목록
        """
        doc_uuid = UUID(document_id) if document_id else uuid4()
        chunks: list[ChunkObject] = []

        base_location = SourceLocation(
            file_path=source_file_path,
            page_number=table.page_number,
            table_index=table.table_index,
            bbox=table.bbox,
        )

        # Layer 1: Row NL
        if self.table_config.row_nl_enabled and table.rows:
            row_chunks = self._build_row_nl_chunks(
                table, doc_uuid, base_location, table_title
            )
            chunks.extend(row_chunks)

        # Layer 2: Markdown Group
        md_chunks = self._build_markdown_chunks(
            table, doc_uuid, base_location, table_title
        )
        chunks.extend(md_chunks)

        # Layer 3: Summary (LLM)
        if self.table_config.summary_enabled:
            summary_chunk = await self._build_summary_chunk(
                table, doc_uuid, base_location, table_title
            )
            if summary_chunk:
                chunks.append(summary_chunk)

        # chunk_index 재정렬
        for i, c in enumerate(chunks):
            c.chunk_index = i

        log.info(
            "table_chunking_complete",
            table_index=table.table_index,
            page=table.page_number,
            rows=len(table.rows),
            total_chunks=len(chunks),
            layer_counts={
                "row_nl": sum(1 for c in chunks if c.metadata.get("layer") == "row_nl"),
                "table_markdown": sum(
                    1 for c in chunks if c.metadata.get("layer") == "table_markdown"
                ),
                "table_summary": sum(
                    1 for c in chunks if c.metadata.get("layer") == "table_summary"
                ),
            },
        )

        return chunks

    # ------------------------------------------------------------------
    # Layer 1: Row NL
    # ------------------------------------------------------------------
    def _build_row_nl_chunks(
        self,
        table: TableContent,
        document_id: UUID,
        base_location: SourceLocation,
        table_title: str,
    ) -> list[ChunkObject]:
        """각 행(또는 행 그룹)을 자연어 문장으로 변환하여 청크를 생성한다."""
        chunks: list[ChunkObject] = []
        headers = table.headers
        rows = table.rows

        if not headers or not rows:
            return chunks

        # 대형 표 자동 그룹 크기 조정
        group_size = self.table_config.row_nl_group_size
        if len(rows) > self.table_config.max_rows_for_row_nl:
            group_size = max(group_size, 5)
            log.info(
                "table_row_nl_group_size_adjusted",
                original=self.table_config.row_nl_group_size,
                adjusted=group_size,
                row_count=len(rows),
            )

        title_prefix = f"[{table_title}] " if table_title else ""

        for group_start in range(0, len(rows), group_size):
            group_end = min(group_start + group_size, len(rows))
            group_rows = rows[group_start:group_end]

            sentences: list[str] = []
            for row in group_rows:
                parts: list[str] = []
                for h_idx, header in enumerate(headers):
                    value = row[h_idx] if h_idx < len(row) else ""
                    if value.strip():
                        parts.append(f"{header} {value}")
                if parts:
                    sentence = f"{title_prefix}{', '.join(parts)}."
                    sentences.append(sentence)

            if not sentences:
                continue

            text = "\n".join(sentences)
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            sl = base_location.model_copy()
            sl.heading_path = [table_title] if table_title else []

            chunks.append(
                ChunkObject(
                    id=uuid4(),
                    document_id=document_id,
                    content=text,
                    chunk_index=0,
                    chunk_hash=chunk_hash,
                    token_count=len(text),
                    strategy=ChunkStrategy.TABLE,
                    source_location=sl,
                    metadata={
                        "layer": "row_nl",
                        "table_index": table.table_index,
                        "page_number": table.page_number,
                        "row_range": [group_start, group_end - 1],
                    },
                )
            )

        return chunks

    # ------------------------------------------------------------------
    # Layer 2: Markdown Group
    # ------------------------------------------------------------------
    def _build_markdown_chunks(
        self,
        table: TableContent,
        document_id: UUID,
        base_location: SourceLocation,
        table_title: str,
    ) -> list[ChunkObject]:
        """헤더 + N행 단위 Markdown 표 그룹 청크를 생성한다."""
        chunks: list[ChunkObject] = []
        headers = table.headers
        rows = table.rows
        rows_per_chunk = self.table_config.markdown_rows_per_chunk

        if not headers:
            return chunks

        # 헤더 Markdown
        header_line = "| " + " | ".join(headers) + " |"
        separator_line = "| " + " | ".join("---" for _ in headers) + " |"

        for group_start in range(0, max(len(rows), 1), rows_per_chunk):
            group_end = min(group_start + rows_per_chunk, len(rows))
            group_rows = rows[group_start:group_end]

            lines = [header_line, separator_line]
            for row in group_rows:
                padded = row + [""] * max(0, len(headers) - len(row))
                lines.append("| " + " | ".join(padded[: len(headers)]) + " |")

            title_line = f"## {table_title}\n\n" if table_title else ""
            text = title_line + "\n".join(lines)
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            sl = base_location.model_copy()
            sl.heading_path = [table_title] if table_title else []

            chunks.append(
                ChunkObject(
                    id=uuid4(),
                    document_id=document_id,
                    content=text,
                    chunk_index=0,
                    chunk_hash=chunk_hash,
                    token_count=len(text),
                    strategy=ChunkStrategy.TABLE,
                    source_location=sl,
                    metadata={
                        "layer": "table_markdown",
                        "table_index": table.table_index,
                        "page_number": table.page_number,
                        "row_range": [group_start, group_end - 1],
                    },
                )
            )

        return chunks

    # ------------------------------------------------------------------
    # Layer 3: Summary (LLM)
    # ------------------------------------------------------------------
    async def _build_summary_chunk(
        self,
        table: TableContent,
        document_id: UUID,
        base_location: SourceLocation,
        table_title: str,
    ) -> Optional[ChunkObject]:
        """LLM을 사용하여 표 전체 요약 청크를 생성한다."""
        try:
            summary_text = await self._generate_summary(table, table_title)
        except Exception as exc:
            log.warning(
                "table_summary_generation_failed",
                table_index=table.table_index,
                error=str(exc),
            )
            # 폴백: 통계 기반 간단 요약
            summary_text = self._fallback_summary(table, table_title)

        if not summary_text:
            return None

        chunk_hash = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()

        sl = base_location.model_copy()
        sl.heading_path = [table_title] if table_title else []

        return ChunkObject(
            id=uuid4(),
            document_id=document_id,
            content=summary_text,
            chunk_index=0,
            chunk_hash=chunk_hash,
            token_count=len(summary_text),
            strategy=ChunkStrategy.TABLE,
            source_location=sl,
            metadata={
                "layer": "table_summary",
                "table_index": table.table_index,
                "page_number": table.page_number,
                "row_count": len(table.rows),
                "col_count": len(table.headers),
            },
        )

    async def _generate_summary(self, table: TableContent, table_title: str) -> str:
        """LLM (Qwen) 으로 표 요약을 생성한다."""
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        # 표 크기가 너무 크면 앞부분만 사용
        max_rows_for_prompt = 50
        display_rows = table.rows[:max_rows_for_prompt]
        truncated = len(table.rows) > max_rows_for_prompt

        # Markdown 표 구성
        header_line = "| " + " | ".join(table.headers) + " |"
        sep_line = "| " + " | ".join("---" for _ in table.headers) + " |"
        row_lines = []
        for row in display_rows:
            padded = row + [""] * max(0, len(table.headers) - len(row))
            row_lines.append("| " + " | ".join(padded[: len(table.headers)]) + " |")

        table_md = "\n".join([header_line, sep_line] + row_lines)
        if truncated:
            table_md += f"\n... (총 {len(table.rows)}행 중 {max_rows_for_prompt}행만 표시)"

        title_info = f"표 제목: {table_title}\n" if table_title else ""

        prompt = (
            f"{title_info}"
            f"열: {', '.join(table.headers)}\n"
            f"행 수: {len(table.rows)}\n\n"
            f"{table_md}\n\n"
            "위 표를 1-2문장으로 요약하세요. "
            "표의 목적, 주요 데이터 범위, 핵심 특징을 포함하세요."
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt="당신은 표 데이터를 분석하고 간결하게 요약하는 전문가입니다.",
            max_tokens=300,
            temperature=0.2,
        )

        response = await llm_router.route(
            task=LLMTask.TABLE_SUMMARY,
            request=request,
        )

        return response.text.strip()

    @staticmethod
    def _fallback_summary(table: TableContent, table_title: str) -> str:
        """LLM 없이 통계 기반 간단 요약을 생성한다."""
        title_part = f"'{table_title}' 표는" if table_title else "이 표는"
        col_names = ", ".join(table.headers[:5])
        if len(table.headers) > 5:
            col_names += f" 등 {len(table.headers)}개 열"

        return (
            f"{title_part} {len(table.rows)}개 행과 {len(table.headers)}개 열({col_names})로 "
            f"구성되어 있습니다."
        )
