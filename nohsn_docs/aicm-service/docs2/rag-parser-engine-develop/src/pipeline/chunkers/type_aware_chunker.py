"""TypeAwareChunker — document_type 기반 6 전략 chunker.

★ 사용자 절칙 (2026-05-07):
    "2-16-5. 전출입. AS-요금정산 문의 그래야 이런 문서도 FAQ 형태라고 인지 하고
     질문 답변으로 블럭 처리 하고 청크로 나눈단 말이야"

→ 풀옵션 KMS pipeline 의 핵심 — document_type 을 인지해 *의미 단위* chunk 를
  만든다. 단순 heading 기반 chunking 이 아니라 문서 유형별 특성에 맞춰:

  - **faq** : Q&A 쌍 단위 (질문 heading + MENT/답변 paragraph 묶음 → 1 chunk)
  - **manual** : SemanticBlockMerger (KSS+cosine 의미 그룹핑) — 기존 v3 default
  - **presentation** : 슬라이드 단위 (page 경계로 chunk 분리)
  - **memo / email** : 단락 단위 (paragraph 1~2개씩 작은 chunk)
  - **report / research_note** : 챕터 단위 (heading_1 boundary)
  - **other** : SemanticBlockMerger fallback

원칙 (제 1원칙 — 하드코딩 금지):
    chunker 안에서 키워드 enum X. document_type 은 *상위* 단계
    (Stage1 LLM + DocumentTypeClassifier) 가 의미적으로 결정 → 본 모듈은 *전략
    선택* 만 담당.

trace 가능:
    모든 strategy 의 결과 chunk 는 ``MergedChunk`` 형식 — source_block_ids /
    cluster_id 보존. metadata.strategy 로 어느 path 를 탔는지 검증 가능.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from src.pipeline.models.chunking import InputBlock, MergedChunk
from src.pipeline.processing.semantic_block_merger import SemanticBlockMerger

# ── 상수 ──────────────────────────────────────────────────────────────────

# 6+1 카테고리 (document_type_classifier 와 일치 + faq 추가)
SUPPORTED_TYPES = frozenset(
    {"faq", "manual", "presentation", "memo", "email", "report", "research_note", "other"}
)

# FAQ Q&A 쌍 패턴.
# 한국 콜센터/FAQ 자료의 빈번한 형식:
#   1) "**질문1:** ..." / "**MENT:** ..." (삼천리가스)
#   2) "### ?로 끝나는 질문 heading + 다음 paragraph 가 답변" (homeshop 등)
#   3) 영문 "Q. ... A. ..."
_FAQ_QUESTION_RE = re.compile(
    r"^\s*(?:\*\*)?(?:질문\s*\d+|Q[.:\s]|문[.:\s]|Question\s*\d*[.:\s])",
    re.IGNORECASE | re.MULTILINE,
)
_FAQ_ANSWER_RE = re.compile(
    r"^\s*(?:\*\*)?(?:MENT|답변|A[.:\s]|Answer[.:\s])",
    re.IGNORECASE | re.MULTILINE,
)
# heading 자체가 질문문 ("?" 끝 + 짧은 길이) 인 경우 — homeshop 형식.
# 50자 이하 + 물음표로 끝나는 heading → 질문 boundary 로 인지.
_FAQ_HEADING_QUESTION_MAX_CHARS = 80


# ── 입력 / 출력 데이터 ────────────────────────────────────────────────────


@dataclass
class ChunkerResult:
    """TypeAwareChunker 출력 — chunk 목록 + 사용된 전략."""

    chunks: list[MergedChunk]
    strategy: str
    qa_pairs_count: int = 0
    avg_chunk_chars: float = 0.0
    notes: str = ""


# ── 메인 chunker ──────────────────────────────────────────────────────────


@dataclass
class TypeAwareChunker:
    """document_type-aware chunker.

    Args:
        merger: SemanticBlockMerger (manual/other default 용). None 이면 기본값.
        min_chars / max_chars: 강제 split 제약 (모든 전략 공통).
        faq_min_qa_chars: FAQ chunk 의 최소 길이 (질문+답변 합쳐 이 미만이면
            인접 Q&A 와 병합).
    """

    merger: SemanticBlockMerger | None = None
    min_chars: int = 200
    max_chars: int = 1800
    faq_min_qa_chars: int = 60

    def __post_init__(self) -> None:
        if self.merger is None:
            self.merger = SemanticBlockMerger(
                min_chars=self.min_chars, max_chars=self.max_chars
            )

    # ------------------------------------------------------------------ entry
    def chunk(
        self,
        blocks: Sequence[InputBlock],
        *,
        document_type: str = "other",
        page_per_block: dict[UUID, int] | None = None,
    ) -> ChunkerResult:
        """document_type 에 맞는 전략으로 block 을 chunk 로 변환한다.

        Args:
            blocks: InputBlock 목록 (block_id, block_type, content, block_index).
            document_type: 6+1 카테고리 (faq/manual/presentation/memo/email/
                report/research_note/other). 알 수 없으면 SemanticBlockMerger.
            page_per_block: presentation 전략용 — block_id → page_number map.

        Returns:
            ChunkerResult — chunks + 전략 메타.
        """
        if not blocks:
            return ChunkerResult(chunks=[], strategy="empty")

        dt = (document_type or "other").strip().lower()

        # FAQ 패턴 자동 인지 — document_type 이 'other' 라도 본문이 명백한 FAQ 면
        # FAQ 전략을 적용. heuristic: 질문/답변 쌍이 3회 이상 반복.
        if dt not in SUPPORTED_TYPES or dt == "other":
            if detect_faq_pattern(blocks) >= 3:
                dt = "faq"

        if dt == "faq":
            chunks = self._chunk_faq(blocks)
            qa_count = len(chunks)
            return ChunkerResult(
                chunks=chunks,
                strategy="faq",
                qa_pairs_count=qa_count,
                avg_chunk_chars=_avg_chars(chunks),
                notes=f"Q&A 쌍 {qa_count} 개 추출",
            )

        if dt == "manual":
            chunks = self._chunk_manual(blocks)
            return ChunkerResult(
                chunks=chunks,
                strategy="manual_semantic",
                avg_chunk_chars=_avg_chars(chunks),
            )

        if dt == "presentation":
            chunks = self._chunk_presentation(blocks, page_per_block)
            return ChunkerResult(
                chunks=chunks,
                strategy="presentation_slide",
                avg_chunk_chars=_avg_chars(chunks),
            )

        if dt in ("memo", "email"):
            chunks = self._chunk_paragraph(blocks)
            return ChunkerResult(
                chunks=chunks,
                strategy=f"{dt}_paragraph",
                avg_chunk_chars=_avg_chars(chunks),
            )

        if dt in ("report", "research_note"):
            chunks = self._chunk_chapter(blocks)
            return ChunkerResult(
                chunks=chunks,
                strategy=f"{dt}_chapter",
                avg_chunk_chars=_avg_chars(chunks),
            )

        # default — semantic merger
        chunks = self.merger.merge(list(blocks))
        return ChunkerResult(
            chunks=chunks,
            strategy="semantic_default",
            avg_chunk_chars=_avg_chars(chunks),
        )

    # ─────────────────────────────────────────────────────────────── strategies

    def _chunk_faq(self, blocks: Sequence[InputBlock]) -> list[MergedChunk]:
        """FAQ 전략 — 질문/답변 쌍 단위 chunk.

        규칙:
        1. 질문 패턴 (`질문N:`, `Q.`, `Q:`, `문.`) 으로 시작하는 block 을 boundary 로.
        2. boundary 부터 다음 boundary 직전까지 묶어 1 chunk.
        3. 최상단 metadata block (주요내용/Key word 등) 은 첫 Q&A 에 prefix 로 흡수.
        4. 너무 짧은 (< faq_min_qa_chars) chunk 는 인접 Q&A 와 병합.
        5. max_chars 초과 시 SemanticBlockMerger 의 _force_split 로 강제 분할.

        예시 (`2-16-5. 전출입. AS-요금정산 문의`):
            heading_1: "2-16-5. 전출입. AS-요금정산 문의"
            paragraph: "주요내용: ... Key word: ..."
            paragraph: "**질문1:** 요금정산은 어떻게 합니까?"
            paragraph: "**MENT:** (네~) 저희 직원이 ..."
            paragraph: "**질문2:** 빌트인 세대인데 요금정산은 어떻게 합니까?"
            paragraph: "**MENT:** 이사 나가시는날 ..."

        → chunk[0]: 헤더 + 질문1+MENT1
           chunk[1]: 질문2+MENT2
           ... (질문N 단위로 N개 chunk)
        """
        # 1) 헤더 영역 (heading + metadata) 와 Q&A 영역 분리
        header_blocks: list[InputBlock] = []
        body_blocks: list[InputBlock] = list(blocks)

        first_q_idx = -1
        for i, b in enumerate(body_blocks):
            if _is_question_block(b):
                first_q_idx = i
                break

        if first_q_idx > 0:
            header_blocks = body_blocks[:first_q_idx]
            body_blocks = body_blocks[first_q_idx:]
        elif first_q_idx == -1:
            # 질문 패턴 1개도 없음 → semantic fallback (faq 분류 오인일 가능성)
            return self.merger.merge(list(blocks))

        # 2) Q&A 쌍 단위 그룹핑
        groups: list[list[InputBlock]] = []
        cur: list[InputBlock] = []
        for b in body_blocks:
            if _is_question_block(b):
                if cur:
                    groups.append(cur)
                cur = [b]
            else:
                cur.append(b)
        if cur:
            groups.append(cur)

        # 3) 헤더는 첫 그룹 prefix
        if header_blocks and groups:
            groups[0] = header_blocks + groups[0]

        # 4) 너무 짧은 그룹 흡수 — 다음 그룹과 병합
        merged: list[list[InputBlock]] = []
        i = 0
        while i < len(groups):
            g = groups[i]
            text_len = sum(len(b.content) for b in g)
            if (
                text_len < self.faq_min_qa_chars
                and i + 1 < len(groups)
            ):
                merged.append(g + groups[i + 1])
                i += 2
                continue
            merged.append(g)
            i += 1

        # 5) chunk 생성 — max_chars 초과 시 force_split
        chunks: list[MergedChunk] = []
        for group in merged:
            cluster_id = uuid4()
            text = self._join_blocks(group)
            if len(text) <= self.max_chars:
                chunks.append(self._make_chunk(text, group, cluster_id, len(chunks)))
                continue
            # 강제 split
            for piece, piece_blocks in self.merger._force_split(text, group):
                chunks.append(
                    self._make_chunk(piece, piece_blocks, cluster_id, len(chunks))
                )

        # chunk_index 재정렬
        for i, c in enumerate(chunks):
            c.chunk_index = i

        return chunks

    def _chunk_manual(self, blocks: Sequence[InputBlock]) -> list[MergedChunk]:
        """manual 전략 — SemanticBlockMerger 그대로 (절차서/매뉴얼/SOP)."""
        return self.merger.merge(list(blocks))

    def _chunk_presentation(
        self,
        blocks: Sequence[InputBlock],
        page_per_block: dict[UUID, int] | None,
    ) -> list[MergedChunk]:
        """presentation 전략 — 슬라이드 (page) 단위 chunk.

        page_per_block 이 없으면 heading_1 boundary 로 fallback.
        """
        if not page_per_block:
            return self._chunk_chapter(blocks)

        # page 별 그룹핑
        groups_by_page: dict[int, list[InputBlock]] = {}
        for b in blocks:
            page = page_per_block.get(b.block_id, 0)
            groups_by_page.setdefault(page, []).append(b)

        chunks: list[MergedChunk] = []
        for page in sorted(groups_by_page.keys()):
            group = groups_by_page[page]
            cluster_id = uuid4()
            text = self._join_blocks(group)
            if not text.strip():
                continue
            if len(text) <= self.max_chars:
                chunks.append(self._make_chunk(text, group, cluster_id, len(chunks)))
            else:
                for piece, piece_blocks in self.merger._force_split(text, group):
                    chunks.append(
                        self._make_chunk(piece, piece_blocks, cluster_id, len(chunks))
                    )

        for i, c in enumerate(chunks):
            c.chunk_index = i
        return chunks

    def _chunk_paragraph(self, blocks: Sequence[InputBlock]) -> list[MergedChunk]:
        """memo / email 전략 — 단락 1~2개씩 작은 chunk.

        짧은 비공식 기록 (회의록, 이메일) 은 검색 시 *원본 단락* 이 답변에 그대로
        나오는 게 좋아 SemanticBlockMerger 보다 작은 단위 유지.
        """
        chunks: list[MergedChunk] = []
        cur: list[InputBlock] = []
        cur_len = 0
        for b in blocks:
            cur.append(b)
            cur_len += len(b.content)
            # 한 chunk 당 약 min_chars 정도. heading 직후엔 본문 한 단락만 묶고 끊음.
            if cur_len >= self.min_chars or b.block_type.startswith("heading_"):
                cluster_id = uuid4()
                text = self._join_blocks(cur)
                if text.strip():
                    chunks.append(self._make_chunk(text, cur, cluster_id, len(chunks)))
                cur = []
                cur_len = 0
        if cur:
            cluster_id = uuid4()
            text = self._join_blocks(cur)
            if text.strip():
                chunks.append(self._make_chunk(text, cur, cluster_id, len(chunks)))

        for i, c in enumerate(chunks):
            c.chunk_index = i
        return chunks

    def _chunk_chapter(self, blocks: Sequence[InputBlock]) -> list[MergedChunk]:
        """report / research_note 전략 — 챕터(heading_1) boundary 로 chunk.

        보고서/리서치는 챕터별 의미 단위가 명확. heading_1 마다 새 chunk.
        max_chars 초과 시 강제 split.
        """
        groups: list[list[InputBlock]] = []
        cur: list[InputBlock] = []
        for b in blocks:
            if b.block_type == "heading_1" and cur:
                groups.append(cur)
                cur = []
            cur.append(b)
        if cur:
            groups.append(cur)

        chunks: list[MergedChunk] = []
        for group in groups:
            cluster_id = uuid4()
            text = self._join_blocks(group)
            if not text.strip():
                continue
            if len(text) <= self.max_chars:
                chunks.append(self._make_chunk(text, group, cluster_id, len(chunks)))
            else:
                for piece, piece_blocks in self.merger._force_split(text, group):
                    chunks.append(
                        self._make_chunk(piece, piece_blocks, cluster_id, len(chunks))
                    )

        for i, c in enumerate(chunks):
            c.chunk_index = i
        return chunks

    # ─────────────────────────────────────────────────────────────── helpers

    @staticmethod
    def _join_blocks(blocks: Sequence[InputBlock]) -> str:
        parts: list[str] = []
        for b in blocks:
            content = (b.content or "").strip()
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    @staticmethod
    def _make_chunk(
        text: str,
        source_blocks: Sequence[InputBlock],
        cluster_id: UUID,
        chunk_index: int,
    ) -> MergedChunk:
        # D31a (#206 v5 §2.5) — neutral helper 사용 (FAQ/memo/report/manual 모두 metadata 풀세트).
        from src.pipeline.processing.merged_chunk_builder import build_merged_chunk
        return build_merged_chunk(
            text=text,
            source_blocks=list(source_blocks),
            cluster_id=cluster_id,
            chunk_index=chunk_index,
        )


# ── 패턴 인지 ─────────────────────────────────────────────────────────────


def _is_question_block(block: InputBlock) -> bool:
    """block 이 FAQ 의 질문 boundary 인지 판정.

    조건 (둘 중 하나):
    1. block content 의 *첫 줄* 이 질문 키워드 패턴 (`질문N`, `Q.`, `MENT` 인접) 이면 True.
    2. block 이 heading_3/2 이고 80자 이하 + 물음표 ("?") 로 끝나면 True
       (homeshop 형식의 `### 결제수단에는 무엇이 있나요?` 패턴).
    """
    content = (block.content or "").strip()
    if not content:
        return False
    first_line = content.split("\n", 1)[0]

    # 패턴 1 — 질문 키워드
    if _FAQ_QUESTION_RE.match(first_line):
        return True

    # 패턴 2 — heading 형식 질문문
    if block.block_type in ("heading_2", "heading_3"):
        stripped = first_line.strip().rstrip("?")  # 물음표 제거 후 길이 측정
        if (
            len(content) <= _FAQ_HEADING_QUESTION_MAX_CHARS
            and first_line.rstrip().endswith(("?", "?"))
        ):
            return True

    return False


def detect_faq_pattern(blocks: Iterable[InputBlock]) -> int:
    """blocks 에서 발견된 Q&A 쌍의 *예상* 개수.

    ≥ 3 이면 문서를 FAQ 로 간주해도 안전. 사용자 절칙의 "FAQ 형태 인지" 로직.

    검사 기준: 질문 패턴 block 의 *바로 다음* block 이 답변 패턴이거나 본문이
    있는 경우를 1쌍으로 카운트. 답변 패턴 강제 X — `**질문N:**` + 어떤 본문이
    뒤따르면 FAQ 형태.
    """
    block_list = list(blocks)
    count = 0
    for i, b in enumerate(block_list):
        if _is_question_block(b):
            # 답변 후보가 있는가? (다음 block 이 비어있지 않거나 본문 자체에 줄바꿈
            # 으로 답변이 포함된 경우)
            has_answer_in_block = "\n" in (b.content or "")
            has_next_answer = (
                i + 1 < len(block_list) and (block_list[i + 1].content or "").strip()
            )
            if has_answer_in_block or has_next_answer:
                count += 1
    return count


def _avg_chars(chunks: Sequence[MergedChunk]) -> float:
    if not chunks:
        return 0.0
    total = sum(c.char_count for c in chunks)
    return round(total / len(chunks), 1)
