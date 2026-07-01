"""HTML 파서 -- BeautifulSoup4 기반 구조화 추출.

전략
-----
1. 인코딩 감지: utf-8 시도 → meta charset → charset-normalizer fallback
2. BeautifulSoup4 (lxml 파서, fallback html.parser) 로 DOM 파싱
3. script/style/nav/footer/aside 등 비콘텐츠 요소 제거
4. 블록 요소별 TextBlock, 표 → TableContent, 이미지 → ImageContent 추출
5. HTML은 물리적 페이지 개념이 없으므로 단일 가상 페이지로 취급
"""

from __future__ import annotations

import asyncio
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

# 제거 대상 태그
_STRIP_TAGS = {"script", "style", "nav", "footer", "aside", "noscript", "svg", "iframe"}

# 블록 레벨 요소 (TextBlock 단위)
_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "dt", "dd", "figcaption", "address",
}

# 헤딩 태그
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class HTMLParser(BaseParser):
    """HTML 문서 파서."""

    async def parse(self) -> ParseResult:
        """HTML 파일을 파싱하여 구조화된 결과를 반환한다."""
        return await asyncio.to_thread(self._parse_sync)

    # ------------------------------------------------------------------
    # 동기 내부
    # ------------------------------------------------------------------
    def _parse_sync(self) -> ParseResult:
        from bs4 import BeautifulSoup, Tag

        raw_bytes = self._read_file_bytes()
        html_text = self._decode_html(raw_bytes)

        # lxml 파서 우선, 없으면 html.parser fallback
        soup = self._make_soup(html_text)

        # 비콘텐츠 요소 제거
        for tag_name in _STRIP_TAGS:
            for el in soup.find_all(tag_name):
                el.decompose()

        # 메타데이터 추출
        metadata = self._extract_metadata(soup)

        # 콘텐츠 추출
        text_blocks: list[TextBlock] = []
        tables: list[TableContent] = []
        images: list[ImageContent] = []
        texts: list[str] = []
        running_offset = 0
        para_idx = 0
        table_idx = 0
        image_idx = 0

        # body (또는 전체 soup) 에서 순회
        body = soup.body if soup.body else soup

        for element in body.descendants:
            if not isinstance(element, Tag):
                continue

            tag_name = element.name

            # 표 추출
            if tag_name == "table":
                tc = self._extract_table(element, table_idx)
                if tc is not None:
                    tables.append(tc)
                    table_idx += 1
                continue

            # 이미지 추출
            if tag_name == "img":
                ic = self._extract_image(element, image_idx)
                if ic is not None:
                    images.append(ic)
                    image_idx += 1
                continue

            # 블록 요소 → TextBlock
            if tag_name in _BLOCK_TAGS:
                # 자식 블록 요소가 있으면 스킵 (자식이 개별 처리됨)
                if any(
                    isinstance(child, Tag) and child.name in _BLOCK_TAGS
                    for child in element.children
                ):
                    continue

                text = element.get_text(separator=" ", strip=True)
                if not text:
                    continue

                tb = TextBlock(
                    text=text,
                    start_char_offset=running_offset,
                    end_char_offset=running_offset + len(text),
                    paragraph_index=para_idx,
                )
                text_blocks.append(tb)
                texts.append(text)

                # 헤딩 메타데이터
                if tag_name in _HEADING_TAGS:
                    level = int(tag_name[1])
                    metadata.setdefault("headings", []).append(
                        {"level": level, "text": text, "paragraph_index": para_idx}
                    )

                running_offset += len(text) + 1
                para_idx += 1

        full_text = "\n".join(texts)

        page = PageContent(
            page_number=1,
            text=full_text,
            text_blocks=text_blocks,
            tables=tables,
            images=images,
            layout_type="single",
        )

        return ParseResult(
            raw_text=full_text,
            pages=[page],
            tables=tables,
            images=images,
            metadata=metadata,
            source_file_path=self.file_path,
        )

    # ------------------------------------------------------------------
    # 인코딩 처리
    # ------------------------------------------------------------------
    def _read_file_bytes(self) -> bytes:
        """파일을 바이트로 읽는다."""
        with open(self.file_path, "rb") as f:
            return f.read()

    def _decode_html(self, raw: bytes) -> str:
        """HTML 바이트를 문자열로 디코딩한다.

        우선순위: utf-8 → meta charset 감지 → charset-normalizer fallback
        """
        # 1) UTF-8 시도
        try:
            return raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            pass

        # 2) meta charset 감지 (바이트에서 직접 검색)
        charset = self._detect_meta_charset(raw)
        if charset:
            try:
                decoded = raw.decode(charset)
                log.debug("html_decoded_by_meta_charset", charset=charset)
                return decoded
            except (UnicodeDecodeError, LookupError):
                pass

        # 3) charset-normalizer fallback
        try:
            from charset_normalizer import from_bytes

            result = from_bytes(raw).best()
            if result is not None:
                detected_enc = result.encoding
                log.debug("html_decoded_by_charset_normalizer", encoding=detected_enc)
                return str(result)
        except ImportError:
            log.warning("charset_normalizer_not_installed")

        # 최후 수단: latin-1 (무손실)
        log.warning("html_decode_fallback_latin1", path=self.file_path)
        return raw.decode("latin-1")

    @staticmethod
    def _detect_meta_charset(raw: bytes) -> Optional[str]:
        """HTML 바이트에서 meta charset 선언을 추출한다."""
        import re

        # 첫 4KB 만 검색 (성능)
        head = raw[:4096].decode("ascii", errors="ignore").lower()

        # <meta charset="...">
        m = re.search(r'<meta\s+charset=["\']?([^"\'\s;>]+)', head)
        if m:
            return m.group(1).strip()

        # <meta http-equiv="content-type" content="...; charset=...">
        m = re.search(r'charset=([^"\'\s;>]+)', head)
        if m:
            return m.group(1).strip()

        return None

    # ------------------------------------------------------------------
    # BeautifulSoup 생성
    # ------------------------------------------------------------------
    @staticmethod
    def _make_soup(html: str) -> "BeautifulSoup":
        """BeautifulSoup 인스턴스를 생성한다. lxml 우선, fallback html.parser."""
        from bs4 import BeautifulSoup

        try:
            return BeautifulSoup(html, "lxml")
        except Exception:
            log.debug("lxml_parser_unavailable_falling_back_to_html_parser")
            return BeautifulSoup(html, "html.parser")

    # ------------------------------------------------------------------
    # 메타데이터 추출
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_metadata(soup: "BeautifulSoup") -> dict:
        """title, meta description, meta keywords 추출."""
        metadata: dict = {}

        # title
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        # meta description
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            metadata["description"] = desc["content"]

        # meta keywords
        kw = soup.find("meta", attrs={"name": "keywords"})
        if kw and kw.get("content"):
            metadata["keywords"] = kw["content"]

        return metadata

    # ------------------------------------------------------------------
    # 표 추출
    # ------------------------------------------------------------------
    def _extract_table(self, table_el: "Tag", table_idx: int) -> Optional[TableContent]:
        """<table> 요소에서 TableContent 를 생성한다."""
        from bs4 import Tag

        all_rows: list[list[str]] = []
        for tr in table_el.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells = []
            for cell in tr.find_all(["th", "td"]):
                cells.append(cell.get_text(separator=" ", strip=True))
            if cells:
                all_rows.append(cells)

        if not all_rows:
            return None

        headers = all_rows[0]
        body = all_rows[1:] if len(all_rows) > 1 else []
        md = self._table_to_markdown(headers, body)

        return TableContent(
            page_number=1,
            table_index=table_idx,
            headers=headers,
            rows=body,
            markdown=md,
            confidence=0.95,
        )

    @staticmethod
    def _table_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
        """표를 Markdown 문자열로 변환한다."""
        if not headers:
            return ""
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            padded = row + [""] * max(0, len(headers) - len(row))
            lines.append("| " + " | ".join(padded[: len(headers)]) + " |")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 이미지 추출
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_image(img_el: "Tag", image_idx: int) -> Optional[ImageContent]:
        """<img> 요소에서 ImageContent 를 생성한다."""
        src = img_el.get("src", "")
        if not src:
            return None

        alt = img_el.get("alt", "")

        return ImageContent(
            page_number=1,
            image_index=image_idx,
            image_path=str(src),
            description=str(alt) if alt else None,
        )
