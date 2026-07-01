"""D47 §C — load_blocks_from_cache 의 source_location sanitize 회귀.

목적:
- DB 의 source_location.heading_path 에 None 원소가 있어도 1건 실패가
  전체를 무산시키지 않고, 정상 블럭은 로드되는지 확인.
- _sanitize_source_location 단위 동작 회귀.
"""

from __future__ import annotations

from src.pipeline.workers.block_worker import _sanitize_source_location


def test_sanitize_empty_dict() -> None:
    assert _sanitize_source_location({}) == {}


def test_sanitize_none_returns_empty() -> None:
    assert _sanitize_source_location(None) == {}


def test_sanitize_filters_none_in_heading_path() -> None:
    src = {
        "page_number": 10,
        "heading_path": ["A", None, "B"],
    }
    out = _sanitize_source_location(src)
    assert out["heading_path"] == ["A", "B"]
    assert out["page_number"] == 10


def test_sanitize_all_none_heading_path() -> None:
    src = {"heading_path": [None, None]}
    out = _sanitize_source_location(src)
    assert out["heading_path"] == []


def test_sanitize_non_list_heading_path() -> None:
    """heading_path 가 비-list (예: str) 면 [] 로 normalize."""
    src = {"heading_path": "not a list"}
    out = _sanitize_source_location(src)
    assert out["heading_path"] == []


def test_sanitize_preserves_other_fields() -> None:
    src = {
        "page_number": 5,
        "heading_path": ["title"],
        "bbox": [1.0, 2.0, 3.0, 4.0],
    }
    out = _sanitize_source_location(src)
    assert out["page_number"] == 5
    assert out["heading_path"] == ["title"]
    assert out["bbox"] == [1.0, 2.0, 3.0, 4.0]


def test_sanitize_empty_string_in_heading() -> None:
    src = {"heading_path": ["", "real", "  "]}
    out = _sanitize_source_location(src)
    assert out["heading_path"] == ["real"]


def test_sanitize_does_not_mutate_input() -> None:
    """원본 dict 를 변경하지 않는지 (불변성 회귀 가드)."""
    src = {"heading_path": ["A", None, "B"]}
    original = dict(src)
    _sanitize_source_location(src)
    assert src == original
