"""Markdown 파서 -- 원시 마크다운 직접 파싱 (라이브러리 미사용).

헤딩 구조, 테이블, 이미지 참조, 프론트매터, 코드 블록을 구조적으로 추출한다.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from src.common.logging import get_logger
from src.pipeline.models.parse_result import (
    ImageContent,
    PageContent,
    ParseResult,
    TableContent,
    TextBlock,
)
from src.pipeline.parsers.base import BaseParser

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 정규식 패턴
# ---------------------------------------------------------------------------
_RE_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_RE_FENCED_CODE = re.compile(r"^(`{3,}|~{3,}).*$", re.MULTILINE)
_RE_TABLE_ROW = re.compile(r"^\|(.+)\|$")
_RE_TABLE_SEPARATOR = re.compile(r"^\|[\s:-]+(\|[\s:-]+)*\|$")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# 인코딩 탐색 순서
_ENCODINGS = ("utf-8", "utf-8-sig", "cp949", "euc-kr", "latin-1")


class MarkdownParser(BaseParser):
    """원시 마크다운 파일 파서.

    알고리즘
    --------
    1. 파일 읽기 (인코딩 폴백)
    2. 프론트매터(YAML) 추출 → metadata
    3. 코드 블록 영역 식별 (내부 콘텐츠는 파싱 대상에서 제외)
    4. 헤딩 기반으로 섹션 분리 → 각 섹션을 TextBlock 으로
    5. 테이블 추출 → TableContent
    6. 이미지 참조 추출 → ImageContent
    7. 단일 가상 페이지로 PageContent 구성
    """

    async def parse(self) -> ParseResult:
        """비동기 마크다운 파싱."""
        return await asyncio.to_thread(self._parse_sync)

    # ------------------------------------------------------------------
    # 동기 내부 구현
    # ------------------------------------------------------------------
    def _parse_sync(self) -> ParseResult:
        raw_text = self._read_file()
        if not raw_text:
            log.warning("markdown_empty_file", path=self.file_path)
            return ParseResult(source_file_path=self.file_path)

        metadata: dict = {}

        # 1) 프론트매터 추출
        body, front_matter_meta = self._extract_front_matter(raw_text)
        if front_matter_meta:
            metadata["front_matter"] = front_matter_meta

        # 2) 코드 블록 영역 식별
        code_ranges = self._find_code_block_ranges(body)

        # 3) 헤딩 구조 파악
        headings = self._extract_headings(body, code_ranges)
        if headings:
            metadata["heading_structure"] = [
                {"level": level, "title": title} for level, title, _ in headings
            ]

        # 4) 섹션 분리 → TextBlock
        sections = self._split_into_sections(body, headings)
        text_blocks: list[TextBlock] = []
        for idx, (section_text, start_offset, end_offset) in enumerate(sections):
            if not section_text.strip():
                continue
            text_blocks.append(
                TextBlock(
                    text=section_text,
                    start_char_offset=start_offset,
                    end_char_offset=end_offset,
                    paragraph_index=idx,
                )
            )

        # 5) 테이블 추출
        tables = self._extract_tables(body, code_ranges)

        # 6) 이미지 참조 추출
        images = self._extract_images(body, code_ranges)

        # 7) 페이지 조립
        page = PageContent(
            page_number=1,
            text=body,
            text_blocks=text_blocks,
            tables=tables,
            images=images,
            layout_type="single",
        )

        metadata["format"] = "markdown"

        return ParseResult(
            raw_text=raw_text,
            pages=[page],
            tables=tables,
            images=images,
            metadata=metadata,
            source_file_path=self.file_path,
        )

    # ------------------------------------------------------------------
    # 파일 읽기 (인코딩 폴백)
    # ------------------------------------------------------------------
    def _read_file(self) -> str:
        """UTF-8 우선, 실패 시 다른 인코딩으로 폴백한다."""
        for encoding in _ENCODINGS:
            try:
                with open(self.file_path, "r", encoding=encoding) as f:
                    content = f.read()
                log.debug("markdown_file_read", path=self.file_path, encoding=encoding)
                return content
            except (UnicodeDecodeError, UnicodeError):
                continue
            except OSError as exc:
                log.error("markdown_file_read_error", path=self.file_path, error=str(exc))
                return ""

        log.error("markdown_encoding_failed", path=self.file_path)
        return ""

    # ------------------------------------------------------------------
    # 프론트매터 추출
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_front_matter(text: str) -> tuple[str, Optional[dict]]:
        """YAML 프론트매터를 추출하여 본문과 분리한다.

        Returns:
            (본문 텍스트, 프론트매터 딕셔너리 또는 None)
        """
        match = _RE_FRONT_MATTER.match(text)
        if not match:
            return text, None

        yaml_str = match.group(1)
        body = text[match.end() :]

        # 간단한 YAML key: value 파싱 (외부 라이브러리 없이)
        meta: dict[str, str] = {}
        for line in yaml_str.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key:
                    meta[key] = value

        return body, meta if meta else None

    # ------------------------------------------------------------------
    # 코드 블록 영역 식별
    # ------------------------------------------------------------------
    @staticmethod
    def _find_code_block_ranges(text: str) -> list[tuple[int, int]]:
        """펜스드 코드 블록(``` 또는 ~~~)의 (start, end) 오프셋 목록을 반환한다."""
        ranges: list[tuple[int, int]] = []
        fence_stack: Optional[tuple[str, int]] = None

        for m in _RE_FENCED_CODE.finditer(text):
            fence_char = m.group(1)[0]  # ` 또는 ~
            fence_len = len(m.group(1))

            if fence_stack is None:
                # 코드 블록 시작
                fence_stack = (fence_char * fence_len, m.start())
            else:
                # 같은 종류·같은 길이 이상의 펜스면 닫기
                opening_fence = fence_stack[0]
                if fence_char == opening_fence[0] and fence_len >= len(opening_fence):
                    ranges.append((fence_stack[1], m.end()))
                    fence_stack = None

        # 닫히지 않은 코드 블록은 파일 끝까지
        if fence_stack is not None:
            ranges.append((fence_stack[1], len(text)))

        return ranges

    @staticmethod
    def _is_in_code_block(pos: int, code_ranges: list[tuple[int, int]]) -> bool:
        """주어진 위치가 코드 블록 내부인지 확인한다."""
        for start, end in code_ranges:
            if start <= pos < end:
                return True
        return False

    # ------------------------------------------------------------------
    # 헤딩 추출
    # ------------------------------------------------------------------
    def _extract_headings(
        self,
        text: str,
        code_ranges: list[tuple[int, int]],
    ) -> list[tuple[int, str, int]]:
        """헤딩을 추출한다. 코드 블록 내부는 무시.

        Returns:
            [(level, title, char_offset), ...]
        """
        headings: list[tuple[int, str, int]] = []
        for m in _RE_HEADING.finditer(text):
            if self._is_in_code_block(m.start(), code_ranges):
                continue
            level = len(m.group(1))
            title = m.group(2).strip()
            headings.append((level, title, m.start()))
        return headings

    # ------------------------------------------------------------------
    # 섹션 분리
    # ------------------------------------------------------------------
    @staticmethod
    def _split_into_sections(
        text: str,
        headings: list[tuple[int, str, int]],
    ) -> list[tuple[str, int, int]]:
        """헤딩을 기준으로 텍스트를 섹션으로 분리한다.

        Returns:
            [(section_text, start_offset, end_offset), ...]
        """
        if not headings:
            # 헤딩이 없으면 전체를 하나의 섹션으로
            return [(text, 0, len(text))]

        sections: list[tuple[str, int, int]] = []

        # 첫 헤딩 이전 텍스트
        first_offset = headings[0][2]
        if first_offset > 0:
            preamble = text[:first_offset]
            if preamble.strip():
                sections.append((preamble, 0, first_offset))

        # 각 헤딩 구간
        for i, (_, _, offset) in enumerate(headings):
            if i + 1 < len(headings):
                next_offset = headings[i + 1][2]
            else:
                next_offset = len(text)
            section_text = text[offset:next_offset]
            sections.append((section_text, offset, next_offset))

        return sections

    # ------------------------------------------------------------------
    # 테이블 추출
    # ------------------------------------------------------------------
    def _extract_tables(
        self,
        text: str,
        code_ranges: list[tuple[int, int]],
    ) -> list[TableContent]:
        """마크다운 테이블(| ... |)을 추출한다."""
        tables: list[TableContent] = []
        lines = text.split("\n")
        table_index = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # 코드 블록 내부 스킵
            line_offset = self._line_offset(text, i, lines)
            if self._is_in_code_block(line_offset, code_ranges):
                i += 1
                continue

            # 테이블 행인지 확인
            if not _RE_TABLE_ROW.match(line.strip()):
                i += 1
                continue

            # 연속된 테이블 행 수집
            table_lines: list[str] = []
            start_line = i
            while i < len(lines):
                stripped = lines[i].strip()
                if _RE_TABLE_ROW.match(stripped):
                    table_lines.append(stripped)
                    i += 1
                else:
                    break

            # 최소 2행 (헤더 + 구분선) 필요
            if len(table_lines) < 2:
                continue

            parsed = self._parse_table_block(table_lines, table_index)
            if parsed is not None:
                tables.append(parsed)
                table_index += 1

        return tables

    @staticmethod
    def _line_offset(text: str, line_idx: int, lines: list[str]) -> int:
        """특정 라인의 텍스트 내 시작 오프셋을 계산한다."""
        offset = 0
        for j in range(line_idx):
            offset += len(lines[j]) + 1  # +1 for newline
        return offset

    @staticmethod
    def _parse_table_block(
        table_lines: list[str],
        table_index: int,
    ) -> Optional[TableContent]:
        """테이블 행 목록을 파싱하여 TableContent 를 반환한다."""

        def split_cells(line: str) -> list[str]:
            """파이프로 구분된 셀을 분리한다."""
            # 양쪽 | 제거 후 분리
            inner = line.strip("|")
            return [cell.strip() for cell in inner.split("|")]

        if len(table_lines) < 2:
            return None

        # 두 번째 행이 구분선(---) 패턴인지 확인
        sep_cells = split_cells(table_lines[1])
        is_separator = all(
            re.match(r"^:?-{1,}:?$", cell.strip()) for cell in sep_cells if cell.strip()
        )

        if not is_separator:
            # 구분선이 없으면 유효한 마크다운 테이블이 아님
            return None

        headers = split_cells(table_lines[0])
        rows: list[list[str]] = []
        for line in table_lines[2:]:
            rows.append(split_cells(line))

        markdown = "\n".join(table_lines)

        return TableContent(
            page_number=1,
            table_index=table_index,
            headers=headers,
            rows=rows,
            markdown=markdown,
            confidence=1.0,
        )

    # ------------------------------------------------------------------
    # 이미지 참조 추출
    # ------------------------------------------------------------------
    def _extract_images(
        self,
        text: str,
        code_ranges: list[tuple[int, int]],
    ) -> list[ImageContent]:
        """![alt](path) 패턴의 이미지 참조를 추출한다."""
        images: list[ImageContent] = []
        for idx, m in enumerate(_RE_IMAGE.finditer(text)):
            if self._is_in_code_block(m.start(), code_ranges):
                continue
            alt_text = m.group(1)
            image_path = m.group(2)
            images.append(
                ImageContent(
                    page_number=1,
                    image_index=idx,
                    image_path=image_path,
                    description=alt_text or None,
                )
            )
        return images
