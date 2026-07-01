"""3단계 LLM 파이프라인 오케스트레이터.

전체 흐름:
1. PDF 페이지 렌더링 (pypdfium2로 이미지 생성)
2. Stage 1: 문서 이해 (첫 3페이지)
3. Stage 2: 블럭 분할 (5페이지씩 배치)
4. 노이즈 필터링
5. Stage 3: 상세 처리 (table/image만)
6. StageResult 반환
"""

from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path

from src.common.config import settings
from src.common.logging import get_logger
from src.pipeline.stages.llm_client import VisionLLMClient
from src.pipeline.stages.models import DocumentContext, PageData, RawBlock, StageResult
from src.pipeline.stages.stage1_understand import DocumentUnderstanding
from src.pipeline.stages.stage1_5_layout import LayoutMapper
from src.pipeline.stages.stage2_segment import BlockSegmentation
from src.pipeline.stages.stage3_enrich import BlockEnrichment

log = get_logger(__name__)

# PDF 렌더링 해상도 (DPI)
_RENDER_DPI = 150


class LLMPipeline:
    """3단계 LLM 문서 처리 파이프라인."""

    def __init__(
        self,
        model: str | None = None,
        vllm_url: str | None = None,
    ) -> None:
        _vllm_url = vllm_url or settings.VLLM_URL
        _model = model or settings.VLLM_MODEL

        if not _vllm_url:
            raise ValueError("VLLM_URL이 설정되어 있지 않습니다.")

        self._client = VisionLLMClient(
            api_key="not-needed",
            model=_model,
            base_url=f"{_vllm_url}/v1" if not _vllm_url.endswith("/v1") else _vllm_url,
        )
        self._stage1 = DocumentUnderstanding(self._client)
        self._stage1_5 = LayoutMapper(self._client)
        self._stage2 = BlockSegmentation(self._client)
        self._stage3 = BlockEnrichment(self._client)

    async def process(
        self,
        pdf_path: str,
        page_range: tuple[int, int] | None = None,
        is_ppt: bool = False,
    ) -> StageResult:
        """문서를 3단계로 처리한다.

        Args:
            pdf_path: PDF 파일 경로.
            page_range: 처리할 페이지 범위 (1-based, inclusive). None이면 전체.
            is_ppt: PPT/PPTX 변환본 여부. True 면 Stage1 이 첫 3페이지가 아닌
                **전체 슬라이드 썸네일 몽타주**를 보고 문서를 이해한다 (슬라이드
                순서가 곧 의미 순서가 아니므로 전체 맥락이 필수).

        Returns:
            StageResult: 문서 컨텍스트 + 블럭 + 노이즈 블럭 + 통계.
        """
        total_start = time.monotonic()
        file_path = Path(pdf_path)

        if not file_path.exists():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

        log.info("pipeline_start", pdf_path=pdf_path, page_range=page_range)

        # ---------------------------------------------------------------
        # 0. PDF 페이지 렌더링 + 텍스트 추출
        # ---------------------------------------------------------------
        stage_start = time.monotonic()
        page_images, page_texts = await self._render_pdf(pdf_path, page_range)
        render_ms = int((time.monotonic() - stage_start) * 1000)

        if not page_images:
            log.warning("pipeline_no_pages", pdf_path=pdf_path)
            return StageResult(
                document_context=DocumentContext(),
                blocks=[],
                noise_blocks=[],
                stats={"render_ms": render_ms, "total_pages": 0},
            )

        total_pages = len(page_images)
        page_nums = sorted(page_images.keys())
        log.info("pdf_rendered", total_pages=total_pages, render_ms=render_ms)

        # ---------------------------------------------------------------
        # 1. Stage 1: 문서 이해
        # - 일반: 첫 3페이지로 제목/유형/노이즈 패턴 파악
        # - PPT: 전체 슬라이드(최대 12장) 썸네일을 한 번에 보고 전체 맥락 파악
        # ---------------------------------------------------------------
        stage_start = time.monotonic()
        if is_ppt:
            # PPT 는 슬라이드 순서가 의미 순서가 아니므로 전체를 함께 본다.
            # vLLM 이미지 입력 한도(요청당 4장 권장)를 고려해 최대 12장까지
            # 균등 샘플링; 너무 많으면 시간/토큰 부담.
            ppt_sample_pages = _sample_pages_for_overview(page_nums, max_count=12)
            stage1_inputs = [page_images[pn] for pn in ppt_sample_pages]
            context = await self._stage1.analyze(stage1_inputs, is_ppt=True)
        else:
            first_pages = [page_images[pn] for pn in page_nums[:3]]
            context = await self._stage1.analyze(first_pages)
        stage1_ms = int((time.monotonic() - stage_start) * 1000)

        log.info(
            "stage1_done",
            ms=stage1_ms,
            doc_type=context.document_type,
            is_ppt=is_ppt,
        )

        # ---------------------------------------------------------------
        # 1.5. Stage 1.5: 파싱맵 구성 — 표/도표 영역 좌표 (실패는 비치명, 빈 맵으로 진행)
        # ---------------------------------------------------------------
        try:
            parse_map = await self._stage1_5.map(pdf_path, page_images, page_nums)
        except Exception as _pm_exc:  # noqa: BLE001 — Stage1.5 실패는 비치명
            log.warning("stage1_5_layout_failed", error=str(_pm_exc))
            from src.pipeline.stages.layout_map import ParseMap as _ParseMap
            parse_map = _ParseMap()

        # ---------------------------------------------------------------
        # 2. Stage 2: 블럭 분할 (5페이지씩 배치)
        # ---------------------------------------------------------------
        stage_start = time.monotonic()
        pages_data: list[PageData] = []
        for pn in page_nums:
            pages_data.append(
                PageData(
                    page_num=pn,
                    image_bytes=page_images[pn],
                    extracted_text=page_texts.get(pn, ""),
                    detected_tables=[
                        t.model_dump() for t in parse_map.tables_for_page(pn)
                    ],
                )
            )

        all_blocks = await self._stage2.segment_all(pages_data, context)
        stage2_ms = int((time.monotonic() - stage_start) * 1000)

        log.info("stage2_done", ms=stage2_ms, total_blocks=len(all_blocks))

        # ---------------------------------------------------------------
        # 3. 노이즈 필터링
        # ---------------------------------------------------------------
        content_blocks: list[RawBlock] = []
        noise_blocks: list[RawBlock] = []

        for block in all_blocks:
            if block.type == "noise":
                noise_blocks.append(block)
            elif not block.content.strip():
                noise_blocks.append(
                    RawBlock(
                        type="noise",
                        content=block.content,
                        page=block.page,
                        reason="빈 콘텐츠",
                    )
                )
            else:
                content_blocks.append(block)

        log.info(
            "noise_filtered",
            content_blocks=len(content_blocks),
            noise_blocks=len(noise_blocks),
        )

        # ---------------------------------------------------------------
        # 3.5 블럭 후처리: 짧은 블럭 합치기 + RAG 최적화
        # ---------------------------------------------------------------
        content_blocks = _merge_short_blocks(content_blocks)

        log.info(
            "blocks_merged",
            after_merge=len(content_blocks),
        )

        # ---------------------------------------------------------------
        # 4. Stage 3: 상세 처리 (table/image만)
        # ---------------------------------------------------------------
        stage_start = time.monotonic()
        enriched_blocks = await self._stage3.enrich_all(
            content_blocks, page_images, context
        )
        stage3_ms = int((time.monotonic() - stage_start) * 1000)

        log.info("stage3_done", ms=stage3_ms)

        # ---------------------------------------------------------------
        # 5. 결과 조합
        # ---------------------------------------------------------------
        total_ms = int((time.monotonic() - total_start) * 1000)

        # 블럭 타입별 통계
        type_counts: dict[str, int] = {}
        for b in enriched_blocks:
            type_counts[b.type] = type_counts.get(b.type, 0) + 1

        stats = {
            "total_pages": total_pages,
            "total_blocks": len(enriched_blocks),
            "noise_blocks": len(noise_blocks),
            "type_counts": type_counts,
            "render_ms": render_ms,
            "stage1_ms": stage1_ms,
            "stage2_ms": stage2_ms,
            "stage3_ms": stage3_ms,
            "total_ms": total_ms,
        }

        log.info(
            "pipeline_complete",
            total_ms=total_ms,
            blocks=len(enriched_blocks),
            noise=len(noise_blocks),
            type_counts=type_counts,
        )

        return StageResult(
            document_context=context,
            blocks=enriched_blocks,
            noise_blocks=noise_blocks,
            stats=stats,
        )

    async def _render_pdf(
        self,
        pdf_path: str,
        page_range: tuple[int, int] | None,
    ) -> tuple[dict[int, bytes], dict[int, str]]:
        """PDF를 페이지별 PNG 이미지 + 텍스트로 변환.

        pypdfium2로 이미지 렌더링, pdfplumber로 텍스트 추출.

        Returns:
            (page_images, page_texts): page_num -> PNG bytes, page_num -> text
        """
        return await asyncio.to_thread(self._render_pdf_sync, pdf_path, page_range)

    @staticmethod
    def _render_pdf_sync(
        pdf_path: str,
        page_range: tuple[int, int] | None,
    ) -> tuple[dict[int, bytes], dict[int, str]]:
        """동기 PDF 렌더링 (스레드풀에서 실행)."""
        import pdfplumber
        import pypdfium2

        page_images: dict[int, bytes] = {}
        page_texts: dict[int, str] = {}

        # pypdfium2로 이미지 렌더링
        pdf_pdfium = pypdfium2.PdfDocument(pdf_path)
        try:
            total = len(pdf_pdfium)

            if page_range:
                start_page = max(1, page_range[0])
                end_page = min(total, page_range[1])
            else:
                start_page = 1
                end_page = total

            for page_idx in range(start_page - 1, end_page):
                page_num = page_idx + 1
                try:
                    page = pdf_pdfium[page_idx]
                    bitmap = page.render(scale=_RENDER_DPI / 72)
                    pil_image = bitmap.to_pil()

                    buf = io.BytesIO()
                    pil_image.save(buf, format="PNG", optimize=True)
                    page_images[page_num] = buf.getvalue()
                    buf.close()
                except Exception as e:
                    log.warning("page_render_failed", page=page_num, error=str(e))
        finally:
            pdf_pdfium.close()

        # pdfplumber로 텍스트 추출
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_idx in range(start_page - 1, min(end_page, len(pdf.pages))):
                    page_num = page_idx + 1
                    try:
                        text = pdf.pages[page_idx].extract_text() or ""
                        page_texts[page_num] = text
                    except Exception as e:
                        log.warning("page_text_failed", page=page_num, error=str(e))
                        page_texts[page_num] = ""
        except Exception as e:
            log.warning("pdfplumber_open_failed", error=str(e))

        return page_images, page_texts


