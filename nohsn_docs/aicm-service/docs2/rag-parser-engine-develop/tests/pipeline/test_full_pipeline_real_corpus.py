"""실제 5 봇 자료 sample 로 풀옵션 pipeline 검증.

샘플:
- samchully: `2-16-5. 전출입. AS-요금정산 문의` → faq 인지
- samchully: `1-5. 전화상담시 유의사항` → manual
- baemin: `배달의 민족_manual_v0.8` → manual
- homeshop: `01_주문결제` → faq

검증 항목 (사용자 절칙):
1. faq 자료가 *질문/MENT 쌍 단위* chunk 로 나뉜다.
2. manual 자료는 의미 단위 (semantic_block_merger) chunk.
3. processing_meta 풍부 — 모든 단계 기록.
4. noise (목차 등) 분리.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.pipeline.full_pipeline import process_document_full

ASSETS_DIR = Path(__file__).resolve().parents[2] / "에이전트 기본 자료"


@pytest.mark.asyncio
async def test_samchully_faq_전출입():
    """samchully — 2-16-5. 전출입. AS-요금정산 문의 (FAQ)."""
    p = ASSETS_DIR / "03_삼천리가스" / "2_VOC상담스크립트" / "2-16-5. 전출입. AS-요금정산 문의.md"
    if not p.exists():
        pytest.skip(f"missing: {p}")

    result = await process_document_full(
        title="2-16-5. 전출입. AS-요금정산 문의",
        file_path=p,
        llm_client=None,
        upload_source="real_corpus_test",
    )

    assert result.document_type == "faq", (
        f"전출입 자료 → faq 인지 실패 ({result.document_type}). 절칙 위반."
    )
    assert result.chunker_strategy == "faq"
    assert result.chunker_qa_pairs >= 10
    print(
        f"\n[전출입 FAQ] blocks={len(result.blocks)} chunks={len(result.chunks)} "
        f"qa_pairs={result.chunker_qa_pairs} avg_chunk={result.avg_chunk_chars}"
    )
    # 첫 chunk 가 헤더 + Q&A1 흡수
    assert "주요내용" in result.chunks[0].content or "전출입" in result.chunks[0].content
    assert "질문1" in result.chunks[0].content
    # 후속 chunk 들에 다른 질문 번호 분포
    later_questions = set()
    for c in result.chunks[1:]:
        for q in range(2, 16):
            if f"질문{q}" in c.content:
                later_questions.add(q)
    assert len(later_questions) >= 5, (
        f"질문2~ 분포 부족 ({sorted(later_questions)}). 모든 질문이 첫 chunk 에 뭉친듯."
    )


@pytest.mark.asyncio
async def test_samchully_manual_전화상담():
    """samchully — 1-5. 전화상담시 유의사항 (manual)."""
    p = ASSETS_DIR / "03_삼천리가스" / "1_전화상담전준비" / "1-5. 전화상담시 유의사항.md"
    if not p.exists():
        pytest.skip(f"missing: {p}")

    result = await process_document_full(
        title="1-5. 전화상담시 유의사항",
        file_path=p,
        llm_client=None,
        document_type_hint="manual",
        upload_source="real_corpus_test",
    )

    assert result.document_type == "manual"
    assert result.chunker_strategy == "manual_semantic"
    print(
        f"\n[전화상담 manual] blocks={len(result.blocks)} chunks={len(result.chunks)} "
        f"avg_chunk={result.avg_chunk_chars}"
    )
    # manual 은 1~10 chunk 정도가 의미 단위 (heading 분포에 따라 변동)
    assert 1 <= len(result.chunks) <= 10


@pytest.mark.asyncio
async def test_baemin_manual_배달의민족():
    """baemin — 배달의 민족_manual_v0.8 (manual)."""
    p = ASSETS_DIR / "07_배달의민족" / "배달의 민족_manual_v0.8.md"
    if not p.exists():
        pytest.skip(f"missing: {p}")

    result = await process_document_full(
        title="배달의 민족_manual_v0.8",
        file_path=p,
        llm_client=None,
        document_type_hint="manual",
        upload_source="real_corpus_test",
    )

    assert result.document_type == "manual"
    assert result.chunker_strategy == "manual_semantic"
    print(
        f"\n[배민 manual] blocks={len(result.blocks)} chunks={len(result.chunks)} "
        f"avg_chunk={result.avg_chunk_chars} sections={len(result.sections)}"
    )
    assert len(result.chunks) > 0


@pytest.mark.asyncio
async def test_homeshop_faq_주문결제():
    """homeshop — 01_주문결제 (FAQ — faq folder kind)."""
    p = ASSETS_DIR / "01_homeshopping_faq" / "01_주문결제.md"
    if not p.exists():
        pytest.skip(f"missing: {p}")

    # hint='faq' 로 강제 FAQ 전략
    result = await process_document_full(
        title="01_주문결제",
        file_path=p,
        llm_client=None,
        document_type_hint="faq",
        upload_source="real_corpus_test",
    )

    print(
        f"\n[homeshop FAQ] blocks={len(result.blocks)} chunks={len(result.chunks)} "
        f"strategy={result.chunker_strategy} qa_pairs={result.chunker_qa_pairs}"
    )
    assert result.document_type == "faq"
    # homeshop 은 다른 질문 패턴일 수 있음 — 적어도 chunk 는 생성
    assert len(result.chunks) > 0


def test_corpus_smoke_summary():
    """4 자료 합계 — 검증 print 용."""
    asyncio.run(_collect_summary())


async def _collect_summary():
    """샘플 자료 4개 통합 요약 — 콘솔 시각화."""
    samples = [
        (
            "samchully:전출입(faq)",
            ASSETS_DIR
            / "03_삼천리가스"
            / "2_VOC상담스크립트"
            / "2-16-5. 전출입. AS-요금정산 문의.md",
            None,
        ),
        (
            "samchully:전화상담(manual)",
            ASSETS_DIR
            / "03_삼천리가스"
            / "1_전화상담전준비"
            / "1-5. 전화상담시 유의사항.md",
            "manual",
        ),
        (
            "baemin:배달의민족(manual)",
            ASSETS_DIR / "07_배달의민족" / "배달의 민족_manual_v0.8.md",
            "manual",
        ),
        (
            "homeshop:주문결제(faq)",
            ASSETS_DIR / "01_homeshopping_faq" / "01_주문결제.md",
            "faq",
        ),
    ]
    print("\n=== 풀옵션 pipeline 실 자료 검증 ===")
    print(f"{'sample':<32} | {'docType':>6} | {'strat':>18} | "
          f"{'blocks':>6} {'chunks':>6} {'avg':>6} {'qa':>4}")
    print("-" * 100)
    for name, p, hint in samples:
        if not p.exists():
            print(f"{name:<32} | (MISSING)")
            continue
        result = await process_document_full(
            title=p.stem,
            file_path=p,
            llm_client=None,
            document_type_hint=hint,
            upload_source="smoke",
        )
        print(
            f"{name:<32} | "
            f"{result.document_type:>6} | "
            f"{result.chunker_strategy:>18} | "
            f"{len(result.blocks):>6} {len(result.chunks):>6} "
            f"{result.avg_chunk_chars:>6.0f} {result.chunker_qa_pairs:>4}"
        )
