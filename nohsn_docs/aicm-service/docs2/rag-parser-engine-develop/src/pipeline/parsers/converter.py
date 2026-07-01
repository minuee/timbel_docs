"""문서 → PDF 변환 모듈.

오피스 포맷(DOCX, PPTX, HWP, XLSX 등)을 LibreOffice headless로 PDF 변환한다.
변환된 PDF는 PDFParser가 처리한다.

전략:
- LibreOffice headless가 DOCX/PPTX/HWP/XLSX/DOC/PPT/XLS 모두 지원
- 변환 실패 시 개별 파서로 fallback
- 변환된 PDF는 임시 디렉토리에 저장 (처리 후 정리)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time

from src.common.logging import get_logger
from src.pipeline.models.document import DocumentFormat
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.base import BaseParser

log = get_logger(__name__)

# PDF 변환 타임아웃 (초)
_CONVERSION_TIMEOUT_SEC = 120

# PDF 변환이 필요한 포맷
_CONVERTIBLE_FORMATS: frozenset[DocumentFormat] = frozenset({
    DocumentFormat.DOCX,
    DocumentFormat.PPTX,
    DocumentFormat.HWP,
    DocumentFormat.XLSX,
})


class ConversionError(Exception):
    """문서 변환 실패."""


def needs_pdf_conversion(fmt: DocumentFormat) -> bool:
    """PDF 변환이 필요한 포맷인지 판별한다.

    Returns True for: DOCX, PPTX, HWP, XLSX
    Returns False for: PDF, TXT, HTML, MARKDOWN, IMAGE
    """
    return fmt in _CONVERTIBLE_FORMATS


async def convert_to_pdf(source_path: str, source_format: DocumentFormat) -> str:
    """LibreOffice headless로 문서를 PDF로 변환한다.

    Args:
        source_path: 원본 문서 경로.
        source_format: 원본 문서 포맷.

    Returns:
        변환된 PDF 파일 경로.

    Raises:
        ConversionError: 변환 실패 시.
    """
    if not os.path.isfile(source_path):
        raise ConversionError(f"원본 파일이 존재하지 않습니다: {source_path}")

    temp_dir = tempfile.mkdtemp(prefix="aicm_convert_")
    start_ts = time.monotonic()

    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        temp_dir,
        source_path,
    ]

    log.info(
        "pdf_conversion_start",
        source_path=source_path,
        source_format=source_format.value,
        temp_dir=temp_dir,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.error("soffice_not_found", detail="LibreOffice(soffice)가 설치되지 않았습니다.")
        raise ConversionError(
            "LibreOffice(soffice)가 시스템에 설치되어 있지 않습니다. "
            "apt install libreoffice-core 등으로 설치하세요."
        )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=_CONVERSION_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        shutil.rmtree(temp_dir, ignore_errors=True)
        elapsed = time.monotonic() - start_ts
        log.error(
            "pdf_conversion_timeout",
            source_path=source_path,
            timeout_sec=_CONVERSION_TIMEOUT_SEC,
            elapsed_sec=round(elapsed, 2),
        )
        raise ConversionError(
            f"PDF 변환 타임아웃 ({_CONVERSION_TIMEOUT_SEC}초): {source_path}"
        )

    elapsed = time.monotonic() - start_ts

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.error(
            "pdf_conversion_failed",
            source_path=source_path,
            returncode=proc.returncode,
            stderr=stderr_text,
        )
        raise ConversionError(
            f"LibreOffice 변환 실패 (exit={proc.returncode}): {stderr_text}"
        )

    # LibreOffice는 원본 파일명에서 확장자만 .pdf로 바꿔서 출력
    base = os.path.splitext(os.path.basename(source_path))[0]
    pdf_path = os.path.join(temp_dir, f"{base}.pdf")

    if not os.path.isfile(pdf_path):
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.error(
            "pdf_conversion_output_missing",
            expected_path=pdf_path,
            source_path=source_path,
        )
        raise ConversionError(f"변환 후 PDF 파일이 생성되지 않았습니다: {pdf_path}")

    log.info(
        "pdf_conversion_complete",
        source_path=source_path,
        source_format=source_format.value,
        pdf_path=pdf_path,
        elapsed_sec=round(elapsed, 2),
        pdf_size_bytes=os.path.getsize(pdf_path),
    )

    return pdf_path


class ConvertingParser(BaseParser):
    """PDF 변환 후 PDFParser에 위임하는 래퍼 파서.

    변환 실패 시 원본 포맷별 파서로 fallback.
    """

    def __init__(
        self,
        file_path: str,
        source_format: DocumentFormat,
        enable_ocr: bool = True,
    ) -> None:
        super().__init__(file_path)
        self._source_format = source_format
        self._temp_pdf: str | None = None
        self._enable_ocr = enable_ocr

    async def parse(self) -> ParseResult:
        """PDF로 변환 후 PDFParser에 위임한다. 실패 시 원본 파서로 fallback.

        변환된 임시 PDF 는 block_worker 의 Vision 파이프라인이 재사용할 수
        있도록 ParseResult 에 담아 반환하고, 정리 책임은 호출 측이
        `result.cleanup_temp()` 로 수행한다.
        """
        try:
            # 1. PDF 변환
            self._temp_pdf = await convert_to_pdf(self.file_path, self._source_format)

            # 2. PDFParser로 위임
            from src.pipeline.parsers.pdf_parser import PDFParser

            pdf_parser = PDFParser(self._temp_pdf, enable_ocr=self._enable_ocr)
            result = await pdf_parser.parse()

            # 3. source_file_path를 원본으로 복원
            result.source_file_path = self.file_path

            # 4. 메타데이터에 변환 정보 추가
            result.metadata["converted_from"] = self._source_format.value
            result.metadata["conversion_method"] = "libreoffice"

            # 5. 변환 PDF 경로 공유 + cleanup 책임 위임 (호출자가 cleanup_temp 호출)
            import os as _os

            result.pdf_path = self._temp_pdf
            result.temp_paths.append(_os.path.dirname(self._temp_pdf))

            # 5-b. 미리보기용 PDF 를 원본 옆에 보존 → /documents/{id}/pdf 엔드포인트가
            #      자동 fallback 으로 서빙 (documents.py:2264-2273).
            #      temp 디렉토리는 block_worker 가 cleanup_temp 로 나중에 정리하므로
            #      여기서 복사해 두지 않으면 미리보기 불가.
            try:
                src_dir = _os.path.dirname(self.file_path)
                stem = _os.path.splitext(_os.path.basename(self.file_path))[0]
                preserved = _os.path.join(src_dir, f"{stem}.pdf")
                if not _os.path.exists(preserved):
                    shutil.copy2(self._temp_pdf, preserved)
                    log.info(
                        "preview_pdf_preserved",
                        format=self._source_format.value,
                        preserved_path=preserved,
                        size_bytes=_os.path.getsize(preserved),
                    )
                result.metadata["preview_pdf_path"] = preserved
            except Exception as exc:
                # 미리보기 실패는 파이프라인에 영향 없음
                log.warning(
                    "preview_pdf_preserve_failed",
                    format=self._source_format.value,
                    error=str(exc),
                )

            # ConvertingParser 인스턴스에서는 더 이상 정리하지 않음
            self._temp_pdf = None

            return result

        except Exception as exc:
            log.warning(
                "pdf_conversion_failed_fallback_to_native",
                format=self._source_format.value,
                error=str(exc),
            )
            # 변환 자체 실패 시에는 즉시 임시 파일 정리
            self._cleanup()
            # fallback: 원본 포맷별 파서
            return await self._fallback_parse()

    async def _fallback_parse(self) -> ParseResult:
        """변환 실패 시 원본 포맷별 파서로 fallback."""
        from src.pipeline.parsers.router import _get_parser_registry

        registry = _get_parser_registry()
        parser_cls = registry.get(self._source_format)
        if parser_cls and parser_cls is not type(self):
            parser = parser_cls(self.file_path)
            return await parser.parse()
        raise RuntimeError(f"No fallback parser for {self._source_format.value}")

    def _cleanup(self) -> None:
        """임시 PDF 파일 및 디렉토리 정리."""
        if self._temp_pdf:
            try:
                temp_dir = os.path.dirname(self._temp_pdf)
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            self._temp_pdf = None
