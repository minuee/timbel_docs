"""Stage1.5 파싱맵 — 페이지별 표/도표 영역 좌표 맵.

LayoutMapper 가 채우고, Stage2 가 hint 로 소비한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DetectedTable(BaseModel):
    """감지된 표/도표 영역 한 건."""

    bbox: list[float]  # [x0, y0, x1, y1] — PDF point 좌표
    kind: str  # "grid_table" (경계선 있는 격자) | "box_table" (박스형 인포그래픽)
    confidence: float


class ParseMap(BaseModel):
    """문서 전체의 파싱맵 — page_num -> [DetectedTable]."""

    by_page: dict[int, list[DetectedTable]] = Field(default_factory=dict)

    def add(self, page_num: int, table: DetectedTable) -> None:
        self.by_page.setdefault(page_num, []).append(table)

    def tables_for_page(self, page_num: int) -> list[DetectedTable]:
        return self.by_page.get(page_num, [])
