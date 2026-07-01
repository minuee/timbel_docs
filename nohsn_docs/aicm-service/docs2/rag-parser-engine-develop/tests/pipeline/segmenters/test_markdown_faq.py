from __future__ import annotations

from src.pipeline.segmenters.markdown_faq import (
    _question_form,
    detect_question_level,
    is_markdown_structured,
)


def test_question_form_q_prefix():
    assert _question_form("Q. CMA수익률은 어떻게 되나요") is True


def test_question_form_question_mark():
    assert _question_form("매장 칭찬하기가 무엇인가요?") is True


def test_question_form_korean_ending_no_qmark():
    # 다이소: 물음표 없이 평서형 어미로 끝나는 질문
    assert _question_form("다이소 모바일 상품권 유효기간을 연장하고 싶어요.") is True


def test_question_form_declarative_answer_is_false():
    assert _question_form("다이소 모바일상품권은 카드결제만 가능합니다.") is False


def test_is_markdown_structured_true():
    assert is_markdown_structured("### a\n### b\n### c") is True


def test_is_markdown_structured_false_plain():
    assert is_markdown_structured("그냥 평문\n두 번째 줄\n세 번째 줄") is False


def test_detect_question_level_hantoo_three_levels():
    text = "# 제목\n## CMA\n### Q. 수익률은 어떻게 되나요\n답변\n### Q. 유형 변경하고 싶어요\n답변2"
    assert detect_question_level(text) == 3


def test_detect_question_level_daiso_single_level():
    text = "### 결제수단은 무엇인가요?\n답변A\n---\n### 유효기간을 연장하고 싶어요.\n답변B"
    assert detect_question_level(text) == 3


def test_detect_question_level_general_doc_returns_none():
    # 일반 문서: 가장 깊은 레벨 헤딩이 질문형이 아님 → None
    text = "# 매뉴얼\n## 설치\n### 사전 준비\n내용\n### 설치 절차\n내용"
    assert detect_question_level(text) is None


# ── Task 2: segment_markdown_text ──
from uuid import uuid4

from src.pipeline.models.block import BlockType
from src.pipeline.segmenters.markdown_faq import segment_markdown_text


def _types(blocks):
    return [b.block_type for b in blocks]


def test_segment_daiso_single_level_qna_only():
    text = (
        "### 다이소 상품권 구매가능한 결제수단은 무엇인가요?\n"
        "다이소 모바일상품권은 카드결제만 가능합니다.\n"
        "---\n"
        "### 다이소 모바일 상품권 유효기간을 연장하고 싶어요.\n"
        "고객센터(1688-9876)로 신청 가능합니다."
    )
    blocks = segment_markdown_text(text, document_id=uuid4())
    assert _types(blocks) == [BlockType.QNA, BlockType.QNA]
    assert blocks[0].metadata["qna_title"] == "다이소 상품권 구매가능한 결제수단은 무엇인가요?"
    assert blocks[0].content == "다이소 모바일상품권은 카드결제만 가능합니다."
    # 불변식: content에 질문/마커 없음
    assert "###" not in blocks[0].content
    assert "무엇인가요" not in blocks[0].content
    assert blocks[1].metadata["qna_title"] == "다이소 모바일 상품권 유효기간을 연장하고 싶어요."


def test_segment_hantoo_three_levels():
    text = (
        "# 한국투자증권 고객 FAQ — 지식문서 (Part 1)\n"
        "---\n"
        "## CMA\n"
        "### Q. CMA수익률은 어떻게 되나요\n"
        "[분류] 대분류: CMA / 세부분류: 수익률\n"
        "MMW 투자형은 영업점 문의\n"
        "---\n"
        "### Q. CMA유형을 변경하고 싶어요\n"
        "CMA 해지 후 재신청하세요."
    )
    blocks = segment_markdown_text(text, document_id=uuid4())
    assert _types(blocks) == [
        BlockType.HEADING_1,
        BlockType.HEADING_2,
        BlockType.QNA,
        BlockType.QNA,
    ]
    assert blocks[0].content == "한국투자증권 고객 FAQ — 지식문서 (Part 1)"
    assert blocks[1].content == "CMA"
    assert blocks[2].metadata["qna_title"] == "Q. CMA수익률은 어떻게 되나요"
    assert blocks[2].content.startswith("[분류] 대분류: CMA")
    assert "###" not in blocks[2].content
    assert [b.block_index for b in blocks] == [0, 1, 2, 3]
    assert all(b.block_hash for b in blocks)
    # heading_path 전파: QnA 가 상위 카테고리(CMA)를 컨텍스트 경로로 가진다.
    _title = "한국투자증권 고객 FAQ — 지식문서 (Part 1)"
    assert blocks[0].source_location.heading_path == []
    assert blocks[1].source_location.heading_path == [_title]
    assert blocks[2].source_location.heading_path == [_title, "CMA"]
    assert blocks[3].source_location.heading_path == [_title, "CMA"]


def test_segment_general_doc_keeps_headings_and_paragraphs():
    # detect_question_level=None → 모든 헤딩이 heading, 본문은 paragraph
    text = "# 매뉴얼\n## 설치\n### 사전 준비\n준비 내용입니다.\n### 설치 절차\n절차 내용입니다."
    blocks = segment_markdown_text(text, document_id=uuid4())
    assert BlockType.QNA not in _types(blocks)
    assert BlockType.HEADING_3 in _types(blocks)
    assert BlockType.PARAGRAPH in _types(blocks)


# ── Task 3: segment() 라우팅 통합 ──
import asyncio
from unittest.mock import patch

import src.pipeline.segmenters.markdown_faq as mdf
from src.pipeline.models.document import ProcessingConfig
from src.pipeline.models.parse_result import PageContent, ParseResult
from src.pipeline.segmenters.llm_block_segmenter import LLMBlockSegmenter


def test_segment_routes_markdown_faq_to_deterministic():
    # llm_client 가 있어도(=gemma 사용 가능) 마크다운 FAQ면 결정적 경로(segment_markdown_text)로
    # 분기해야 한다. 카테고리(`## CMA`)가 heading_2 로 나오는 건 결정적 경로만의 특징.
    text = (
        "## CMA\n"
        "### 결제수단은 무엇인가요?\n카드결제만 가능합니다.\n"
        "---\n### 환불받고 싶어요\n고객센터로 신청 가능합니다.\n"
        "---\n### 재발급 받고 싶어요\n5회까지 가능합니다."
    )
    pr = ParseResult(pages=[PageContent(page_number=1, text=text)])
    seg = LLMBlockSegmenter(ProcessingConfig(), llm_client=object())

    with patch.object(mdf, "segment_markdown_text", wraps=mdf.segment_markdown_text) as spy:
        blocks = asyncio.run(seg.segment(pr, document_id=uuid4()))

    spy.assert_called_once()  # 결정적 경로가 실제로 선택됨
    assert blocks[0].block_type == BlockType.HEADING_2
    assert blocks[0].content == "CMA"
    qna = [b for b in blocks if b.block_type == BlockType.QNA]
    assert len(qna) == 3
    assert qna[0].metadata["qna_title"] == "결제수단은 무엇인가요?"
