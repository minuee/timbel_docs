"""비-PDF 비-오피스 포맷에 대해 미리보기 PDF 를 생성한다.

- DOCX/PPTX/HWP/XLSX 는 converter.ConvertingParser 가 이미 처리 (변환 PDF 를 원본 옆에 보존).
- 이 모듈은 그 외 포맷(IMAGE/TXT/HTML/MARKDOWN)에 대해 원본 옆에 preview.pdf 를 만든다.

전략:
- IMAGE: Pillow 로 단일 페이지 PDF.
- TXT/HTML/MARKDOWN: LibreOffice headless.

멱등성:
- 이미 preserved 위치에 파일이 있으면 재생성 없이 경로만 반환.
- 실패는 예외 없이 None 반환 — 파이프라인 차단 금지.

프론트 연동:
- documents 라우터의 GET /documents/{id}/pdf 엔드포인트가
  source_file 과 같은 디렉토리의 ``{stem}.pdf`` 를 자동 fallback 으로 서빙.
- 따라서 preserved 경로만 맞추면 프론트 PDF 뷰어가 그대로 동작.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time

from src.common.logging import get_logger
from src.pipeline.models.document import DocumentFormat

log = get_logger(__name__)

_LIBREOFFICE_TIMEOUT_SEC = 120

# PDF 를 만들어 둘 포맷 (DOCX/PPTX/HWP/XLSX 는 ConvertingParser 가 이미 처리).
_PREVIEW_TARGET_FORMATS: frozenset[DocumentFormat] = frozenset({
    DocumentFormat.IMAGE,
    DocumentFormat.TXT,
    DocumentFormat.HTML,
    DocumentFormat.MARKDOWN,
})


def _preserved_path(source_path: str) -> str:
    src_dir = os.path.dirname(source_path)
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(src_dir, f"{stem}.pdf")


async def ensure_preview_pdf(source_path: str, source_format: DocumentFormat) -> str | None:
    """원본 파일 옆에 미리보기용 PDF 를 보장한다.

    Args:
        source_path: 원본 업로드 파일 경로.
        source_format: 감지된 포맷.

    Returns:
        preserved PDF 경로 (성공), None (원본이 PDF 이거나 대상 외이거나 실패).
    """
    if source_format == DocumentFormat.PDF:
        return None
    if source_format not in _PREVIEW_TARGET_FORMATS:
        return None
    if not os.path.isfile(source_path):
        log.warning("preview_pdf_source_missing", source_path=source_path)
        return None

    preserved = _preserved_path(source_path)
    if os.path.exists(preserved):
        return preserved

    if source_format == DocumentFormat.IMAGE:
        return await _generate_from_image(source_path, preserved)

    # TXT/HTML/MARKDOWN → LibreOffice
    return await _generate_via_libreoffice(source_path, preserved, source_format)


async def _generate_from_image(source_path: str, preserved: str) -> str | None:
    """Pillow 로 단일 페이지 PDF 생성."""
    try:
        from PIL import Image

        def _save() -> None:
            img = Image.open(source_path)
            try:
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")
                img.save(preserved, "PDF", resolution=150.0)
            finally:
                img.close()

        await asyncio.to_thread(_save)
        log.info(
            "preview_pdf_from_image",
            source_path=source_path,
            preserved_path=preserved,
            size_bytes=os.path.getsize(preserved),
        )
        return preserved
    except Exception as exc:
        log.warning(
            "preview_pdf_from_image_failed",
            source_path=source_path,
            error=str(exc),
        )
        return None


async def _generate_via_libreoffice(
    source_path: str, preserved: str, source_format: DocumentFormat
) -> str | None:
    """LibreOffice headless 로 PDF 변환."""
    temp_dir = tempfile.mkdtemp(prefix="aicm_preview_")
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

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.warning("preview_pdf_soffice_not_found")
            return None

        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_LIBREOFFICE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning(
                "preview_pdf_libreoffice_timeout",
                source_path=source_path,
                timeout_sec=_LIBREOFFICE_TIMEOUT_SEC,
            )
            return None

        if proc.returncode != 0:
            log.warning(
                "preview_pdf_libreoffice_failed",
                source_path=source_path,
                returncode=proc.returncode,
                stderr=stderr.decode("utf-8", errors="replace")[:500],
            )
            return None

        stem = os.path.splitext(os.path.basename(source_path))[0]
        generated = os.path.join(temp_dir, f"{stem}.pdf")
        if not os.path.isfile(generated):
            log.warning("preview_pdf_libreoffice_output_missing", expected=generated)
            return None

        shutil.copy2(generated, preserved)
        elapsed = time.monotonic() - start_ts
        log.info(
            "preview_pdf_via_libreoffice",
            source_path=source_path,
            source_format=source_format.value,
            preserved_path=preserved,
            elapsed_sec=round(elapsed, 2),
            size_bytes=os.path.getsize(preserved),
        )
        return preserved
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
