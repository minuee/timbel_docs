"""파서 라우터 -- 포맷 감지(MIME + 확장자 + magic bytes) + 파서 레지스트리.

오피스 포맷(DOCX, PPTX, HWP, XLSX)은 PDF-first 전략을 사용한다:
converter 모듈이 설치되어 있으면 PDF로 변환 후 PDFParser에 위임하고,
변환 불가 시 개별 네이티브 파서로 fallback한다.
"""

from __future__ import annotations

import mimetypes
import os
from typing import Optional

from src.common.exceptions import UnsupportedFormatError
from src.common.logging import get_logger
from src.pipeline.models.document import DocumentFormat
from src.pipeline.parsers.base import BaseParser

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Magic bytes 시그니처
# ---------------------------------------------------------------------------
_MAGIC_SIGNATURES: list[tuple[bytes, DocumentFormat]] = [
    (b"%PDF", DocumentFormat.PDF),
    (b"PK\x03\x04", DocumentFormat.DOCX),  # ZIP (DOCX/XLSX/PPTX) — 확장자로 세분화
    (b"\xd0\xcf\x11\xe0", DocumentFormat.HWP),  # OLE2 (HWP/DOC/XLS)
    (b"HWP Document File", DocumentFormat.HWP),
]

# 확장자 -> 포맷 매핑
_EXT_MAP: dict[str, DocumentFormat] = {
    ".pdf": DocumentFormat.PDF,
    ".docx": DocumentFormat.DOCX,
    ".doc": DocumentFormat.DOCX,
    ".hwp": DocumentFormat.HWP,
    ".hwpx": DocumentFormat.HWP,
    ".pptx": DocumentFormat.PPTX,
    ".ppt": DocumentFormat.PPTX,
    ".xlsx": DocumentFormat.XLSX,
    ".xls": DocumentFormat.XLSX,
    ".html": DocumentFormat.HTML,
    ".htm": DocumentFormat.HTML,
    ".txt": DocumentFormat.TXT,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
    ".png": DocumentFormat.IMAGE,
    ".jpg": DocumentFormat.IMAGE,
    ".jpeg": DocumentFormat.IMAGE,
    ".tiff": DocumentFormat.IMAGE,
    ".bmp": DocumentFormat.IMAGE,
    ".webp": DocumentFormat.IMAGE,
}

# MIME -> 포맷 매핑
_MIME_MAP: dict[str, DocumentFormat] = {
    "application/pdf": DocumentFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentFormat.DOCX,
    "application/msword": DocumentFormat.DOCX,
    "application/haansofthwp": DocumentFormat.HWP,
    "application/x-hwp": DocumentFormat.HWP,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": DocumentFormat.PPTX,
    "application/vnd.ms-powerpoint": DocumentFormat.PPTX,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocumentFormat.XLSX,
    "application/vnd.ms-excel": DocumentFormat.XLSX,
    "text/html": DocumentFormat.HTML,
    "text/plain": DocumentFormat.TXT,
    "text/markdown": DocumentFormat.MARKDOWN,
    "image/png": DocumentFormat.IMAGE,
    "image/jpeg": DocumentFormat.IMAGE,
    "image/tiff": DocumentFormat.IMAGE,
    "image/bmp": DocumentFormat.IMAGE,
    "image/webp": DocumentFormat.IMAGE,
}


