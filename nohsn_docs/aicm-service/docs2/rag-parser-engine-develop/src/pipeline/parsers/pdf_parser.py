"""PDF 파서 -- pdfplumber 텍스트/표 추출 + 다단 레이아웃 감지.

chunk_service/pipeline/stages/extract_text_process.py 의 히스토그램 기반
거터(gutter) 분석 알고리즘을 async 아키텍처로 재구현하였다.
"""

from __future__ import annotations

import asyncio
import re
import statistics
import tempfile
from pathlib import Path
from typing import Any, Optional

import pdfplumber

from src.common.logging import get_logger
from src.pipeline.models.parse_result import (
    HeadingInfo,
    ImageContent,
    PageContent,
    ParseResult,
    TableContent,
    TextBlock,
)
from src.pipeline.parsers.base import BaseParser

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 다단 레이아웃 분석 상수
# ---------------------------------------------------------------------------
_GUTTER_SCAN_START = 0.4  # 페이지 너비 대비 스캔 시작 비율
_GUTTER_SCAN_END = 0.6
_GUTTER_WINDOW = 20  # 슬라이딩 윈도우 폭 (pt)
_GUTTER_ABS_THRESHOLD = 15  # 절대 밀도 임계값
_GUTTER_REL_THRESHOLD = 0.1  # 상대 밀도 임계값
_Y_TOLERANCE = 3.0  # 같은 라인으로 취급할 Y 차이 (pt)
_HEADER_FOOTER_MARGIN = 50  # 헤더/푸터 마진 (pt)
_MIN_TEXT_LENGTH_FOR_OCR = 10  # 이 길이 미만이면 OCR 필요 페이지로 판정

# ---------------------------------------------------------------------------
# 헤딩 감지 상수
# ---------------------------------------------------------------------------
_HEADING_SIZE_RATIO = 1.2  # 페이지 중앙값 대비 이 비율 이상이면 헤딩 후보
_HEADING_MAX_WORDS = 30  # 헤딩으로 인정할 최대 단어 수
_HEADING_MAX_LEVELS = 3  # h1, h2, h3 까지

# ---------------------------------------------------------------------------
# 한글 CID 폰트 매핑 실패 감지 상수
# ---------------------------------------------------------------------------
# CID 폰트 매핑 실패는 두 가지 형태로 나타난다:
#
# (1) "3회 이상 반복" — 같은 음절이 3회 이상 연속.
#     예: "개개개개", "사사사" — 대체 글리프로 전체 치환된 전형적 케이스.
#
# (2) "AABB+ glyph doubling" — 각 음절이 정확히 2회씩 반복되어 나란히 나타남.
#     예: "하하이이패패스스", "길길라라잡잡이이", "제제장장" — 하이패스 PDF 에서
#     제목/헤딩이 실제로 이렇게 추출됐다. 폰트가 글리프를 2번 emit 한 케이스로,
#     (1) 의 detector 로는 못 잡는다.
#
# 자연어에서 단일 "각각", "쓰쓰가무시" 같은 우연한 2회 반복은 흔하므로,
# (2) 는 "AABB 쌍이 최소 2번 연속 (즉 AABBCC+)" 형태만 깨짐으로 간주하며,
# 문서 전체에서 이런 런이 _MIN_DOUBLING_RUNS 개 이상이면 CID 깨짐 판정한다.

_BROKEN_RUN_PATTERN = re.compile(r"([\uac00-\ud7a3])\1{2,}")  # 한글 음절 3회 이상 반복
# AABB 쌍이 2번 이상 연속 = 최소 4 음절 (AABBCCDD 또는 AABBCC)
_GLYPH_DOUBLING_PATTERN = re.compile(r"(?:([\uac00-\ud7a3])\1){2,}")

_BROKEN_TEXT_RATIO_THRESHOLD = 0.30  # 30% 이상이면 깨진 페이지로 판정
_MIN_DOUBLING_RUNS = 3  # AABB+ 런이 3개 이상이면 glyph doubling 깨짐 판정
_MIN_TEXT_LENGTH_FOR_BROKEN_CHECK = 30  # 너무 짧은 텍스트는 판정 보류


