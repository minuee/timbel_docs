"""D47 §B — heading_propagator._set_heading_path None 필터 회귀.

목적:
- stack[:level-1] 슬라이스가 None 슬롯을 포함해도 SourceLocation 검증을 깨지
  않도록 _set_heading_path 가 None / 빈 문자열을 사전 제거하는지 확인.
- 회귀 가드: 정상 입력은 그대로 통과.
"""

from __future__ import annotations

import uuid

import pytest

from src.pipeline.enrichers.heading_propagator import _set_heading_path
from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import SourceLocation


def _make_block() -> BlockObject:
    return BlockObject(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        block_type=BlockType.PARAGRAPH,
        content="x",
        block_index=0,
        block_hash="h",
        token_count=1,
        source_location=SourceLocation(),
        metadata={},
    )


def test_set_heading_path_filters_none() -> None:
    """None 원소가 섞인 path 를 안전하게 정리."""
    block = _make_block()
    _set_heading_path(block, ["A", None, "B"])  # type: ignore[list-item]
    assert block.source_location.heading_path == ["A", "B"]


def test_set_heading_path_filters_empty_string() -> None:
    """빈 문자열 / whitespace-only 원소 제거."""
    block = _make_block()
    _set_heading_path(block, ["", "  ", "title"])
    assert block.source_location.heading_path == ["title"]


def test_set_heading_path_all_none() -> None:
    """전체가 None 이어도 [] 로 안전 set — pydantic 검증 통과."""
    block = _make_block()
    _set_heading_path(block, [None, None])  # type: ignore[list-item]
    assert block.source_location.heading_path == []


def test_set_heading_path_normal_unchanged() -> None:
    """정상 입력 회귀 가드 — 동작 변경 없음."""
    block = _make_block()
    _set_heading_path(block, ["1. 서론", "1.1 배경"])
    assert block.source_location.heading_path == ["1. 서론", "1.1 배경"]


def test_set_heading_path_empty_list() -> None:
    """빈 list 회귀 가드."""
    block = _make_block()
    _set_heading_path(block, [])
    assert block.source_location.heading_path == []


def test_set_heading_path_coerces_non_str() -> None:
    """비-str 값도 str 캐스팅 후 통과 (pydantic 검증 깨지지 않음)."""
    block = _make_block()
    _set_heading_path(block, [123, "abc"])  # type: ignore[list-item]
    assert block.source_location.heading_path == ["123", "abc"]
