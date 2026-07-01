"""Wave Wire-up Final — DocumentProcessor 의 qa_pair / table_normalize 단계 검증.

env flag KMS_QA_EXTRACT_ENABLED / KMS_TABLE_NORMALIZE_ENABLED 가 true 일 때
respective extractor 가 호출되어 block.metadata 에 결과가 채워지는지 확인.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.pipeline.models.block import BlockObject, BlockType
from src.pipeline.models.document import ProcessingConfig
from src.pipeline.processing.document_processor import DocumentProcessor


def _make_block(content: str, *, metadata: dict | None = None) -> BlockObject:
    return BlockObject(
        id=uuid4(),
        document_id=uuid4(),
        block_type=BlockType.PARAGRAPH if hasattr(BlockType, "PARAGRAPH") else next(iter(BlockType)),
        content=content,
        block_index=0,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_qa_pair_step_wires_when_flag_on(monkeypatch):
    """KMS_QA_EXTRACT_ENABLED=true + LLM 주입 → block.metadata['qa_pairs'] 채워짐."""
    monkeypatch.setenv("KMS_QA_EXTRACT_ENABLED", "true")

    # qa_pair_extractor 가 callable async LLM 을 받아 들임 (test_qa_pair_extractor 와 동일 패턴).
    payload = {
        "pairs": [
            {
                "question": "결제일은 언제인가요?",
                "answer": "T+2 영업일.",
                "confidence": 0.92,
            }
        ]
    }
    mock_llm = AsyncMock(return_value=json.dumps(payload, ensure_ascii=False))

    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=mock_llm)

    long_text = (
        "결제일 관련 안내입니다. 결제일은 T+2 영업일이며, 별도 요청 시 변경이 가능합니다. "
        "다른 문의 사항이 있으면 콜센터로 연락 바랍니다. 그리고 추가 안내 문구가 더 들어갑니다."
    )
    blocks = [_make_block(long_text)]

    out = await processor._maybe_extract_qa_pairs(blocks)
    assert len(out) == 1
    assert "qa_pairs" in out[0].metadata
    pairs = out[0].metadata["qa_pairs"]
    assert len(pairs) == 1
    assert pairs[0]["question"] == "결제일은 언제인가요?"
    assert pairs[0]["confidence"] == pytest.approx(0.92, abs=0.01)


@pytest.mark.asyncio
async def test_qa_pair_step_skipped_when_flag_off(monkeypatch):
    """env flag 미설정/false → extractor 호출 없음 + metadata 변동 없음."""
    monkeypatch.delenv("KMS_QA_EXTRACT_ENABLED", raising=False)

    mock_llm = AsyncMock(return_value="{}")
    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=mock_llm)

    blocks = [_make_block("결제일 관련 본문 텍스트입니다.")]
    out = await processor._maybe_extract_qa_pairs(blocks)
    assert "qa_pairs" not in out[0].metadata
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_table_normalize_step_wires_when_flag_on(monkeypatch):
    """KMS_TABLE_NORMALIZE_ENABLED=true + raw_table 메타 → normalized_table_md 생성."""
    monkeypatch.setenv("KMS_TABLE_NORMALIZE_ENABLED", "true")

    # table_normalizer 의 LLM 응답 — JSON 으로 headers/rows 반환.
    table_payload = {
        "headers": ["항목", "값"],
        "rows": [["결제일", "T+2"], ["수수료", "0.015%"]],
    }
    mock_llm = AsyncMock(return_value=json.dumps(table_payload, ensure_ascii=False))
    processor = DocumentProcessor(config=ProcessingConfig(), llm_client=mock_llm)

    blocks = [
        _make_block(
            "표 본문 컨텍스트.",
            metadata={"raw_table": [["항목", "값"], ["결제일", "T+2"], ["수수료", "0.015%"]]},
        )
    ]

    out = await processor._maybe_normalize_tables(blocks)
    assert len(out) == 1
    md = out[0].metadata.get("normalized_table_md")
    assert md is not None
    # markdown 표 신호: pipe + 헤더 행
    assert "|" in md and "항목" in md