def detect_broken_text_ratio(text: str) -> float:
    """텍스트에서 CID 매핑 실패(형태 1)로 추정되는 글자의 비율을 반환한다.

    같은 한글 음절이 3회 이상 연속되는 패턴을 깨짐으로 간주한다.

    Returns:
        0.0 ~ 1.0 사이의 비율. 0.0 = 깨짐 없음.
    """
    if not text or len(text) < _MIN_TEXT_LENGTH_FOR_BROKEN_CHECK:
        return 0.0
    broken_chars = sum(len(m.group(0)) for m in _BROKEN_RUN_PATTERN.finditer(text))
    if broken_chars == 0:
        return 0.0
    # 공백/제어 문자를 제외한 본문 길이를 기준으로 정규화
    visible_len = sum(1 for c in text if not c.isspace())
    if visible_len == 0:
        return 0.0
    return min(1.0, broken_chars / visible_len)


def detect_glyph_doubling_runs(text: str) -> int:
    """연속된 AABB 글리프 doubling 런(2쌍 이상)의 개수를 반환한다.

    하이패스 PDF 처럼 제목 폰트가 글리프를 2번 emit 해 "하하이이패패스스"
    형태로 추출되는 CID 깨짐 형태(2) 를 감지한다. 자연어에서 우연히 나타날 수
    있는 단일 AABB (예: "각각") 는 제외하기 위해 AABB 가 2번 이상 연속
    (즉 AABBCC 이상) 인 런만 카운트한다.
    """
    if not text or len(text) < _MIN_TEXT_LENGTH_FOR_BROKEN_CHECK:
        return 0
    return sum(1 for _ in _GLYPH_DOUBLING_PATTERN.finditer(text))


def is_broken_text(text: str) -> bool:
    """텍스트가 CID 깨짐으로 판정되는지 여부.

    두 시그널을 OR 로 결합한다:
    - 3회 이상 반복 비율이 임계값 이상
    - AABB+ 연속 런이 N개 이상
    """
    return (
        detect_broken_text_ratio(text) >= _BROKEN_TEXT_RATIO_THRESHOLD
        or detect_glyph_doubling_runs(text) >= _MIN_DOUBLING_RUNS
    )


