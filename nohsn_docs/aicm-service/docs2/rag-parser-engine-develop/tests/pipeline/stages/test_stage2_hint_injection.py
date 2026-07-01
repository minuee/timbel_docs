from src.pipeline.stages.stage2_segment import _build_table_hint, _STAGE2_PROMPT_TEMPLATE
from src.pipeline.stages.models import PageData


def test_build_table_hint_lists_detected_regions():
    batch = [
        PageData(page_num=6, image_bytes=b"x", extracted_text="t",
                 detected_tables=[{"bbox": [50, 400, 550, 480], "kind": "box_table", "confidence": 0.8}]),
    ]
    hint = _build_table_hint(batch)
    assert "페이지 6" in hint
    assert "box_table" in hint
    assert "[50" in hint  # bbox 좌표 노출


def test_build_table_hint_empty_when_no_tables():
    batch = [PageData(page_num=1, image_bytes=b"x", extracted_text="t")]
    assert _build_table_hint(batch) == ""


def test_stage2_template_has_table_hint_placeholder():
    assert "{table_hint}" in _STAGE2_PROMPT_TEMPLATE


def test_stage2_template_has_doc_type_hint_placeholder():
    assert "{doc_type_hint}" in _STAGE2_PROMPT_TEMPLATE
