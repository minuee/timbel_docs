"""TXT 파서 -- 일반 텍스트 파일 파싱 (인코딩 자동 감지 + 테이블 패턴 탐지).

전략
-----
1. 인코딩 감지: utf-8 → cp949/euc-kr → chardet fallback
2. 이중 개행(\n\n) 기준 단락 분리
3. 탭/파이프 구분 패턴이 감지되면 TableContent 로 변환
4. 단일 가상 페이지 (DOCX 파서와 동일)
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

from src.common.logging import get_logger
from src.pipeline.models.parse_result import (
    PageContent,
    ParseResult,
    TableContent,
    TextBlock,
)
from src.pipeline.parsers.base import BaseParser

log = get_logger(__name__)

# 테이블 패턴: 2줄 이상, 각 줄에 탭 또는 파이프 구분자가 있는 블록
_PIPE_LINE_RE = re.compile(r"^\|?.+\|.+\|?$")
_TAB_LINE_RE = re.compile(r"^[^\t]+\t[^\t]+")


class TXTParser(BaseParser):
    """일반 텍스트(.txt) 파서."""

    async def parse(self) -> ParseResult:
        """텍스트 파일을 파싱하여 구조화된 결과를 반환한다."""
        return await asyncio.to_thread(self._parse_sync)

    # ------------------------------------------------------------------
    # 동기 내부
    # ------------------------------------------------------------------
    def _parse_sync(self) -> ParseResult:
        raw_bytes = self._read_bytes()
        text, encoding = self._decode(raw_bytes)
        file_size = len(raw_bytes)
        line_count = text.count("\n") + (1 if text else 0)

        # 단락 분리 (이중 개행)
        paragraphs = self._split_paragraphs(text)

        text_blocks: list[TextBlock] = []
        tables: list[TableContent] = []
        plain_texts: list[str] = []
        running_offset = 0
        table_index = 0

        for para_idx, para in enumerate(paragraphs):
            # 테이블 패턴 감지
            table = self._try_parse_table(para, table_index)
            if table is not None:
                tables.append(table)
                table_index += 1

            tb = TextBlock(
                text=para,
                start_char_offset=running_offset,
                end_char_offset=running_offset + len(para),
                paragraph_index=para_idx,
            )
            text_blocks.append(tb)
            plain_texts.append(para)
            running_offset += len(para) + 2  # +2 for \n\n separator

        full_text = "\n\n".join(plain_texts)

        page = PageContent(
            page_number=1,
            text=full_text,
            text_blocks=text_blocks,
            tables=tables,
            layout_type="single",
        )

        metadata = {
            "file_size": file_size,
            "detected_encoding": encoding,
            "line_count": line_count,
        }

        log.info(
            "txt_parse_complete",
            path=self.file_path,
            encoding=encoding,
            paragraphs=len(paragraphs),
            tables=len(tables),
            line_count=line_count,
        )

        return ParseResult(
            raw_text=full_text,
            pages=[page],
            tables=tables,
            images=[],
            metadata=metadata,
            source_file_path=self.file_path,
        )

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------
    def _read_bytes(self) -> bytes:
        """파일을 바이너리로 읽는다."""
        with open(self.file_path, "rb") as f:
            return f.read()

    @staticmethod
    def _decode(raw: bytes) -> tuple[str, str]:
        """바이트를 텍스트로 디코딩한다. 인코딩 자동 감지."""
        # 1) UTF-8 (BOM 포함)
        for enc in ("utf-8-sig", "utf-8"):
            try:
                return raw.decode(enc), enc
            except (UnicodeDecodeError, ValueError):
                continue

        # 2) 한국어 인코딩
        for enc in ("cp949", "euc-kr"):
            try:
                return raw.decode(enc), enc
            except (UnicodeDecodeError, ValueError):
                continue

        # 3) chardet fallback
        try:
            import chardet

            detected = chardet.detect(raw)
            enc = detected.get("encoding") or "utf-8"
            return raw.decode(enc, errors="replace"), enc
        except ImportError:
            log.warning("chardet_not_installed", fallback="utf-8 with replace")
            return raw.decode("utf-8", errors="replace"), "utf-8(fallback)"

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """이중 개행 기준으로 단락을 분리한다. 빈 단락은 제거."""
        # \r\n 정규화
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        parts = re.split(r"\n{2,}", normalized)
        return [p.strip() for p in parts if p.strip()]

    def _try_parse_table(self, paragraph: str, table_index: int) -> Optional[TableContent]:
        """단락이 테이블 패턴이면 TableContent 를 반환한다."""
        lines = paragraph.strip().split("\n")
        if len(lines) < 2:
            return None

        # 파이프 구분 테이블
        if all(_PIPE_LINE_RE.match(line.strip()) for line in lines):
            return self._parse_pipe_table(lines, table_index)

        # 탭 구분 테이블
        if all(_TAB_LINE_RE.match(line) for line in lines):
            return self._parse_tab_table(lines, table_index)

        return None

    def _parse_pipe_table(self, lines: list[str], table_index: int) -> TableContent:
        """파이프 구분 테이블을 파싱한다."""
        parsed_rows: list[list[str]] = []
        for line in lines:
            stripped = line.strip().strip("|")
            cells = [c.strip() for c in stripped.split("|")]
            # markdown 구분선(---) 스킵
            if all(re.match(r"^-+$", c) or c == "" for c in cells):
                continue
            parsed_rows.append(cells)

        if not parsed_rows:
            return TableContent(
                page_number=1, table_index=table_index, headers=[], rows=[]
            )

        headers = parsed_rows[0]
        rows = parsed_rows[1:]
        md = self._table_to_markdown(headers, rows)
        return TableContent(
            page_number=1,
            table_index=table_index,
            headers=headers,
            rows=rows,
            markdown=md,
            confidence=0.7,
        )

    def _parse_tab_table(self, lines: list[str], table_index: int) -> TableContent:
        """탭 구분 테이블을 파싱한다."""
        parsed_rows = [line.split("\t") for line in lines]
        headers = [c.strip() for c in parsed_rows[0]]
        rows = [[c.strip() for c in row] for row in parsed_rows[1:]]
        md = self._table_to_markdown(headers, rows)
        return TableContent(
            page_number=1,
            table_index=table_index,
            headers=headers,
            rows=rows,
            markdown=md,
            confidence=0.7,
        )

    @staticmethod
    def _table_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
        """헤더/행을 마크다운 테이블로 변환한다."""
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            padded = row + [""] * max(0, len(headers) - len(row))
            lines.append("| " + " | ".join(padded[: len(headers)]) + " |")
        return "\n".join(lines)