class PDFParser(BaseParser):
    """pdfplumber 기반 PDF 파서.

    처리 전략
    ---------
    1. 페이지별 텍스트 블록 좌표 추출 (다단 감지 포함)
    2. 표 영역 감지 및 Markdown 변환
    3. 이미지 메타 수집
    4. source_location 데이터를 모든 추출 요소에 부착
    """

    def __init__(self, file_path: str, enable_ocr: bool = True) -> None:
        super().__init__(file_path)
        self._enable_ocr = enable_ocr

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    async def parse(self) -> ParseResult:
        """비동기 PDF 파싱. IO-bound 작업을 스레드풀에 위임.

        빈 페이지(ocr_used=True)는 추출 후 OCR 후처리.
        enable_ocr=False 이면 OCR 후처리를 건너뛴다 (preview/빠른 분석용).
        """
        result = await asyncio.to_thread(self._parse_sync)

        # OCR 후처리: 빈 페이지에 대해 OCREngine 실행 (스캔 PDF 대응)
        if not self._enable_ocr:
            return result
        empty_pages = [p for p in result.pages if p.ocr_used]
        if empty_pages:
            try:
                import pdfplumber
                from src.pipeline.models.parse_result import TextBlock

                with pdfplumber.open(self.file_path) as pdf:
                    for page_content in empty_pages:
                        try:
                            raw_page = pdf.pages[page_content.page_number - 1]
                            ocr_text = await self._run_ocr(raw_page, page_content.page_number)
                            # OCR 결과 채택 조건:
                            # - OCR 결과가 더 길거나
                            # - 기존 텍스트가 깨져 있고 OCR 결과가 비어있지 않으면 교체
                            existing_broken = is_broken_text(page_content.text)
                            should_replace = bool(ocr_text) and (
                                len(ocr_text) > len(page_content.text)
                                or (existing_broken and len(ocr_text.strip()) >= _MIN_TEXT_LENGTH_FOR_OCR)
                            )
                            if should_replace:
                                page_content.text = ocr_text
                                page_content.text_blocks = [
                                    TextBlock(
                                        text=ocr_text,
                                        page_number=page_content.page_number,
                                        bbox=(0, 0, raw_page.width, raw_page.height),
                                        paragraph_index=0,
                                        char_offset_start=0,
                                        char_offset_end=len(ocr_text),
                                    )
                                ]
                                log.info(
                                    "ocr_applied_post_parse",
                                    page=page_content.page_number,
                                    ocr_chars=len(ocr_text),
                                )
                        except Exception as exc:
                            log.debug(
                                "ocr_post_parse_failed",
                                page=page_content.page_number,
                                error=str(exc),
                            )
            except Exception as exc:
                log.debug("ocr_batch_post_parse_failed", error=str(exc))

        return result

    # ------------------------------------------------------------------
    # 동기 내부 구현 (pdfplumber 는 동기 라이브러리)
    # ------------------------------------------------------------------

    # 대용량 문서 최적화: 페이지 배치 크기
    _PAGE_BATCH_SIZE = 20

    # ------------------------------------------------------------------
    # pypdfium2 보조 추출 — pdfplumber 가 CID 폰트를 풀지 못할 때 사용
    # ------------------------------------------------------------------
    _pdfium_doc: Any | None = None
    _pdfium_failed: bool = False

    def _get_pdfium_doc(self) -> Any | None:
        """pypdfium2 PdfDocument 를 lazy 로드한다. 실패 시 None."""
        if self._pdfium_failed:
            return None
        if self._pdfium_doc is not None:
            return self._pdfium_doc
        try:
            import pypdfium2 as pdfium  # type: ignore

            self._pdfium_doc = pdfium.PdfDocument(self.file_path)
            return self._pdfium_doc
        except Exception as exc:  # ImportError 또는 PDF 로드 실패
            log.debug("pdfium_unavailable", error=str(exc))
            self._pdfium_failed = True
            return None

    def _close_pdfium_doc(self) -> None:
        """pypdfium2 리소스를 해제한다."""
        if self._pdfium_doc is not None:
            try:
                self._pdfium_doc.close()
            except Exception:
                pass
            self._pdfium_doc = None

    def _extract_text_via_pdfium(self, page_number: int) -> str:
        """pypdfium2 로 페이지 텍스트를 재추출한다.

        page_number : 1-based.
        Returns:
            추출된 텍스트. 실패 시 빈 문자열.
        """
        doc = self._get_pdfium_doc()
        if doc is None:
            return ""
        try:
            page = doc[page_number - 1]
            text_page = page.get_textpage()
            try:
                raw = text_page.get_text_range() or ""
            finally:
                text_page.close()
                page.close()
            return raw
        except Exception as exc:
            log.debug("pdfium_page_extract_failed", page=page_number, error=str(exc))
            return ""

    def _parse_sync(
        self,
        progress_callback: Any | None = None,
    ) -> ParseResult:
        """PDF 를 배치 단위(20페이지)로 스트리밍 처리한다.

        Parameters
        ----------
        progress_callback : Callable[[int, int], None] | None
            (현재 페이지, 전체 페이지) 진행 콜백
        """
        pages: list[PageContent] = []
        all_tables: list[TableContent] = []
        all_images: list[ImageContent] = []
        all_headings: list[HeadingInfo] = []

        with pdfplumber.open(self.file_path) as pdf:
            total_pages = len(pdf.pages)
            total_char_offset = 0

            # 배치 단위로 처리하여 메모리 효율 확보
            for batch_start in range(0, total_pages, self._PAGE_BATCH_SIZE):
                batch_end = min(batch_start + self._PAGE_BATCH_SIZE, total_pages)
                batch_pages = pdf.pages[batch_start:batch_end]

                for local_idx, page in enumerate(batch_pages):
                    page_idx = batch_start + local_idx
                    page_number = page_idx + 1
                    width = page.width
                    height = page.height

                    # 헤더/푸터 마진 제거
                    top = min(_HEADER_FOOTER_MARGIN, height * 0.1)
                    bottom = max(height - _HEADER_FOOTER_MARGIN, height * 0.9)
                    if height > top + bottom * 0.1:
                        cropped = page.crop((0, top, width, bottom))
                    else:
                        cropped = page

                    # 1) 텍스트 추출 (다단 감지)
                    text, text_blocks, layout_type = self._extract_text_with_layout(
                        cropped, page_number, total_char_offset
                    )

                    # 1b) CID 폰트 매핑 실패 감지 → pypdfium2 fallback
                    plumber_broken_ratio = detect_broken_text_ratio(text)
                    if plumber_broken_ratio >= _BROKEN_TEXT_RATIO_THRESHOLD:
                        pdfium_text = self._extract_text_via_pdfium(page_number)
                        pdfium_broken_ratio = detect_broken_text_ratio(pdfium_text)
                        # pdfium 결과가 더 나으면 채택
                        if (
                            pdfium_text
                            and pdfium_broken_ratio < plumber_broken_ratio
                        ):
                            log.info(
                                "pdf_text_pdfium_fallback",
                                page=page_number,
                                plumber_ratio=round(plumber_broken_ratio, 3),
                                pdfium_ratio=round(pdfium_broken_ratio, 3),
                                plumber_chars=len(text),
                                pdfium_chars=len(pdfium_text),
                            )
                            text = pdfium_text
                            # pdfium 경로는 좌표를 잃으므로 단일 TextBlock 으로 대체
                            text_blocks = [
                                TextBlock(
                                    text=pdfium_text,
                                    start_char_offset=total_char_offset,
                                    end_char_offset=total_char_offset + len(pdfium_text),
                                )
                            ]
                            layout_type = "single"
                        else:
                            log.warning(
                                "pdf_text_broken_pdfium_no_help",
                                page=page_number,
                                plumber_ratio=round(plumber_broken_ratio, 3),
                                pdfium_ratio=round(pdfium_broken_ratio, 3),
                            )

                    # 1c) 워드랩된 마크다운 테이블 행 병합
                    text = self._merge_wrapped_table_rows(text)

                    # OCR 필요 여부 판정 (실제 OCR 호출은 async parse()에서 후처리)
                    # - 텍스트가 너무 짧거나 (스캔 PDF)
                    # - 추출 텍스트가 여전히 깨져 있으면 OCR 트리거
                    ocr_used = (
                        len(text.strip()) < _MIN_TEXT_LENGTH_FOR_OCR
                        or detect_broken_text_ratio(text) >= _BROKEN_TEXT_RATIO_THRESHOLD
                    )

                    # 1.5) 폰트 기반 헤딩 감지
                    page_headings = self._detect_headings(
                        cropped, text_blocks, page_number
                    )
                    all_headings.extend(page_headings)

                    # 2) 표 추출
                    page_tables = self._extract_tables(page, page_number)
                    all_tables.extend(page_tables)

                    # 3) 이미지 메타 수집 (메모리 효율적: 수집 후 즉시 해제)
                    page_images = self._extract_image_metadata(page, page_number)
                    all_images.extend(page_images)

                    pages.append(
                        PageContent(
                            page_number=page_number,
                            text=text,
                            text_blocks=text_blocks,
                            tables=page_tables,
                            images=page_images,
                            layout_type=layout_type,
                            ocr_used=ocr_used,
                        )
                    )
                    total_char_offset += len(text)

                    # 진행 콜백 (100+ 페이지 문서용)
                    if progress_callback is not None and total_pages >= 100:
                        progress_callback(page_number, total_pages)

                # 배치 처리 후 페이지 캐시 해제 (메모리 최적화)
                try:
                    if hasattr(page, "flush_cache"):
                        page.flush_cache()  # type: ignore[union-attr]
                    elif hasattr(page, "close"):
                        page.close()  # type: ignore[union-attr]
                except Exception:
                    pass  # 캐시 해제 실패는 non-fatal

                if total_pages >= 100:
                    log.info(
                        "pdf_batch_processed",
                        batch=f"{batch_start + 1}-{batch_end}",
                        total=total_pages,
                    )

        # pypdfium2 핸들 정리 (lazy 로드된 경우)
        self._close_pdfium_doc()

        raw_text = "\n".join(p.text for p in pages)
        metadata = self._extract_pdf_metadata(self.file_path)

        # 헤딩 정보를 메타데이터에 추가
        if all_headings:
            metadata["headings"] = [h.model_dump() for h in all_headings]

        return ParseResult(
            raw_text=raw_text,
            pages=pages,
            tables=all_tables,
            images=all_images,
            metadata=metadata,
            source_file_path=self.file_path,
        )

    # ------------------------------------------------------------------
    # OCR — 스캔 PDF 대응 (PaddleOCR → Claude Vision cascade)
    # ------------------------------------------------------------------
    async def _run_ocr(self, page: Any, page_number: int) -> str:
        """페이지에서 OCR로 텍스트를 추출한다.

        pdfplumber에서 렌더한 페이지 이미지를 OCREngine에 전달.
        PaddleOCR이 주, Claude Vision이 fallback.
        """
        try:
            # 페이지를 이미지로 렌더
            img = await asyncio.to_thread(
                page.to_image, resolution=200
            )
            # PIL Image → bytes
            import io

            buf = io.BytesIO()
            img.original.save(buf, format="PNG")
            image_bytes = buf.getvalue()

            from src.pipeline.parsers.ocr_engine import OCREngine

            engine = OCREngine()
            result = await engine.extract(image_bytes, media_type="image/png")
            # OCRResult.texts (list[str]) → 하나의 텍스트로 결합
            parts = []
            if result.texts:
                parts.extend(result.texts)
            if result.tables:
                parts.extend(result.tables)
            return "\n".join(parts).strip()
        except ImportError:
            log.debug("ocr_engine_not_available", page=page_number)
            return ""
        except Exception as exc:
            log.debug("ocr_run_failed", page=page_number, error=str(exc))
            return ""

    # ------------------------------------------------------------------
    # 다단 감지 + 텍스트 추출
    # ------------------------------------------------------------------
    def _extract_text_with_layout(
        self,
        page: Any,
        page_number: int,
        global_char_offset: int,
    ) -> tuple[str, list[TextBlock], str]:
        """페이지 텍스트를 추출하고 다단 레이아웃을 감지한다.

        Returns:
            (full_text, text_blocks, layout_type)
        """
        try:
            split_x = self._detect_column_split(page)

            if split_x is not None:
                x0, top, x1, bottom = page.bbox
                if x0 + 1 < split_x < x1 - 1:
                    left = page.crop((x0, top, split_x, bottom))
                    right = page.crop((split_x, top, x1, bottom))
                    left_lines = self._extract_lines(left)
                    right_lines = self._extract_lines(right)
                    all_lines = left_lines + right_lines
                    layout_type = "multi_column"
                else:
                    all_lines = self._extract_lines(page)
                    layout_type = "single"
            else:
                all_lines = self._extract_lines(page)
                layout_type = "single"
        except Exception:
            log.warning("text_extraction_fallback", page=page_number)
            raw = page.extract_text() or ""
            block = TextBlock(
                text=raw,
                start_char_offset=global_char_offset,
                end_char_offset=global_char_offset + len(raw),
            )
            return raw, [block], "single"

        # 라인 -> TextBlock 변환
        text_blocks: list[TextBlock] = []
        running_offset = global_char_offset
        texts: list[str] = []

        for line_text, bbox in all_lines:
            if not line_text.strip():
                continue
            tb = TextBlock(
                text=line_text,
                start_char_offset=running_offset,
                end_char_offset=running_offset + len(line_text),
                bbox=bbox,
            )
            text_blocks.append(tb)
            texts.append(line_text)
            running_offset += len(line_text) + 1  # +1 for newline

        full_text = "\n".join(texts)
        return full_text, text_blocks, layout_type

    def _detect_column_split(self, page: Any) -> Optional[float]:
        """히스토그램 기반 다단 거터 감지.

        chunk_service extract_text_process.py 의 _detect_column_split_x 를 참고하였다.
        """
        try:
            if not page.chars:
                return None

            x0, _top, x1, _bottom = page.bbox
            width = x1 - x0
            hist_len = int(width) + 1
            hist = [0] * hist_len

            for c in page.chars:
                idx = int(c["x0"] - x0)
                if 0 <= idx < hist_len:
                    hist[idx] += 1

            scan_start = int(width * _GUTTER_SCAN_START)
            scan_end = int(width * _GUTTER_SCAN_END)
            if scan_start >= scan_end:
                return None

            min_density = float("inf")
            max_density = 0
            best_x: Optional[float] = None

            for x in range(scan_start, max(scan_start + 1, scan_end - _GUTTER_WINDOW)):
                density = sum(hist[x : x + _GUTTER_WINDOW])
                if density < min_density:
                    min_density = density
                    best_x = x + _GUTTER_WINDOW / 2 + x0
                if density > max_density:
                    max_density = density

            if best_x is None:
                return None

            is_gutter = min_density < _GUTTER_ABS_THRESHOLD or (
                max_density > 0 and (min_density / max_density) < _GUTTER_REL_THRESHOLD
            )
            return best_x if is_gutter else None
        except Exception:
            return None

    def _extract_lines(self, page: Any) -> list[tuple[str, list[float]]]:
        """페이지에서 라인 단위 텍스트와 bbox 를 추출한다."""
        try:
            words = page.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=3)
        except Exception:
            return []

        if not words:
            return []

        lines: list[tuple[str, list[float]]] = []
        current_words: list[dict] = []
        current_y = words[0]["top"]

        for w in words:
            if abs(w["top"] - current_y) <= _Y_TOLERANCE:
                current_words.append(w)
            else:
                if current_words:
                    lines.append(self._words_to_line(current_words))
                current_words = [w]
                current_y = w["top"]

        if current_words:
            lines.append(self._words_to_line(current_words))

        return lines

    @staticmethod
    def _words_to_line(words: list[dict]) -> tuple[str, list[float]]:
        text = " ".join(w["text"] for w in words)
        x0 = words[0]["x0"]
        x1 = words[-1]["x1"]
        y0 = min(w["top"] for w in words)
        y1 = max(w["bottom"] for w in words)
        return text, [x0, y0, x1, y1]

    # ------------------------------------------------------------------
    # 폰트 기반 헤딩 감지
    # ------------------------------------------------------------------
    def _detect_headings(
        self,
        page: Any,
        text_blocks: list[TextBlock],
        page_number: int,
    ) -> list[HeadingInfo]:
        """페이지의 chars 폰트 크기/볼드 정보를 분석하여 헤딩을 감지한다.

        알고리즘:
        1. page.chars 에서 라인별 대표 폰트 크기를 계산한다.
        2. 페이지 전체 중앙값(median) 대비 _HEADING_SIZE_RATIO 이상인 라인을 헤딩 후보로 선정.
        3. 볼드 폰트 + 짧은 텍스트도 헤딩 후보에 포함.
        4. 헤딩 후보의 폰트 크기를 내림차순 정렬하여 level 을 부여한다.
        """
        try:
            chars = page.chars
            if not chars:
                return []
        except Exception:
            return []

        # 라인별 chars 그룹핑 (Y 좌표 기준)
        line_groups: list[list[dict]] = []
        current_group: list[dict] = []
        current_y: float | None = None

        sorted_chars = sorted(chars, key=lambda c: (c.get("top", 0), c.get("x0", 0)))
        for c in sorted_chars:
            c_top = c.get("top", 0)
            if current_y is None or abs(c_top - current_y) > _Y_TOLERANCE:
                if current_group:
                    line_groups.append(current_group)
                current_group = [c]
                current_y = c_top
            else:
                current_group.append(c)
        if current_group:
            line_groups.append(current_group)

        if not line_groups:
            return []

        # 라인별 대표 폰트 크기 계산 (문자 수 기반 가중 중앙값 대신 최빈 크기 사용)
        line_font_sizes: list[float] = []
        line_texts: list[str] = []
        line_is_bold: list[bool] = []

        for group in line_groups:
            sizes = [c.get("size", 0) for c in group if c.get("text", "").strip()]
            if not sizes:
                line_font_sizes.append(0)
                line_texts.append("")
                line_is_bold.append(False)
                continue

            dominant_size = statistics.median(sizes)
            text = "".join(c.get("text", "") for c in group).strip()
            fontnames = [c.get("fontname", "") for c in group if c.get("text", "").strip()]
            bold = any("Bold" in fn or "bold" in fn for fn in fontnames)

            line_font_sizes.append(dominant_size)
            line_texts.append(text)
            line_is_bold.append(bold)

        # 유효한 폰트 크기만으로 전체 중앙값 계산
        valid_sizes = [s for s in line_font_sizes if s > 0]
        if not valid_sizes:
            return []
        median_size = statistics.median(valid_sizes)

        if median_size <= 0:
            return []

        # 헤딩 후보 선정
        heading_candidates: list[tuple[int, float, str]] = []  # (line_idx, font_size, text)

        for idx, (size, text, bold) in enumerate(
            zip(line_font_sizes, line_texts, line_is_bold)
        ):
            if not text or len(text.split()) > _HEADING_MAX_WORDS:
                continue

            is_large = size >= median_size * _HEADING_SIZE_RATIO
            is_bold_short = bold and len(text.split()) <= 15 and size >= median_size

            if is_large or is_bold_short:
                heading_candidates.append((idx, size, text))

        if not heading_candidates:
            return []

        # 폰트 크기별 레벨 부여 (큰 순서대로 h1, h2, h3)
        unique_sizes = sorted(set(c[1] for c in heading_candidates), reverse=True)
        size_to_level: dict[float, int] = {}
        for i, s in enumerate(unique_sizes[:_HEADING_MAX_LEVELS]):
            size_to_level[s] = i + 1
        # 나머지는 최하위 레벨
        for s in unique_sizes[_HEADING_MAX_LEVELS:]:
            size_to_level[s] = _HEADING_MAX_LEVELS

        # TextBlock 에 heading_level 매핑 (텍스트 매칭)
        heading_text_to_level: dict[str, int] = {}
        for _idx, size, text in heading_candidates:
            level = size_to_level.get(size, _HEADING_MAX_LEVELS)
            heading_text_to_level[text] = level

        for tb in text_blocks:
            stripped = tb.text.strip()
            if stripped in heading_text_to_level:
                tb.heading_level = heading_text_to_level[stripped]

        # HeadingInfo 리스트 생성
        headings: list[HeadingInfo] = []
        for _idx, size, text in heading_candidates:
            level = size_to_level.get(size, _HEADING_MAX_LEVELS)
            # TextBlock 에서 char_offset 찾기
            char_offset = 0
            for tb in text_blocks:
                if tb.text.strip() == text:
                    char_offset = tb.start_char_offset
                    break
            headings.append(
                HeadingInfo(
                    level=level,
                    text=text,
                    page=page_number,
                    char_offset=char_offset,
                )
            )

        return headings

    # ------------------------------------------------------------------
    # 표 추출
    # ------------------------------------------------------------------
    def _extract_tables(self, page: Any, page_number: int) -> list[TableContent]:
        """pdfplumber 의 find_tables 로 표를 추출하고 Markdown 으로 변환한다."""
        results: list[TableContent] = []
        try:
            found = page.find_tables()
            if not found:
                return results

            for t_idx, table_obj in enumerate(found):
                data = table_obj.extract()
                if not data or len(data) < 2:
                    continue

                # 첫 행을 헤더로 사용
                headers = [
                    str(cell).replace("\n", " ").strip() if cell else ""
                    for cell in data[0]
                ]
                rows: list[list[str]] = []
                for row in data[1:]:
                    rows.append(
                        [str(cell).replace("\n", " ").strip() if cell else "" for cell in row]
                    )

                md = self._table_to_markdown(headers, rows)
                bbox_raw = table_obj.bbox
                bbox = (
                    [float(bbox_raw[0]), float(bbox_raw[1]), float(bbox_raw[2]), float(bbox_raw[3])]
                    if bbox_raw
                    else None
                )

                results.append(
                    TableContent(
                        page_number=page_number,
                        table_index=t_idx,
                        headers=headers,
                        rows=rows,
                        markdown=md,
                        confidence=1.0,
                        bbox=bbox,
                    )
                )
        except Exception as exc:
            log.warning("table_extraction_failed", page=page_number, error=str(exc))

        return results

    @staticmethod
    def _table_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            # 열 수 맞추기
            padded = row + [""] * max(0, len(headers) - len(row))
            lines.append("| " + " | ".join(padded[: len(headers)]) + " |")
        return "\n".join(lines)

    @staticmethod
    def _merge_wrapped_table_rows(text: str) -> str:
        """LibreOffice PDF 변환 시 워드랩된 마크다운 테이블 행을 원래 한 줄로 병합한다."""
        lines = text.split('\n')
        merged: list[str] = []
        i = 0
        while i < len(lines):
            stripped = lines[i].rstrip()
            if (stripped.startswith('|')
                    and not stripped.endswith('|')
                    and stripped.count('|') >= 2
                    and '---' not in stripped):
                combined = stripped
                j = i + 1
                while j < len(lines):
                    next_stripped = lines[j].rstrip()
                    if not next_stripped:
                        break
                    if next_stripped.startswith('|') and next_stripped.count('|') >= 2:
                        break
                    combined += ' ' + next_stripped.strip()
                    j += 1
                    if combined.endswith('|'):
                        break
                merged.append(combined)
                i = j
            else:
                merged.append(lines[i])
                i += 1
        return '\n'.join(merged)

    # ------------------------------------------------------------------
    # 이미지 추출
    # ------------------------------------------------------------------
    _image_temp_dir: str | None = None

    def _get_image_temp_dir(self) -> str:
        """이미지 저장용 영구 디렉터리를 생성/반환한다.

        공유 볼륨 `/data/uploads/images/` 하위에 저장하여 API 컨테이너에서도
        서빙 가능하게 한다. 실패 시 /tmp 로 폴백.
        """
        if self._image_temp_dir is None:
            import os as _os
            import uuid as _uuid

            base_dir = "/data/uploads/images"
            try:
                _os.makedirs(base_dir, exist_ok=True)
                # document 단위로 격리된 하위 디렉터리
                subdir = _uuid.uuid4().hex[:16]
                self._image_temp_dir = _os.path.join(base_dir, subdir)
                _os.makedirs(self._image_temp_dir, exist_ok=True)
                log.debug("image_shared_dir_created", path=self._image_temp_dir)
            except Exception as exc:
                # 공유 볼륨 쓰기 실패 시 기존 /tmp 로 폴백
                log.warning("image_shared_dir_failed", error=str(exc))
                self._image_temp_dir = tempfile.mkdtemp(prefix="aicm_pdf_img_")
                log.debug("image_temp_dir_created_fallback", path=self._image_temp_dir)
        return self._image_temp_dir

    def _extract_image_metadata(self, page: Any, page_number: int) -> list[ImageContent]:
        """페이지 내 이미지를 추출하고 임시 파일로 저장한다.

        추출 실패 시 image_path 는 빈 문자열로 유지한다 (graceful degradation).
        """
        results: list[ImageContent] = []
        try:
            images = page.images
            if not images:
                return results

            for img_idx, img in enumerate(images):
                bbox = [
                    float(img.get("x0", 0)),
                    float(img.get("top", 0)),
                    float(img.get("x1", 0)),
                    float(img.get("bottom", 0)),
                ]

                image_path = ""
                try:
                    image_path = self._extract_image_bytes(
                        page, img, page_number, img_idx, bbox
                    )
                except Exception as exc:
                    log.debug(
                        "image_bytes_extraction_failed",
                        page=page_number,
                        image_index=img_idx,
                        error=str(exc),
                    )

                results.append(
                    ImageContent(
                        page_number=page_number,
                        image_index=img_idx,
                        image_path=image_path,
                        bbox=bbox,
                    )
                )
        except Exception as exc:
            log.warning("image_meta_extraction_failed", page=page_number, error=str(exc))

        return results

    def _extract_image_bytes(
        self,
        page: Any,
        img: dict,
        page_number: int,
        img_idx: int,
        bbox: list[float],
    ) -> str:
        """단일 이미지의 바이트를 추출하여 PNG 파일로 저장한다.

        Returns:
            저장된 파일 경로. 실패 시 빈 문자열.
        """
        x0, top, x1, bottom = bbox
        img_width = x1 - x0
        img_height = bottom - top

        # 너무 작은 이미지는 장식 요소로 간주하여 건너뛴다
        if img_width < 20 or img_height < 20:
            return ""

        # pdfplumber crop → to_image 방식으로 이미지 영역 추출
        page_bbox = page.bbox
        crop_x0 = max(x0, page_bbox[0])
        crop_top = max(top, page_bbox[1])
        crop_x1 = min(x1, page_bbox[2])
        crop_bottom = min(bottom, page_bbox[3])

        if crop_x1 <= crop_x0 or crop_bottom <= crop_top:
            return ""

        cropped = page.crop((crop_x0, crop_top, crop_x1, crop_bottom))
        pil_image = cropped.to_image(resolution=150).original

        temp_dir = self._get_image_temp_dir()
        file_name = f"page{page_number}_img{img_idx}.png"
        file_path = str(Path(temp_dir) / file_name)

        pil_image.save(file_path, format="PNG")
        log.debug(
            "image_extracted",
            page=page_number,
            image_index=img_idx,
            path=file_path,
        )
        return file_path

    # ------------------------------------------------------------------
    # 문서 메타데이터
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_pdf_metadata(file_path: str) -> dict:
        metadata: dict[str, Any] = {}
        try:
            with pdfplumber.open(file_path) as pdf:
                info = pdf.metadata or {}
                metadata["title"] = info.get("Title", "")
                metadata["author"] = info.get("Author", "")
                metadata["creator"] = info.get("Creator", "")
                metadata["creation_date"] = info.get("CreationDate", "")
                metadata["page_count"] = len(pdf.pages)
        except Exception:
            pass
        return metadata
