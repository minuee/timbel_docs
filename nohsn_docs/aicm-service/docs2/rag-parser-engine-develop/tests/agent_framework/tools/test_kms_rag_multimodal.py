"""KMSRagTool multimodal retrieve 테스트 — KMS-Plus 2026-05-07.

사용자 절칙: "표나 그림 등의 자료를 보여줘야 답변할 수 있다 — 풀옵션".

검증:
- block_type="table" + metadata.table_markdown 가 있으면 hit 에 markdown_table 필드.
- block_type="image" + metadata.image_path 가 있으면 hit 에 image_url 필드 (URL 변환).
- result.multimodal_blocks 가 표/이미지 list 로 채워짐 (engine 이 SSE emit).
- GPT-5 P0-4 검증 — multimodal_blocks 가 있을 때 _structured_card 는 emit X
  (중복 차단). engine 이 multimodal_blocks 리스트만 보고 frontend 에 push.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agent_framework.tools.kms_rag import KMSRagTool


class _FakeResultItem:
    """SearchResultItem-like — block_type / metadata 포함."""

    def __init__(
        self,
        chunk_id,
        document_id,
        document_title,
        content,
        score,
        *,
        block_type=None,
        metadata=None,
        section_title=None,
    ):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.document_title = document_title
        self.section_title = section_title
        self.content = content
        self.score = score
        self.block_type = block_type
        self.metadata = metadata or {}


class _FakeResponse:
    def __init__(self, results):
        self.results = results


@pytest.mark.asyncio
async def test_table_block_surfaced_to_hit_and_multimodal_blocks():
    """block_type=table + metadata.table_markdown → hit.markdown_table + result.multimodal_blocks."""
    md_table = "| 항목 | 금액 |\n| --- | --- |\n| 입원비 | 50만원 |"
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([
        _FakeResultItem(
            "c1", "d1", "체납 기준",
            "표 1: 체납 기준 ...", 0.9,
            block_type="table",
            metadata={
                "table_markdown": md_table,
                "table_headers": ["항목", "금액"],
            },
        ),
    ]))

    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        got = await tool({"query": "체납 기준 표 보여줘", "top_k": 3})

    assert got["total"] == 1
    h = got["hits"][0]
    assert h["block_type"] == "table"
    assert h["markdown_table"] == md_table
    assert h["table_headers"] == ["항목", "금액"]

    # multimodal_blocks 도 같이 채워짐.
    assert "multimodal_blocks" in got
    assert len(got["multimodal_blocks"]) == 1
    blk = got["multimodal_blocks"][0]
    assert blk["kind"] == "table"
    assert blk["markdown"] == md_table
    assert blk["title"] == "체납 기준"

    # GPT-5 P0-4 — multimodal_blocks 가 있으면 _structured_card 는 set 안 함
    # (engine 이 multimodal list 만 SSE emit, 중복 차단).
    assert "_structured_card" not in got


@pytest.mark.asyncio
async def test_image_block_surfaced_to_hit():
    """block_type=image + metadata.image_path / image_description → hit.image_url + caption."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([
        _FakeResultItem(
            "c1", "d1", "지점 안내도",
            "지점 위치 그림.", 0.7,
            block_type="image",
            metadata={
                "image_path": "https://kms.example.com/img/branch_map.png",
                "image_description": "강남지점 위치도 — 강남역 2번 출구",
                "ocr_text": "강남지점 강남역 2번 출구 도보 5분",
            },
        ),
    ]))

    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        got = await tool({"query": "강남지점 위치 그림"})

    h = got["hits"][0]
    assert h["block_type"] == "image"
    # GPT-5 P0-3 — 외부 URL 은 그대로 통과 (http/https 시작 → no rewrite).
    assert h["image_url"] == "https://kms.example.com/img/branch_map.png"
    assert "강남" in h["image_caption"]
    assert h["ocr_text"].startswith("강남지점")

    # multimodal_blocks
    blk = got["multimodal_blocks"][0]
    assert blk["kind"] == "image"
    assert blk["image_url"] == "https://kms.example.com/img/branch_map.png"

    # GPT-5 P0-4 — multimodal 시 _structured_card 는 emit X (중복 차단).
    assert "_structured_card" not in got


@pytest.mark.asyncio
async def test_no_multimodal_when_text_only():
    """text-only block_type 은 multimodal_blocks / _structured_card 없음 (회귀 0)."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([
        _FakeResultItem(
            "c1", "d1", "일반 본문", "본문 텍스트.", 0.7,
            block_type="paragraph",
            metadata={},
        ),
    ]))

    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        got = await tool({"query": "본문 검색"})

    h = got["hits"][0]
    assert h["block_type"] == "paragraph"
    assert "markdown_table" not in h
    assert "image_url" not in h

    # 결과 dict 도 multimodal 키 없음.
    assert "multimodal_blocks" not in got
    assert "_structured_card" not in got


@pytest.mark.asyncio
async def test_mixed_table_and_image_hits():
    """표 hit + 이미지 hit 둘 다 → multimodal_blocks 에 둘 다 포함, 첫번째가 _structured_card."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([
        _FakeResultItem(
            "c1", "d1", "표 자료", "표.", 0.9,
            block_type="table",
            metadata={"table_markdown": "| a | b |\n|---|---|\n| 1 | 2 |"},
        ),
        _FakeResultItem(
            "c2", "d1", "그림 자료", "그림.", 0.8,
            block_type="image",
            metadata={"image_path": "/img/x.png", "image_description": "x"},
        ),
    ]))

    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        got = await tool({"query": "자료 둘 다"})

    assert len(got["hits"]) == 2
    assert len(got["multimodal_blocks"]) == 2
    kinds = [b["kind"] for b in got["multimodal_blocks"]]
    assert kinds == ["table", "image"]
    # GPT-5 P0-3 — 내부 image_path 는 /api/v1/preview/images URL 로 변환.
    image_blk = got["multimodal_blocks"][1]
    assert image_blk["image_url"].endswith("/img/x.png")
    assert "/api/v1/preview/images/" in image_blk["image_url"]
    # GPT-5 P0-4 — multimodal 시 _structured_card emit X.
    assert "_structured_card" not in got