def detect_format(file_path: str) -> DocumentFormat:
    """파일의 포맷을 감지한다.

    우선순위: magic bytes > 확장자 > MIME type
    """
    # 1) magic bytes
    fmt = _detect_by_magic(file_path)
    if fmt is not None:
        # ZIP 기반 파일은 확장자로 세분화
        if fmt == DocumentFormat.DOCX:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".pptx", ".ppt"):
                return DocumentFormat.PPTX
            if ext in (".xlsx", ".xls"):
                return DocumentFormat.XLSX
            if ext in (".hwpx",):
                return DocumentFormat.HWP
        log.debug("format_detected_by_magic", format=fmt.value, path=file_path)
        return fmt

    # 2) 확장자
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _EXT_MAP:
        log.debug("format_detected_by_ext", format=_EXT_MAP[ext].value, path=file_path)
        return _EXT_MAP[ext]

    # 3) MIME type
    mime, _ = mimetypes.guess_type(file_path)
    if mime and mime in _MIME_MAP:
        log.debug("format_detected_by_mime", format=_MIME_MAP[mime].value, path=file_path)
        return _MIME_MAP[mime]

    raise UnsupportedFormatError(ext or "unknown")


def _detect_by_magic(file_path: str) -> Optional[DocumentFormat]:
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)
    except OSError:
        return None

    for sig, fmt in _MAGIC_SIGNATURES:
        if header[: len(sig)] == sig:
            return fmt
        # HWP Document File 시그니처는 오프셋이 다를 수 있음
        if sig in header:
            return fmt
    return None


# ---------------------------------------------------------------------------
# 파서 레지스트리
# ---------------------------------------------------------------------------
def _get_parser_registry() -> dict[DocumentFormat, type[BaseParser]]:
    """지연 import 로 순환 의존 방지."""
    from src.pipeline.parsers.docx_parser import DOCXParser
    from src.pipeline.parsers.html_parser import HTMLParser
    from src.pipeline.parsers.pptx_parser import PPTXParser
    from src.pipeline.parsers.hwp_parser import HWPParser
    from src.pipeline.parsers.image_parser import ImageParser
    from src.pipeline.parsers.markdown_parser import MarkdownParser
    from src.pipeline.parsers.pdf_parser import PDFParser
    from src.pipeline.parsers.txt_parser import TXTParser
    from src.pipeline.parsers.xlsx_parser import XLSXParser

    return {
        DocumentFormat.PDF: PDFParser,
        DocumentFormat.DOCX: DOCXParser,
        DocumentFormat.PPTX: PPTXParser,
        DocumentFormat.HWP: HWPParser,
        DocumentFormat.XLSX: XLSXParser,
        DocumentFormat.HTML: HTMLParser,
        DocumentFormat.IMAGE: ImageParser,
        DocumentFormat.TXT: TXTParser,
        DocumentFormat.MARKDOWN: MarkdownParser,
    }


def select_parser(
    source_format: DocumentFormat,
    file_path: str,
    enable_ocr: bool = True,
) -> BaseParser:
    """포맷에 맞는 파서 인스턴스를 반환한다.

    오피스 포맷(DOCX, PPTX, HWP, XLSX)은 PDF 변환 후 PDFParser에 위임.
    변환 불가 시 개별 파서로 fallback.

    enable_ocr=False 로 호출하면 PDFParser 의 OCR 후처리를 건너뜀 (preview 등 빠른 분석용).
    """
    # PDF 변환이 필요한 오피스 포맷
    try:
        from src.pipeline.parsers.converter import ConvertingParser, needs_pdf_conversion

        if needs_pdf_conversion(source_format):
            log.info(
                "using_pdf_conversion",
                format=source_format.value,
                path=file_path,
            )
            return ConvertingParser(file_path, source_format, enable_ocr=enable_ocr)
    except ImportError:
        log.debug("converter_module_not_available_using_native_parser")

    # 직접 파싱 (PDF, TXT, HTML, MD, IMAGE) 또는 converter 미설치 시 fallback
    registry = _get_parser_registry()
    parser_cls = registry.get(source_format)
    if not parser_cls:
        raise UnsupportedFormatError(source_format.value)
    # PDFParser만 enable_ocr을 지원한다
    from src.pipeline.parsers.pdf_parser import PDFParser
    if parser_cls is PDFParser:
        return PDFParser(file_path, enable_ocr=enable_ocr)
    return parser_cls(file_path)
