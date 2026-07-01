"""TypeAwareChunker 테스트.

검증 대상 (사용자 절칙, 2026-05-07):
1. ``2-16-5. 전출입. AS-요금정산 문의`` 같은 자료가 *FAQ 형태로 인지* 되어
   질문/MENT 쌍 단위 chunk 로 나뉘어야 한다.
2. ``1-5. 전화상담시 유의사항`` 같은 자료는 manual 전략으로 SemanticBlockMerger
   가 의미 단위 chunk 를 생성한다.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.pipeline.chunkers.type_aware_chunker import (
    TypeAwareChunker,
    detect_faq_pattern,
)
from scripts.seed.semantic_block_merger import InputBlock


# ── 픽스처 — 실제 자료 기반 ────────────────────────────────────────────


def _build_blocks_from_md(md_text: str) -> list[InputBlock]:
    """간단한 markdown → InputBlock 변환 (테스트 전용).

    `# heading` / `## heading` / paragraph 만 인식. reseed 의 정식 파이프라인이
    아니므로 정확하진 않지만 chunker 기능 검증엔 충분.
    """
    blocks: list[InputBlock] = []
    cur_para: list[str] = []
    idx = 0

    def flush_para() -> None:
        nonlocal idx, cur_para
        if cur_para:
            content = "\n".join(cur_para).strip()
            if content:
                blocks.append(
                    InputBlock(
                        block_id=uuid4(),
                        block_type="paragraph",
                        content=content,
                        block_index=idx,
                    )
                )
                idx += 1
            cur_para = []

    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            flush_para()
            blocks.append(
                InputBlock(
                    block_id=uuid4(),
                    block_type="heading_1",
                    content=stripped[2:].strip(),
                    block_index=idx,
                )
            )
            idx += 1
        elif stripped.startswith("## "):
            flush_para()
            blocks.append(
                InputBlock(
                    block_id=uuid4(),
                    block_type="heading_2",
                    content=stripped[3:].strip(),
                    block_index=idx,
                )
            )
            idx += 1
        elif stripped:
            cur_para.append(stripped)
        else:
            flush_para()
    flush_para()

    # FAQ 자료의 경우 list item 한 줄이 별도 paragraph 로 들어가도록 split.
    # (실제 MarkdownParser 는 list item 을 별도 block 으로 다루지 않을 수 있어
    #  여기서는 *질문* / *MENT* 패턴이 같은 paragraph 안에 묶여 있으면 분리.)
    refined: list[InputBlock] = []
    for b in blocks:
        if b.block_type == "paragraph" and (
            "**질문" in b.content or "**MENT" in b.content
        ):
            # 줄 단위로 다시 분해
            lines = [ln.strip() for ln in b.content.split("\n") if ln.strip()]
            cur: list[str] = []
            for ln in lines:
                if (
                    ln.startswith("- **질문")
                    or ln.startswith("**질문")
                    or ln.startswith("- **MENT")
                    or ln.startswith("**MENT")
                ):
                    if cur:
                        refined.append(
                            InputBlock(
                                block_id=uuid4(),
                                block_type="paragraph",
                                content="\n".join(cur).strip(),
                                block_index=len(refined),
                            )
                        )
                        cur = []
                    # leading "- " 제거
                    cur.append(ln.lstrip("- ").strip())
                else:
                    cur.append(ln)
            if cur:
                refined.append(
                    InputBlock(
                        block_id=uuid4(),
                        block_type="paragraph",
                        content="\n".join(cur).strip(),
                        block_index=len(refined),
                    )
                )
        else:
            b.block_index = len(refined)
            refined.append(b)
    return refined


@pytest.fixture
def faq_blocks() -> list[InputBlock]:
    """FAQ 형식 — 2-16-5. 전출입. AS-요금정산 문의."""
    md_path = (
        Path(__file__).resolve().parents[2]
        / "에이전트 기본 자료"
        / "03_삼천리가스"
        / "2_VOC상담스크립트"
        / "2-16-5. 전출입. AS-요금정산 문의.md"
    )
    if not md_path.exists():
        pytest.skip(f"sample missing: {md_path}")
    return _build_blocks_from_md(md_path.read_text(encoding="utf-8"))


@pytest.fixture
def manual_blocks() -> list[InputBlock]:
    """manual 형식 — 1-5. 전화상담시 유의사항."""
    md_path = (
        Path(__file__).resolve().parents[2]
        / "에이전트 기본 자료"
        / "03_삼천리가스"
        / "1_전화상담전준비"
        / "1-5. 전화상담시 유의사항.md"
    )
    if not md_path.exists():
        pytest.skip(f"sample missing: {md_path}")
    return _build_blocks_from_md(md_path.read_text(encoding="utf-8"))


# ── 테스트 ────────────────────────────────────────────────────────────


class TestFAQDetection:
    """detect_faq_pattern — 자동 인지 휴리스틱."""

    def test_faq_pattern_recognized(self, faq_blocks):
        """전출입 AS-요금정산 문의 — Q&A 쌍이 ≥3 회 발견."""
        count = detect_faq_pattern(faq_blocks)
        assert count >= 3, (
            f"FAQ 패턴 인지 실패 — Q&A 쌍 {count} 개 발견 (기대 ≥3). "
            "사용자 절칙: '2-16-5. 전출입. AS-요금정산 문의' 가 FAQ 형태로 인지되어야."
        )

    def test_manual_not_faq(self, manual_blocks):
        """manual 자료는 Q&A 쌍이 ≤2 (FAQ 아님)."""
        count = detect_faq_pattern(manual_blocks)
        assert count < 3, (
            f"manual 자료가 FAQ 로 잘못 인지됨 (Q&A {count} 개). "
            "1-5. 전화상담시 유의사항 은 manual 이어야 함."
        )


class TestFAQChunker:
    """FAQ 전략 — Q&A 쌍 단위 chunk."""

    def test_faq_chunks_per_qa_pair(self, faq_blocks):
        """전출입 자료 — 질문 N 개 → 약 N 개 chunk (헤더는 첫 chunk 흡수)."""
        chunker = TypeAwareChunker(min_chars=80, max_chars=2000)
        result = chunker.chunk(faq_blocks, document_type="faq")

        assert result.strategy == "faq"
        # 질문 패턴이 15개 정도 있음. 짧은 chunk 흡수로 약간 줄 수 있어 ≥10
        assert len(result.chunks) >= 10, (
            f"Q&A chunk 수 부족 ({len(result.chunks)}). "
            "전출입 자료는 질문1~15 → 최소 10+ chunk 기대."
        )
        # 각 chunk 가 질문 패턴을 포함해야 (헤더 단독 chunk 는 첫 Q&A 와 병합됨)
        q_chunks = sum(
            1 for c in result.chunks if "질문" in c.content or "MENT" in c.content
        )
        assert q_chunks >= len(result.chunks) - 1

    def test_faq_chunk_contains_question_and_answer(self, faq_blocks):
        """첫 chunk 가 헤더 + 질문1 + MENT1 을 모두 포함해야."""
        chunker = TypeAwareChunker(min_chars=80, max_chars=2000)
        result = chunker.chunk(faq_blocks, document_type="faq")

        first_chunk = result.chunks[0]
        # 헤더 흡수 — 주요내용/Key word 포함
        assert "주요내용" in first_chunk.content or "전출입" in first_chunk.content
        # 질문1 + MENT1 본문 포함
        assert "질문1" in first_chunk.content
        assert "MENT" in first_chunk.content


class TestManualChunker:
    """manual 전략 — SemanticBlockMerger."""

    def test_manual_strategy_uses_semantic_merger(self, manual_blocks):
        chunker = TypeAwareChunker(min_chars=200, max_chars=1800)
        result = chunker.chunk(manual_blocks, document_type="manual")

        assert result.strategy == "manual_semantic"
        assert len(result.chunks) > 0
        # manual 은 의미 단위 그룹핑 — 보통 5~10 chunk
        assert 1 <= len(result.chunks) <= 20


class TestAutoFAQOverride:
    """document_type='other' 라도 FAQ 패턴이 강하면 자동으로 FAQ 전략 적용."""

    def test_auto_promote_other_to_faq(self, faq_blocks):
        chunker = TypeAwareChunker(min_chars=80, max_chars=2000)
        result = chunker.chunk(faq_blocks, document_type="other")

        # FAQ 패턴이 명백 → 자동 promote
        assert result.strategy == "faq", (
            f"FAQ 자동 인지 실패 — strategy={result.strategy}. "
            "사용자 절칙: 분류기가 'other' 를 줘도 본문 패턴이 명백하면 FAQ 처리."
        )


class TestParagraphStrategy:
    """memo / email — 단락 단위."""

    def test_memo_creates_short_chunks(self):
        blocks = [
            InputBlock(uuid4(), "heading_1", "회의록 2026-05-07", 0),
            InputBlock(uuid4(), "paragraph", "참석자: A, B, C", 1),
            InputBlock(
                uuid4(),
                "paragraph",
                "안건: KMS 풀옵션 pipeline. " * 5,
                2,
            ),
            InputBlock(uuid4(), "paragraph", "결정: TypeAwareChunker 도입.", 3),
        ]
        chunker = TypeAwareChunker(min_chars=100, max_chars=1800)
        result = chunker.chunk(blocks, document_type="memo")

        assert result.strategy == "memo_paragraph"
        assert len(result.chunks) >= 2  # 단락 단위로 여러 chunk


class TestChapterStrategy:
    """report / research_note — 챕터(heading_1) boundary."""

    def test_report_chunks_per_chapter(self):
        blocks = [
            InputBlock(uuid4(), "heading_1", "1. 배경", 0),
            InputBlock(uuid4(), "paragraph", "2025년 KMS 검색 품질 분석.", 1),
            InputBlock(uuid4(), "heading_1", "2. 분석", 2),
            InputBlock(uuid4(), "paragraph", "FAQ 자료가 의미 단위 분할되지 않음.", 3),
            InputBlock(uuid4(), "heading_1", "3. 결론", 4),
            InputBlock(uuid4(), "paragraph", "TypeAwareChunker 도입 권고.", 5),
        ]
        chunker = TypeAwareChunker(min_chars=10, max_chars=2000)
        result = chunker.chunk(blocks, document_type="report")

        assert result.strategy == "report_chapter"
        # heading_1 3 개 → 3 chunks
        assert len(result.chunks) == 3
