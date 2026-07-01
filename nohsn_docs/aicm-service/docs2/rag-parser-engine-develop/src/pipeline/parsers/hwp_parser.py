"""HWP 파서 -- LibreOffice 변환 -> PDF 파서 위임.

HWP (한컴오피스) 파일은 직접 파싱이 어려우므로
LibreOffice + HWP2ODT 플러그인으로 PDF 변환 후 PDFParser 에 위임한다.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from src.common.logging import get_logger
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.base import BaseParser
from src.pipeline.parsers.pdf_parser import PDFParser

log = get_logger(__name__)


class HWPParser(BaseParser):
    """HWP 문서 파서 -- LibreOffice PDF 변환 후 PDFParser 에 위임."""

    async def parse(self) -> ParseResult:
        """HWP -> PDF 변환 후 PDFParser 로 파싱한다."""
        pdf_path = await self._convert_to_pdf()
        log.info("hwp_converted_to_pdf", source=self.file_path, pdf=pdf_path)

        parser = PDFParser(pdf_path)
        result = await parser.parse()

        # source_file_path 를 원본 HWP 로 덮어씀
        result.source_file_path = self.file_path
        result.metadata["original_format"] = "hwp"
        result.metadata["converted_pdf"] = pdf_path
        return result

    async def _convert_to_pdf(self) -> str:
        """LibreOffice headless 로 HWP -> PDF 변환."""
        out_dir = tempfile.mkdtemp(prefix="aicm_hwp_")
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            out_dir,
            self.file_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        base = os.path.splitext(os.path.basename(self.file_path))[0]
        pdf_path = os.path.join(out_dir, f"{base}.pdf")
        if not os.path.exists(pdf_path):
            log.error(
                "hwp_conversion_failed",
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
            raise FileNotFoundError(f"HWP -> PDF 변환 실패: {self.file_path}")
        return pdf_path
