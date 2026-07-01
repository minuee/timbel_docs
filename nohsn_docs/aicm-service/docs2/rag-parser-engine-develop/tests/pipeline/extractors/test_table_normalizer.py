"""TableNormalizer 단위 테스트.

LLM mock — raw → structured 추론은 LLM 책임. 본 테스트는 어댑터·markdown
렌더·예외 처리 경로만 검증.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.pipeline.extractors.table_normalizer import (
    NormalizedTable,
    TableNormalizer,
)


def _llm(payload: dict | str) -> AsyncMock:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return AsyncMock(return_value=text)


@pytest.mark.asyncio
async def test_normalize_simple_table_renders_markdown():
    """평범한 헤더+행 표 → markdown 문자열 (헤더, 구분선, 행) 포함."""
    mock = _llm(
        {
            "headers": ["연도", "매출액"],
            "rows": [["2023", "100억"], ["2024", "150억"]],
        }
    )
    norm = TableNormalizer(llm_client=mock)
    md = await norm.normalize(
        raw_table=[["연도", "매출액"], ["2023", "100억"], ["2024", "150억"]],
        context="연도별 매출 추이",
    )

    assert "| 연도 | 매출액 |" in md
    assert "|---|---|" in md
    assert "| 2023 | 100억 |" in md
    assert "| 2024 | 150억 |" in md


@pytest.mark.asyncio
async def test_normalize_with_merged_cells_and_inconsistent_rows():
    """LLM 이 합리적으로 헤더 정리하고 빈 셀을 '—' 로 채운 응답을 그대로 사용."""
    mock = _llm(
        {
            "headers": ["분류", "항목", "비율"],
            "rows": [
                ["주식", "코스피", "60%"],
                ["주식", "코스닥", "—"],
                ["채권", "국채", "—"],
            ],
        }
    )
    norm = TableNormalizer(llm_client=mock)
    md = await norm.normalize(
        raw_table=[
            ["분류", "항목", "비율"],
            ["주식", "코스피", "60%"],
            ["", "코스닥", ""],
            ["채권", "국채", ""],
        ],
    )

    assert "| 주식 | 코스피 | 60% |" in md
    assert "| 주식 | 코스닥 | — |" in md  # rowspan 합치기 + 빈셀 마커
    assert "| 채권 | 국채 | — |" in md


@pytest.mark.asyncio
async def test_empty_table_returns_empty():
    """빈 raw_table → LLM 호출 없이 빈 문자열."""
    mock = AsyncMock()
    norm = TableNormalizer(llm_client=mock)
    assert await norm.normalize(raw_table=[]) == ""
    assert await norm.normalize(raw_table=[[]]) == ""
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_returns_empty_string():
    """LLM 예외 → 빈 문자열 반환 (파이프라인 안정성)."""
    failing = AsyncMock(side_effect=RuntimeError("LLM down"))
    norm = TableNormalizer(llm_client=failing)
    md = await norm.normalize(raw_table=[["a", "b"], ["1", "2"]])
    assert md == ""


@pytest.mark.asyncio
async def test_pipe_in_cell_is_escaped():
    """셀 안 '|' 문자가 markdown 표 깨지지 않게 escape 되는지 확인."""
    mock = _llm(
        {
            "headers": ["항목", "값"],
            "rows": [["수익|손실", "3억"]],
        }
    )
    norm = TableNormalizer(llm_client=mock)
    md = await norm.normalize(raw_table=[["a", "b"], ["c", "d"]])
    assert "&#124;" in md  # | 가 escape 됨
    assert "수익&#124;손실" in md


@pytest.mark.asyncio
async def test_normalize_to_struct_returns_object():
    """markdown 대신 구조 객체 가져오기."""
    mock = _llm(
        {"headers": ["a", "b"], "rows": [["1", "2"]]}
    )
    norm = TableNormalizer(llm_client=mock)
    struct = await norm.normalize_to_struct(raw_table=[["a", "b"], ["1", "2"]])
    assert isinstance(struct, NormalizedTable)
    assert struct.headers == ("a", "b")
    assert struct.rows == (("1", "2"),)
