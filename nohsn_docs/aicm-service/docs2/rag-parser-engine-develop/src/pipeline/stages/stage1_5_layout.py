"""Stage1.5 LayoutMapper — 파싱맵 구성.

pdfplumber 의 find_tables() 로 경계선 있는 격자 표를 1차 추출 (confidence=1.0),
vision LLM 으로 박스형 인포그래픽을 보강 (Task 4).
"""
from __future__ import annotations

from src.common.logging import get_logger
from src.pipeline.stages.layout_map import DetectedTable, ParseMap
from src.pipeline.stages.llm_client import VisionLLMClient

log = get_logger(__name__)

_BOX_DETECT_PROMPT = """이 페이지 이미지에서 '박스형 도표' 영역을 찾으세요.

박스형 도표 = 테두리 박스 안에 N개의 항목/열이 시각적으로 배치되어 의미를 담는 구조
(예: 3개 법령을 나란히 박스로, 단계별 책임 매트릭스, N-column 비교표).
일반 문단/리스트는 제외.

JSON 배열만 반환. 좌표는 페이지 좌상단 기준 [x0, y0, x1, y1]:
[{"bbox": [x0, y0, x1, y1], "confidence": 0.0~1.0}]
없으면 []"""


class LayoutMapper:
    def __init__(self, vision_client: VisionLLMClient) -> None:
        self._client = vision_client

    def _extract_grid_tables(self, pdf: pdfplumber.PDF, page_nums: list[int]) -> ParseMap:
        """pdfplumber find_tables() — 경계선 격자 표. confidence=1.0 (vector 근거)."""
        pm = ParseMap()
        for pn in page_nums:
            try:
                page = pdf.pages[pn - 1]
            except IndexError:
                continue
            for tbl in page.find_tables():
                x0, y0, x1, y1 = tbl.bbox
                pm.add(pn, DetectedTable(
                    bbox=[float(x0), float(y0), float(x1), float(y1)],
                    kind="grid_table",
                    confidence=1.0,
                ))
        return pm

    async def _augment_box_tables(
        self, pm: ParseMap, page_images: dict[int, bytes], page_nums: list[int]
    ) -> None:
        """vision LLM 으로 박스형 인포그래픽 영역 보강."""
        for pn in page_nums:
            img = page_images.get(pn)
            if not img:
                continue
            try:
                raw = await self._client.call(
                    prompt=_BOX_DETECT_PROMPT,
                    images=[img],
                    max_tokens=512,
                    task="layout_mapping",
                )
                parsed = self._client.parse_json(raw)
            except Exception as exc:  # noqa: BLE001 — 보강 실패는 치명 X
                log.warning("layout_box_detect_failed", page=pn, error=str(exc))
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                bbox = item.get("bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                try:
                    parsed_bbox = [float(v) for v in bbox]
                    conf = float(item.get("confidence", 0.5))
                except (TypeError, ValueError):
                    continue
                pm.add(pn, DetectedTable(
                    bbox=parsed_bbox,
                    kind="box_table",
                    confidence=conf,
                ))

    async def map(
        self, pdf_path: str, page_images: dict[int, bytes], page_nums: list[int]
    ) -> ParseMap:
        """파싱맵 구성 진입점 — grid 1차 + box 보강.

        grid 추출 (pdfplumber) 실패는 비치명 — 빈 ParseMap 으로 시작하고 box 보강 계속.
        """
        import pdfplumber  # lazy import — optional dependency
        pm = ParseMap()
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pm = self._extract_grid_tables(pdf, page_nums)
        except Exception as exc:  # noqa: BLE001 — grid 추출 실패는 비치명 (box 보강은 계속)
            log.warning("layout_grid_extract_failed", pdf_path=pdf_path, error=str(exc))
        await self._augment_box_tables(pm, page_images, page_nums)
        log.info("layout_map_complete", pages=len(page_nums),
                 total_tables=sum(len(v) for v in pm.by_page.values()))
        return pm
