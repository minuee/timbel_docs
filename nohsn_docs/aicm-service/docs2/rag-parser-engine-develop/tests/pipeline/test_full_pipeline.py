"""``process_document_full`` 통합 테스트.

검증 (사용자 절칙, 2026-05-07):
1. 풀옵션 — vision/stage1/noise/type/chunker 모두 거침
2. ``2-16-5. 전출입. AS-요금정산 문의`` → document_type=faq + Q&A chunk
3. ``1-5. 전화상담시 유의사항`` → document_type=manual + semantic chunk
4. processing_meta 풍부 (모든 단계 결과)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.full_pipeline import process_document_full


@pytest.fixture
def faq_md_path() -> Path:
    p = (
        Path(__file__).resolve().parents[2]
        / "에이전트 기본 자료"
        / "03_삼천리가스"
        / "2_VOC상담스크립트"
        / "2-16-5. 전출입. AS-요금정산 문의.md"
    )
    if not p.exists():
        pytest.skip(f"sample missing: {p}")
    return p


@pytest.fixture
def manual_md_path() -> Path:
    p = (
        Path(__file__).resolve().parents[2]
        / "에이전트 기본 자료"
        / "03_삼천리가스"
        / "1_전화상담전준비"
        / "1-5. 전화상담시 유의사항.md"
    )
    if not p.exists():
        pytest.skip(f"sample missing: {p}")
    return p


class TestFAQProcessing:
    """FAQ 자료 — 절칙 핵심 검증."""

    @pytest.mark.asyncio
    async def test_faq_recognized_and_chunked(self, faq_md_path):
        """전출입 자료 → faq 분류 + Q&A 쌍 단위 chunk."""
        result = await process_document_full(
            title="2-16-5. 전출입. AS-요금정산 문의",
            file_path=faq_md_path,
            llm_client=None,  # heuristic fallback (FAQ 패턴 명백)
            upload_source="test",
        )

        # 풀옵션 단계 모두 거쳤는지
        assert result.parser, "parser 미기록"
        assert result.processing_meta.get("vision"), "vision_gate 미실행"
        assert result.processing_meta.get("stage1"), "Stage1 미실행"
        assert result.processing_meta.get("noise"), "noise_filter 미실행"
        assert result.processing_meta.get("chunker"), "chunker 미실행"

        # FAQ 인지 — 절칙
        assert result.document_type == "faq", (
            f"FAQ 인지 실패 — document_type={result.document_type}. "
            "절칙: 전출입 자료는 FAQ 형태로 인지되어야."
        )
        assert result.chunker_strategy == "faq", (
            f"chunker strategy={result.chunker_strategy} (faq 기대)"
        )
        # Q&A 쌍 충분
        assert result.chunker_qa_pairs >= 10, (
            f"Q&A 쌍 {result.chunker_qa_pairs} 개 — 최소 10 기대"
        )
        # has_qa_pairs flag 가 풍부 메타에 기록
        assert result.has_qa_pairs is True

        # block + chunk 수
        assert len(result.blocks) > 0
        assert len(result.chunks) >= 10


class TestManualProcessing:
    @pytest.mark.asyncio
    async def test_manual_uses_semantic_strategy(self, manual_md_path):
        """1-5. 전화상담시 유의사항 → manual 또는 other (heuristic)."""
        result = await process_document_full(
            title="1-5. 전화상담시 유의사항",
            file_path=manual_md_path,
            llm_client=None,
            upload_source="test",
        )

        # FAQ 가 아니어야 함
        assert result.document_type != "faq", (
            f"manual 자료가 FAQ 로 분류됨 — {result.document_type}"
        )
        # heuristic fallback 시 'other' → semantic_default 또는 manual_semantic
        assert result.chunker_strategy in (
            "manual_semantic",
            "semantic_default",
        ), f"chunker strategy={result.chunker_strategy}"

        assert len(result.chunks) > 0


class TestMarkdownTextInput:
    """markdown_text 직접 입력 (chat upload / auto-draft) 시나리오."""

    @pytest.mark.asyncio
    async def test_text_input(self):
        md = (
            "# 회의록 2026-05-07\n\n"
            "참석자: A, B, C\n\n"
            "## 안건\n\n"
            "KMS 풀옵션 pipeline 도입 — TypeAwareChunker.\n\n"
            "## 결정\n\n"
            "1. faq Q&A 쌍 chunker 추가\n"
            "2. 모든 ingest endpoint 통일\n"
        )
        result = await process_document_full(
            title="회의록 2026-05-07",
            markdown_text=md,
            llm_client=None,
            document_type_hint="memo",
            upload_source="auto_draft",
        )

        assert result.document_type == "memo"
        assert result.chunker_strategy == "memo_paragraph"
        assert len(result.chunks) >= 1
        assert result.processing_meta["upload_source"] == "auto_draft"


class TestProcessingMeta:
    """풀옵션 단계가 모두 meta 에 기록되는지."""

    @pytest.mark.asyncio
    async def test_all_stages_recorded(self, faq_md_path):
        result = await process_document_full(
            title="meta test",
            file_path=faq_md_path,
            llm_client=None,
            upload_source="test",
        )
        meta = result.processing_meta

        # 필수 키 — spec 정의대로
        assert "pipeline_version" in meta
        assert "parser" in meta
        assert meta["vision"]["use_vision"] in (True, False)
        assert "reason" in meta["vision"]
        assert "stage1" in meta
        assert "has_qa_pairs" in meta["stage1"]
        assert meta["noise"]["content_blocks_count"] > 0
        assert "noise_blocks_count" in meta["noise"]
        assert meta["document_type"]["classified"] == "faq"
        assert "confidence" in meta["document_type"]
        assert "reason" in meta["document_type"]
        assert meta["chunker"]["strategy"] == "faq"
        assert meta["chunker"]["qa_pairs_count"] >= 10
        assert meta["chunker"]["avg_chunk_chars"] > 0
        assert meta["embedding_model"] == "BGE-M3"
        assert "elapsed_ms" in meta
        assert "processed_at" in meta
