"""이미지 파서 -- OCR 엔진 + PIL 전처리 + 표 구조 감지.

Phase 2 Task B-2.
"""

from __future__ import annotations

import asyncio
import io
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
from src.pipeline.parsers.ocr_engine import OCREngine, OCRResult

log = get_logger(__name__)


class ImageParser(BaseParser):
    """이미지 파서.

    처리 전략
    ---------
    1. PIL 로 이미지 열기 + 전처리 (EXIF 회전 보정, 명암 조정)
    2. OCREngine.extract() 호출
    3. 표 구조가 감지되면 TableContent 로 변환
    4. source_location 에 bbox, is_image 메타데이터 기록
    """

    def __init__(self, file_path: str) -> None:
        super().__init__(file_path)
        self._ocr_engine = OCREngine()

    async def parse(self) -> ParseResult:
        """이미지를 파싱하여 텍스트와 표를 추출한다."""
        # 1) 이미지 로드 + 전처리
        image_bytes, media_type = await asyncio.to_thread(self._load_and_preprocess)

        if not image_bytes:
            log.warning("image_load_failed", path=self.file_path)
            return ParseResult(source_file_path=self.file_path)

        # 2) OCR 수행
        ocr_result: OCRResult = await self._ocr_engine.extract(image_bytes, media_type)

        # 3) 결과를 ParseResult 로 변환
        return self._build_result(ocr_result, media_type)

    def _load_and_preprocess(self) -> tuple[bytes, str]:
        """이미지를 로드하고 전처리한다.

        Returns
        -------
        tuple[bytes, str]
            (전처리된 이미지 bytes, MIME 타입)
        """
        from PIL import Image, ImageEnhance, ImageOps

        try:
            img = Image.open(self.file_path)
        except Exception as exc:
            log.error("image_open_failed", path=self.file_path, error=str(exc))
            return b"", "image/png"

        # MIME 타입 결정
        fmt = img.format or "PNG"
        media_type_map = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "TIFF": "image/tiff",
            "BMP": "image/bmp",
            "WEBP": "image/webp",
        }
        media_type = media_type_map.get(fmt.upper(), "image/png")

        # EXIF 회전 보정
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # RGB 변환 (RGBA/P 모드 대응)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # 명암 조정: 낮은 대비 이미지 개선
        try:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.3)
        except Exception:
            pass

        # 해상도 보장: 짧은 변이 1000px 미만이면 업스케일
        min_dim = min(img.size)
        if min_dim < 1000:
            scale = 1000 / min_dim
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            try:
                img = img.resize(new_size, Image.LANCZOS)
            except Exception:
                pass

        # PNG 바이트로 변환
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), media_type

    def _build_result(self, ocr_result: OCRResult, media_type: str) -> ParseResult:
        """OCR 결과를 ParseResult 로 변환한다."""
        tables: list[TableContent] = []
        text_parts: list[str] = []

        # OCR 텍스트
        if ocr_result.texts:
            text_parts.extend(ocr_result.texts)

        # OCR 표 -> TableContent
        for t_idx, table_md in enumerate(ocr_result.tables):
            headers, rows = self._parse_markdown_table(table_md)
            tc = TableContent(
                page_number=1,
                table_index=t_idx,
                headers=headers,
                rows=rows,
                markdown=table_md,
                confidence=ocr_result.confidence,
                bbox=None,
            )
            tables.append(tc)
            text_parts.append(table_md)

        page_text = "\n\n".join(text_parts)

        text_blocks: list[TextBlock] = []
        if page_text:
            text_blocks.append(
                TextBlock(
                    text=page_text,
                    start_char_offset=0,
                    end_char_offset=len(page_text),
                )
            )

        images: list[ImageContent] = [
            ImageContent(
                page_number=1,
                image_index=0,
                image_path=self.file_path,
                ocr_text=page_text if page_text else None,
                description=None,
                bbox=None,
            )
        ]

        page = PageContent(
            page_number=1,
            text=page_text,
            text_blocks=text_blocks,
            tables=tables,
            images=images,
            layout_type="single",
            ocr_used=True,
        )

        metadata = {
            "ocr_engine": ocr_result.engine_used,
            "ocr_confidence": ocr_result.confidence,
            "is_image": True,
            "media_type": media_type,
        }

        return ParseResult(
            raw_text=page_text,
            pages=[page],
            tables=tables,
            images=images,
            metadata=metadata,
            source_file_path=self.file_path,
        )

    @staticmethod
    def _parse_markdown_table(md: str) -> tuple[list[str], list[list[str]]]:
        """Markdown 표 문자열을 헤더와 데이터 행으로 파싱한다."""
        lines = [line.strip() for line in md.strip().split("\n") if line.strip()]
        if len(lines) < 2:
            return [], []

        def parse_row(line: str) -> list[str]:
            # 양쪽 | 제거 후 분리
            line = line.strip("|")
            return [cell.strip() for cell in line.split("|")]

        headers = parse_row(lines[0])

        # 구분선 건너뛰기
        data_start = 1
        if data_start < len(lines) and all(
            c in "-| :" for c in lines[data_start]
        ):
            data_start = 2

        rows: list[list[str]] = []
        for line in lines[data_start:]:
            if line.startswith("|"):
                rows.append(parse_row(line))

        return headers, rows
