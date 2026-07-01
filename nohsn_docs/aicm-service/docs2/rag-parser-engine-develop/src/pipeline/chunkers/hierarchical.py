"""Hierarchical Chunker -- 목차 구조 보존 + 한국어 제목 패턴 인식.

Phase 2 Task B-4.

chunk_service/pipeline/stages/structure_process.py 의 HEADER_PATTERNS 를 참조하여
PDF/DOCX 헤딩 추출을 개선하였다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID, uuid4

from src.common.logging import get_logger
from src.pipeline.chunkers.base import BaseChunker
from src.pipeline.models.document import ChunkObject, ChunkStrategy, ProcessingConfig, SourceLocation
from src.pipeline.models.parse_result import PageContent, TextBlock

log = get_logger(__name__)


@dataclass
class Section:
    """문서 내 섹션 (계층적 구조 노드)."""

    title: str
    level: int
    content: list[str] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)
    page_number: Optional[int] = None


# ---------------------------------------------------------------------------
# 한국어 제목 패턴 (chunk_service structure_process.py 참조)
# ---------------------------------------------------------------------------
_HEADING_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    # Level 1: 편/장
    (re.compile(r"^\s*제\s*\d+\s*편"), 1),
    (re.compile(r"^\s*제\s*\d+\s*장"), 1),
    # Level 2: 조
    (re.compile(r"^\s*제\s*\d+\s*조"), 2),
    # Level 3: 숫자 번호 (1. 2. 3.)
    (re.compile(r"^\s*\d+\.\s+\S"), 3),
    # Level 4: 원문자 (①~⑮)
    (re.compile(r"^\s*[①-⑮]"), 4),
    # Level 4: 가나다 (가. 나. 다.)
    (re.compile(r"^\s*[가-하]\.\s"), 4),
    # Level 3: Q&A 패턴
    (re.compile(r"^\s*Q[.:]\s"), 3),
    # Markdown 헤딩 (# ## ###)
    (re.compile(r"^#{1}\s+\S"), 1),
    (re.compile(r"^#{2}\s+\S"), 2),
    (re.compile(r"^#{3}\s+\S"), 3),
    (re.compile(r"^#{4,}\s+\S"), 4),
]

# 서술형 종결 패턴 (제목이 아닌 본문으로 판단하는 기준)
_SHORT_HEADER_PATTERN = re.compile(r"^\s*([①-⑮]|[가-하]\.)")
_MAX_HEADER_LEN = 100
_MAX_SHORT_HEADER_LEN = 30


class HierarchicalChunker(BaseChunker):
    """목차 구조 보존 청커.

    알고리즘
    --------
    1. 전체 텍스트를 줄 단위로 스캔하여 제목 패턴 감지
    2. 제목 레벨별 계층적 섹션 트리 구축
    3. 각 섹션을 max_tokens 이내로 분할
    4. 각 청크에 heading_path 프리픽스 부착
       예: ``[대출 한도 > 신용등급별 한도] content...``
    5. source_location 에 heading_path 기록
    """

    async def chunk(
        self,
        pages: list[PageContent],
        *,
        source_file_path: str = "",
        document_id: str = "",
    ) -> list[ChunkObject]:
        """페이지 목록 -> 계층적 청크 목록."""
        doc_uuid = UUID(document_id) if document_id else uuid4()

        # 1) 전체 텍스트를 줄 단위로 수집
        lines = self._collect_lines(pages, source_file_path)

        if not lines:
            return []

        # 2) 섹션 트리 구축
        root_sections = self._build_section_tree(lines)

        # 3) 섹션 -> 청크 변환
        chunks = self._sections_to_chunks(root_sections, doc_uuid, source_file_path)

        # 4) chunk_index 재정렬
        for i, c in enumerate(chunks):
            c.chunk_index = i

        log.info(
            "hierarchical_chunking_complete",
            total_lines=len(lines),
            sections=self._count_sections(root_sections),
            chunks=len(chunks),
        )

        return chunks

    # ------------------------------------------------------------------
    # 줄 수집
    # ------------------------------------------------------------------
    @staticmethod
    def _collect_lines(
        pages: list[PageContent], source_file_path: str
    ) -> list[tuple[str, int]]:
        """페이지에서 (텍스트, 페이지번호) 튜플 목록을 수집한다."""
        lines: list[tuple[str, int]] = []
        for page in pages:
            for line in page.text.split("\n"):
                stripped = line.strip()
                if stripped:
                    lines.append((stripped, page.page_number))
        return lines

    # ------------------------------------------------------------------
    # 제목 감지
    # ------------------------------------------------------------------
    @classmethod
    def _detect_heading(cls, text: str) -> Optional[int]:
        """텍스트가 제목 패턴에 매칭되면 레벨을 반환한다.

        chunk_service structure_process.py 의 _is_explicit_header 로직을 참조.
        """
        text = text.strip()

        # 길이 체크: 원문자/가나다 패턴은 30자, 그 외 100자 제한
        limit = _MAX_SHORT_HEADER_LEN if _SHORT_HEADER_PATTERN.match(text) else _MAX_HEADER_LEN
        if len(text) > limit:
            return None

        # 서술형 종결 체크
        if len(text) > 20 and text.endswith((".", ",")):
            return None

        for pattern, level in _HEADING_PATTERNS:
            if pattern.match(text):
                return level

        return None

    # ------------------------------------------------------------------
    # 섹션 트리 구축
    # ------------------------------------------------------------------
    def _build_section_tree(
        self, lines: list[tuple[str, int]]
    ) -> list[Section]:
        """줄 목록에서 계층적 섹션 트리를 구축한다."""
        root_sections: list[Section] = []
        # 스택: (Section, level) — 현재 열려있는 섹션 경로
        stack: list[tuple[Section, int]] = []

        # 제목 이전 본문을 위한 기본 섹션
        current_content: list[str] = []
        current_page: Optional[int] = None

        for text, page_num in lines:
            heading_level = self._detect_heading(text)

            if heading_level is not None:
                # 이전에 쌓인 제목 없는 본문이 있으면 기본 섹션 생성
                if current_content and not stack:
                    default_section = Section(
                        title="(본문)",
                        level=0,
                        content=current_content,
                        page_number=current_page,
                    )
                    root_sections.append(default_section)
                    current_content = []

                # 새 섹션 생성
                new_section = Section(
                    title=text,
                    level=heading_level,
                    page_number=page_num,
                )

                # 스택에서 현재 레벨 이상의 섹션을 pop
                while stack and stack[-1][1] >= heading_level:
                    stack.pop()

                if stack:
                    # 부모 섹션의 자식으로 추가
                    stack[-1][0].children.append(new_section)
                else:
                    # 루트 섹션
                    root_sections.append(new_section)

                stack.append((new_section, heading_level))
                current_content = []
            else:
                # 본문 텍스트
                if stack:
                    stack[-1][0].content.append(text)
                else:
                    current_content.append(text)
                    if current_page is None:
                        current_page = page_num

        # 마지막 남은 제목 없는 본문
        if current_content and not stack:
            root_sections.append(
                Section(
                    title="(본문)",
                    level=0,
                    content=current_content,
                    page_number=current_page,
                )
            )

        return root_sections

    # ------------------------------------------------------------------
    # 섹션 -> 청크 변환
    # ------------------------------------------------------------------
    def _sections_to_chunks(
        self,
        sections: list[Section],
        document_id: UUID,
        source_file_path: str,
        parent_path: Optional[list[str]] = None,
    ) -> list[ChunkObject]:
        """섹션 트리를 순회하며 청크를 생성한다."""
        chunks: list[ChunkObject] = []
        heading_path = parent_path or []

        for section in sections:
            current_path = heading_path + [section.title] if section.title != "(본문)" else heading_path

            # 본문 텍스트를 청크로 변환
            if section.content:
                full_text = "\n".join(section.content)
                path_prefix = (
                    f"[{' > '.join(current_path)}] " if current_path else ""
                )
                prefixed_text = path_prefix + full_text

                # max_tokens 제약으로 분할
                text_chunks = self._split_by_token_limit(prefixed_text)

                for text_chunk in text_chunks:
                    chunk_hash = hashlib.sha256(
                        text_chunk.encode("utf-8")
                    ).hexdigest()

                    sl = SourceLocation(
                        file_path=source_file_path,
                        page_number=section.page_number,
                        heading_path=list(current_path),
                    )

                    chunks.append(
                        ChunkObject(
                            id=uuid4(),
                            document_id=document_id,
                            content=text_chunk,
                            chunk_index=0,
                            chunk_hash=chunk_hash,
                            token_count=len(text_chunk),
                            strategy=ChunkStrategy.HIERARCHICAL,
                            source_location=sl,
                            metadata={
                                "heading_path": current_path,
                                "section_title": section.title,
                                "level": section.level,
                            },
                        )
                    )

            # 자식 섹션 재귀 처리
            child_chunks = self._sections_to_chunks(
                section.children, document_id, source_file_path, current_path
            )
            chunks.extend(child_chunks)

        return chunks

    def _split_by_token_limit(self, text: str) -> list[str]:
        """max_tokens 초과 시 텍스트를 분할한다."""
        if len(text) <= self.max_tokens:
            return [text]

        parts: list[str] = []
        while len(text) > self.max_tokens:
            cut = self.max_tokens
            # 줄바꿈, 마침표, 쉼표, 공백 순으로 분할점 검색
            for sep in ("\n", ". ", ", ", " "):
                pos = text.rfind(sep, 0, cut)
                if pos > self.min_tokens:
                    cut = pos + len(sep)
                    break

            parts.append(text[:cut].strip())
            # 오버랩 적용
            overlap_start = max(0, cut - self.overlap)
            text = text[overlap_start:]

        if text.strip():
            parts.append(text.strip())

        return parts

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------
    @classmethod
    def _count_sections(cls, sections: list[Section]) -> int:
        """섹션 트리의 총 노드 수를 반환한다."""
        count = len(sections)
        for s in sections:
            count += cls._count_sections(s.children)
        return count