# ---------------------------------------------------------------------------
# 후처리: 짧은 블럭 합치기 + RAG 최적화
# ---------------------------------------------------------------------------

_MIN_BLOCK_CHARS = 50  # 이 이하면 인접 블럭과 합침
_HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}


def _sample_pages_for_overview(
    page_nums: list[int], max_count: int
) -> list[int]:
    """전체 페이지에서 균등 간격으로 max_count 개를 샘플링한다.

    PPT Stage1 입력용 — 첫/마지막을 항상 포함하며 사이를 균등 분포로 채운다.
    페이지 수가 max_count 이하면 전체 반환.
    """
    if not page_nums:
        return []
    if len(page_nums) <= max_count:
        return list(page_nums)
    if max_count <= 1:
        return [page_nums[0]]
    # 균등 간격 인덱스
    step = (len(page_nums) - 1) / (max_count - 1)
    indices = sorted({int(round(i * step)) for i in range(max_count)})
    return [page_nums[i] for i in indices if 0 <= i < len(page_nums)]


def _merge_short_blocks(blocks: list[RawBlock]) -> list[RawBlock]:
    """짧은 블럭을 인접 블럭과 합치고, heading에 컨텍스트를 부여한다.

    규칙:
    1. heading 블럭 → 다음 paragraph/list 블럭의 contextual_heading으로 연결
       (heading 자체는 유지 — 문서 검색에서 위치 마커로 사용)
    2. 50자 미만의 paragraph → 인접 paragraph와 합침
    3. table/image/code/callout은 합치지 않음 (독립 단위)
    """
    if not blocks:
        return blocks

    merged: list[RawBlock] = []
    i = 0

    while i < len(blocks):
        block = blocks[i]

        # heading → properties에 다음 블럭 미리보기 추가 (RAG 벡터화 시 사용)
        if block.type in _HEADING_TYPES:
            # 다음 블럭이 있으면 heading의 properties에 컨텍스트 추가
            if i + 1 < len(blocks):
                next_block = blocks[i + 1]
                if next_block.type not in _HEADING_TYPES | {"noise", "divider"}:
                    # heading에 다음 본문의 첫 200자를 컨텍스트로 부여
                    block.properties["next_context"] = next_block.content[:200]
            merged.append(block)
            i += 1
            continue

        # 짧은 paragraph → 다음 paragraph와 합침
        if (
            block.type == "paragraph"
            and len(block.content.strip()) < _MIN_BLOCK_CHARS
            and i + 1 < len(blocks)
            and blocks[i + 1].type == "paragraph"
        ):
            next_block = blocks[i + 1]
            merged_block = RawBlock(
                type="paragraph",
                content=block.content.strip() + "\n\n" + next_block.content.strip(),
                page=block.page,
                keywords=block.keywords + next_block.keywords,
                properties=block.properties,
            )
            merged.append(merged_block)
            i += 2  # 두 블럭을 하나로
            continue

        merged.append(block)
        i += 1

    return merged
