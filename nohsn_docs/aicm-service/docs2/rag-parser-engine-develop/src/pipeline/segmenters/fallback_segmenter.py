"""FallbackSegmenter — LLM 없이 KSS + 개행 기반 휴리스틱으로 블럭을 분할한다.

LLM 호출 불가 시, 저난이도 문서, 또는 비용 절감 모드에서 사용한다.
"""

from __future__ import annotations

import hashlib
import re
from uuid import UUID, uuid4

from src.common.logging import get_logger
from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import ProcessingConfig, SourceLocation
from src.pipeline.models.parse_result import ImageContent, PageContent, ParseResult, TableContent
from src.pipeline.segmenters.base import BaseSegmenter

log = get_logger(__name__)


class FallbackSegmenter(BaseSegmenter):
    """KSS 문장 분리 + 더블 개행 기반 단락 분할 세그멘터.

    알고리즘
    --------
    1. 각 페이지의 텍스트를 더블 개행(``\\n\\n``)으로 1차 분할
    2. 1차 분할 결과가 없으면 KSS 문장 분리 후 일정 문장 수로 그루핑
    3. 표 → TableBlock, 이미지 → ImageBlock 으로 1:1 매핑
    4. 모든 블럭을 페이지 순서대로 block_index 부여
    """

    def __init__(self, config: ProcessingConfig) -> None:
        super().__init__(config)
        self._sentences_per_block = 5  # KSS 폴백 시 문장 그루핑 단위

    @staticmethod
    def _detect_block_type(content: str, heading_level: int | None = None) -> BlockType:
        """블럭 콘텐츠를 분석하여 노션 블럭 타입을 휴리스틱으로 판별한다."""
        stripped = content.strip()

        # 1. 헤딩 (parser가 감지한 heading_level 우선)
        if heading_level is not None:
            if heading_level == 1:
                return BlockType.HEADING_1
            if heading_level == 2:
                return BlockType.HEADING_2
            return BlockType.HEADING_3

        # 2. 구분선
        if stripped in ("---", "***", "===", "────") or set(stripped) <= {"-", "*", "=", "─", " "}:
            if len(stripped) >= 3:
                return BlockType.DIVIDER

        # 3. 코드 블럭 (``` 으로 시작)
        if stripped.startswith("```") or stripped.startswith("~~~"):
            return BlockType.CODE

        # 4. 인용 (> 으로 시작하는 줄이 대다수)
        lines = stripped.split("\n")
        if lines and sum(1 for l in lines if l.strip().startswith(">")) > len(lines) * 0.5:
            return BlockType.QUOTE

        # 5. 콜아웃 (특정 패턴)
        callout_patterns = ["주의:", "참고:", "Note:", "Warning:", "⚠", "📌", "💡", "ℹ"]
        if any(stripped.startswith(p) for p in callout_patterns):
            return BlockType.CALLOUT

        # 6. 체크리스트
        if stripped.startswith(("[ ]", "[x]", "[X]", "☐", "☑")):
            return BlockType.TO_DO

        # 7. 번호 리스트 (대다수 줄이 숫자/가나다로 시작)
        numbered_patterns = re.compile(r"^(\d+[\.\)]\s|[가-힣][\.\)]\s|\(\d+\)\s)")
        if lines and sum(1 for l in lines if numbered_patterns.match(l.strip())) > len(lines) * 0.5:
            return BlockType.NUMBERED_LIST

        # 8. 불릿 리스트 (대다수 줄이 -, •, · 등으로 시작)
        bullet_patterns = re.compile(r"^[-•·▪▸►◦]\s")
        if lines and sum(1 for l in lines if bullet_patterns.match(l.strip())) > len(lines) * 0.5:
            return BlockType.BULLETED_LIST

        # 9. 기본: 단락
        return BlockType.PARAGRAPH

    @staticmethod
    def _find_heading_level(
        text: str,
        page: PageContent,
        headings: list[dict],
    ) -> int | None:
        """텍스트가 parser가 감지한 heading에 해당하는지 확인한다.

        TextBlock.heading_level 을 우선 사용하고, 없으면 ParseResult metadata의
        headings 목록에서 텍스트 매칭으로 판별한다.
        """
        stripped = text.strip()

        # 1. TextBlock 에서 heading_level 확인 (가장 정확)
        for tb in page.text_blocks:
            if tb.heading_level is not None and tb.text.strip() == stripped:
                return tb.heading_level

        # 2. metadata headings 에서 텍스트 매칭
        for h in headings:
            h_text = h.get("text", "").strip()
            if h_text and (h_text == stripped or stripped.startswith(h_text)):
                return h.get("level", 3)

        return None

    async def segment(
        self,
        parse_result: ParseResult,
        *,
        document_id: UUID,
        source_file_url: str = "",
    ) -> list[BlockObject]:
        """ParseResult → 블럭 목록."""
        blocks: list[BlockObject] = []

        headings: list[dict] = parse_result.metadata.get("headings", [])

        for page in parse_result.pages:
            # 텍스트 블럭
            text_blocks = self._segment_page_text(
                page, document_id, parse_result.source_file_path, headings, source_file_url
            )
            blocks.extend(text_blocks)

            # 표 블럭
            for table in page.tables:
                blocks.append(self._table_to_block(table, document_id, parse_result.source_file_path, source_file_url))

            # 이미지 블럭
            for image in page.images:
                blocks.append(self._image_to_block(image, document_id, parse_result.source_file_path, source_file_url))

        # block_index 재정렬
        for i, block in enumerate(blocks):
            block.block_index = i

        log.info(
            "fallback_segmentation_complete",
            document_id=str(document_id),
            block_count=len(blocks),
            text_blocks=sum(1 for b in blocks if b.block_type == BlockType.PARAGRAPH),
            table_blocks=sum(1 for b in blocks if b.block_type == BlockType.TABLE),
            image_blocks=sum(1 for b in blocks if b.block_type == BlockType.IMAGE),
        )
        return blocks

    def _segment_page_text(
        self,
        page: PageContent,
        document_id: UUID,
        source_file_path: str,
        headings: list[dict] | None = None,
        source_file_url: str = "",
    ) -> list[BlockObject]:
        """페이지 텍스트를 단락 단위 블럭으로 분할한다."""
        text = page.text.strip()
        if not text:
            return []

        headings = headings or []

        # 1차: 더블 개행으로 분할
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        # 더블 개행이 없으면 KSS 문장 분리 폴백
        if len(paragraphs) <= 1 and len(text) > self.block_max_tokens:
            paragraphs = self._kss_group(text)

        blocks: list[BlockObject] = []
        for para in paragraphs:
            if not para:
                continue

            # block_max_tokens 초과 시 강제 분할
            sub_parts = self._split_oversized(para)
            for part in sub_parts:
                sl = self._find_source_location(part, page, source_file_path, source_file_url)
                heading_level = self._find_heading_level(part, page, headings)
                block_type = self._detect_block_type(part, heading_level)
                block = BlockObject(
                    id=uuid4(),
                    document_id=document_id,
                    block_type=block_type,
                    content=part,
                    block_index=0,  # 나중에 재정렬
                    token_count=len(part),
                    source_location=sl,
                )
                block.compute_hash()
                blocks.append(block)

        return blocks

    def _kss_group(self, text: str) -> list[str]:
        """KSS 로 문장 분리 후 N 문장씩 그루핑한다."""
        try:
            import kss

            sentences = kss.split_sentences(text)
        except ImportError:
            log.warning("kss_not_installed_using_newline_split")
            sentences = [line.strip() for line in text.split("\n") if line.strip()]

        groups: list[str] = []
        buf: list[str] = []
        for sent in sentences:
            buf.append(sent)
            if len(buf) >= self._sentences_per_block:
                groups.append("\n".join(buf))
                buf = []
        if buf:
            groups.append("\n".join(buf))

        return groups

    def _split_oversized(self, text: str) -> list[str]:
        """block_max_tokens 초과 시 강제 분할."""
        if len(text) <= self.block_max_tokens:
            return [text]

        parts: list[str] = []
        while len(text) > self.block_max_tokens:
            cut = self.block_max_tokens
            for sep in ("\n\n", "\n", ". ", ", ", " "):
                pos = text.rfind(sep, 0, cut)
                if pos > 100:
                    cut = pos + len(sep)
                    break
            parts.append(text[:cut].strip())
            text = text[cut:]

        if text.strip():
            parts.append(text.strip())

        return parts

    @staticmethod
    def _find_source_location(
        text: str,
        page: PageContent,
        source_file_path: str,
        source_file_url: str = "",
    ) -> SourceLocation:
        """텍스트에 가장 근접한 TextBlock 의 위치 정보를 상속한다."""
        best_block = None
        best_overlap = 0

        for tb in page.text_blocks:
            overlap = len(set(text[:200]) & set(tb.text[:200]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_block = tb

        if best_block:
            return SourceLocation(
                file_path=source_file_path,
                file_url=source_file_url or None,
                page_number=page.page_number,
                start_char_offset=best_block.start_char_offset,
                end_char_offset=best_block.end_char_offset,
                bbox=best_block.bbox,
                paragraph_index=best_block.paragraph_index,
            )

        return SourceLocation(
            file_path=source_file_path,
            file_url=source_file_url or None,
            page_number=page.page_number,
        )

    @staticmethod
    def _table_to_block(
        table: TableContent,
        document_id: UUID,
        source_file_path: str,
        source_file_url: str = "",
    ) -> BlockObject:
        """TableContent → TableBlock."""
        content = table.markdown or _table_to_markdown(table)
        block = BlockObject(
            id=uuid4(),
            document_id=document_id,
            block_type=BlockType.TABLE,
            content=content,
            block_index=0,
            token_count=len(content),
            source_location=SourceLocation(
                file_path=source_file_path,
                page_number=table.page_number,
                table_index=table.table_index,
                bbox=table.bbox,
                file_url=source_file_url or None,
            ),
            metadata={"confidence": table.confidence},
            table_headers=table.headers,
            table_rows=table.rows,
            table_markdown=content,
        )
        block.compute_hash()
        return block

    @staticmethod
    def _image_to_block(
        image: ImageContent,
        document_id: UUID,
        source_file_path: str,
        source_file_url: str = "",
    ) -> BlockObject:
        """ImageContent → ImageBlock."""
        content = image.description or image.ocr_text or f"[이미지: 페이지 {image.page_number}]"
        block = BlockObject(
            id=uuid4(),
            document_id=document_id,
            block_type=BlockType.IMAGE,
            content=content,
            block_index=0,
            token_count=len(content),
            source_location=SourceLocation(
                file_path=source_file_path,
                page_number=image.page_number,
                bbox=image.bbox,
                file_url=source_file_url or None,
            ),
            image_path=image.image_path,
            ocr_text=image.ocr_text,
            image_description=image.description,
        )
        block.compute_hash()
        return block


def _table_to_markdown(table: TableContent) -> str:
    """TableContent 를 마크다운 표 문자열로 변환한다."""
    if not table.headers and not table.rows:
        return ""

    lines: list[str] = []
    if table.headers:
        lines.append("| " + " | ".join(table.headers) + " |")
        lines.append("| " + " | ".join("---" for _ in table.headers) + " |")

    for row in table.rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")

    return "\n".join(lines)
