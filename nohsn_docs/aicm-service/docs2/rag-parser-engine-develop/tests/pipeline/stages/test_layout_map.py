"""Tests for PageData.detected_tables field."""

from __future__ import annotations

from src.pipeline.stages.models import PageData


def test_pagedata_detected_tables_default_empty():
    """PageData should have detected_tables field defaulting to empty list."""
    pd = PageData(page_num=1, image_bytes=b"x", extracted_text="t")
    assert pd.detected_tables == []


def test_pagedata_detected_tables_accepts_list():
    """PageData should accept detected_tables parameter with table data."""
    pd = PageData(
        page_num=1, image_bytes=b"x", extracted_text="t",
        detected_tables=[{"bbox": [0, 0, 100, 50], "kind": "box_table", "confidence": 0.9}],
    )
    assert pd.detected_tables[0]["kind"] == "box_table"
    assert pd.detected_tables[0]["confidence"] == 0.9


from src.pipeline.stages.layout_map import DetectedTable, ParseMap


def test_detected_table_fields():
    dt = DetectedTable(bbox=[0, 0, 100, 50], kind="box_table", confidence=0.85)
    assert dt.kind == "box_table"
    assert dt.confidence == 0.85


def test_parsemap_page_lookup():
    pm = ParseMap()
    pm.add(page_num=3, table=DetectedTable(bbox=[1, 2, 3, 4], kind="grid_table", confidence=0.9))
    assert len(pm.tables_for_page(3)) == 1
    assert pm.tables_for_page(99) == []


from unittest.mock import MagicMock
from src.pipeline.stages.stage1_5_layout import LayoutMapper


def test_layout_mapper_extracts_grid_tables_from_pdfplumber():
    # pdfplumber page mock — find_tables 가 격자를 반환
    fake_page = MagicMock()
    fake_page.rects = [
        {"x0": 10, "top": 10, "x1": 200, "bottom": 100},
    ]
    fake_page.find_tables.return_value = [
        MagicMock(bbox=(10, 10, 200, 100)),
    ]
    fake_pdf = MagicMock()
    fake_pdf.pages = [fake_page]

    mapper = LayoutMapper(vision_client=MagicMock())
    pm = mapper._extract_grid_tables(fake_pdf, page_nums=[1])
    assert len(pm.tables_for_page(1)) == 1
    assert pm.tables_for_page(1)[0].kind == "grid_table"
    assert pm.tables_for_page(1)[0].confidence == 1.0


def test_layout_mapper_vision_detects_box_tables():
    from unittest.mock import AsyncMock
    import asyncio

    vision = MagicMock()
    vision.call = AsyncMock(return_value='[{"bbox": [50, 400, 550, 480], "confidence": 0.8}]')
    vision.parse_json.return_value = [{"bbox": [50, 400, 550, 480], "confidence": 0.8}]

    mapper = LayoutMapper(vision_client=vision)
    pm = ParseMap()
    asyncio.run(mapper._augment_box_tables(pm, page_images={6: b"img"}, page_nums=[6]))
    boxes = [t for t in pm.tables_for_page(6) if t.kind == "box_table"]
    assert len(boxes) == 1
    assert boxes[0].confidence == 0.8


def test_augment_box_tables_skips_malformed_items():
    from unittest.mock import AsyncMock
    import asyncio

    vision = MagicMock()
    # parsed 가 list 지만 원소가 dict 아님 / bbox 비정상 / confidence 비숫자
    vision.call = AsyncMock(return_value="x")
    vision.parse_json.return_value = [
        "not a dict",
        {"bbox": [1, 2, 3]},  # len != 4
        {"bbox": ["a", "b", "c", "d"], "confidence": 0.5},  # non-numeric bbox
        {"bbox": [10, 20, 30, 40], "confidence": "bad"},  # non-numeric confidence
        {"bbox": [10, 20, 30, 40], "confidence": 0.7},  # valid
    ]
    mapper = LayoutMapper(vision_client=vision)
    pm = ParseMap()
    asyncio.run(mapper._augment_box_tables(pm, page_images={1: b"img"}, page_nums=[1]))
    boxes = pm.tables_for_page(1)
    assert len(boxes) == 1  # valid 1개만
    assert boxes[0].confidence == 0.7
