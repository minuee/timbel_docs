"""블럭 기반 파이프라인 Pydantic 모델 — specs/06 기준.

Block = 의미 완결 단위 (검색 단위 = 편집 단위).
기존 ChunkObject 를 대체하며, 문서는 순서 있는 블럭의 집합으로 표현된다.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.pipeline.models.document import SourceLocation


class BlockType(str, Enum):
    """블럭 유형 — Notion 호환 블럭 타입.

    프론트엔드(Notion 스타일 에디터)와 API 응답 모두 동일한 타입을 사용한다.
    """

    # -- 텍스트 계열 --
    PARAGRAPH = "paragraph"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"

    # -- 리스트 계열 --
    BULLETED_LIST = "bulleted_list"
    NUMBERED_LIST = "numbered_list"
    TO_DO = "to_do"
    TOGGLE = "toggle"
    QNA = "qna"  # Q&A 쌍 (FAQ 질문 + 답변 전체가 하나의 블럭)

    # -- 코드/인용 --
    CODE = "code"
    QUOTE = "quote"
    CALLOUT = "callout"

    # -- 미디어 --
    TABLE = "table"
    IMAGE = "image"

    # -- 구분 --
    DIVIDER = "divider"

    # -- 슬라이드/PPT --
    SLIDE = "slide"  # PPT형 페이지 통째 처리 (이미지+텍스트 결합)

    # -- 시스템 (파이프라인 생성) --
    SUMMARY = "summary"                    # 문서 요약 (KnowledgeCompiler)
    TABLE_OF_CONTENTS = "table_of_contents"  # 자동 생성 목차

    # -- 비정형 소스 --
    CALENDAR_EVENT = "calendar_event"        # 캘린더 이벤트 (start/end/location/attendees)
    CHAT_MESSAGE = "chat_message"            # 채팅 메시지 (speaker/timestamp/channel)
    EMAIL = "email"                          # 이메일 (from/to/cc/subject/date)
    AUDIO_TRANSCRIPT = "audio_transcript"    # 음성 전사 (speaker/start_ms/end_ms/audio_url)

    # -- 하위 호환 별칭 --
    TEXT = "paragraph"  # 기존 "text" → "paragraph" 매핑


class BlockObject(BaseModel):
    """개별 블럭 객체 — 검색·편집·벡터화의 기본 단위."""

    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    block_type: BlockType
    content: str
    block_index: int
    block_hash: str = ""  # SHA-256, compute_hash() 로 자동 채움
    token_count: int = 0

    # 원본 위치
    source_location: SourceLocation = Field(default_factory=SourceLocation)

    # 벡터화 결과
    dense_vector: Optional[list[float]] = None   # 1024d BGE-M3
    sparse_vector: Optional[dict[int, float]] = None

    # Notion 스타일 속성 (code language, heading toggleable, to_do checked, callout icon 등)
    properties: Optional[dict] = Field(default_factory=dict)

    # 중첩 블럭 지원 (toggle, callout 등의 자식 블럭 ID 목록)
    children: list[UUID] = Field(default_factory=list)

    # 메타데이터
    metadata: dict = Field(default_factory=dict)

    # Phase 2: 보강
    contextual_prefix: Optional[str] = None
    extracted_metadata: Optional[dict] = None

    # 표 전용 필드
    table_headers: Optional[list[str]] = None
    table_rows: Optional[list[list[str]]] = None
    table_markdown: Optional[str] = None

    # 이미지 전용 필드
    image_path: Optional[str] = None
    ocr_text: Optional[str] = None
    image_description: Optional[str] = None

    def compute_hash(self) -> str:
        """content 기반 SHA-256 해시를 계산하고 block_hash 에 저장한다."""
        self.block_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        return self.block_hash

    def embedding_text(self) -> str:
        """검색용 임베딩 텍스트 생성. 다층 정보 포함.

        v2 레이어 구성 (순서대로):
        1. Contextual prefix (문서 맥락, 섹션 경로, 인접 블럭)
        2. Search summary (LLM 생성 검색 최적화 요약)
        3. Topic tags (상위 주제 태그)
        4. Query keywords (사용자 검색 질의형 표현)
        5. 블럭 타입별 원본 content

        블럭 타입별 최적화:
        - heading: 제목 + next_context (다음 본문) 합치기
        - table: markdown + table_nl (자연어 해석)
        - image: description + ocr_text
        - default: content
        """
        parts: list[str] = []

        # 1. Contextual prefix (모든 타입 공통)
        if self.contextual_prefix:
            parts.append(self.contextual_prefix)

        # 1.5 QNA 블럭: 질문(qna_title)을 임베딩에 포함. content 는 답변이므로, 질문을 함께 임베딩해야
        # 사용자가 질문으로 검색했을 때 이 블럭(답변 보유)이 매칭된다. (질문은 metadata 1곳에만 저장)
        _qna_title = self.metadata.get("qna_title")
        if _qna_title:
            parts.append(f"[질문] {_qna_title}")

        # 2. Search summary (LLM 생성)
        search_summary = self.metadata.get("search_summary")
        if search_summary:
            parts.append(f"[요약] {search_summary}")

        # 3. Topic tags
        topic_tags = self.metadata.get("topic_tags")
        if topic_tags and isinstance(topic_tags, list):
            parts.append(f"[주제] {', '.join(topic_tags)}")

        # 4. Query keywords
        # extracted_metadata(인프로세스 파이프라인 경로) 우선, 없으면 metadata 폴백.
        # DB 재로드 기반 재인덱싱(편집 저장 등)에서는 extracted_metadata 가 None 이고
        # query_keywords 가 meta_info(=metadata) 에만 있으므로 폴백이 필요하다.
        query_keywords = (
            (self.extracted_metadata or {}).get("query_keywords")
            or self.metadata.get("query_keywords")
        )
        if query_keywords and isinstance(query_keywords, list):
            parts.append(f"[검색어] {', '.join(query_keywords)}")

        # 5. 블럭 타입별 원본 content

        # heading: 제목 + 다음 본문 컨텍스트 합치기
        if self.block_type in (BlockType.HEADING_1, BlockType.HEADING_2, BlockType.HEADING_3):
            parts.append(self.content)
            next_ctx = (
                self.metadata.get("next_context")
                or self.properties.get("next_context", "")
            )
            if next_ctx:
                parts.append(next_ctx)
            return "\n\n".join(parts)

        # table: content + table_nl 합치기
        if self.block_type == BlockType.TABLE:
            if self.table_markdown:
                parts.append(self.table_markdown)
            else:
                parts.append(self.content)
            meta_nl = self.metadata.get("table_nl", "")
            if meta_nl:
                parts.append(meta_nl)
            return "\n\n".join(parts)

        # image: description + ocr_text
        if self.block_type == BlockType.IMAGE:
            if self.image_description:
                parts.append(self.image_description)
            if self.ocr_text:
                parts.append(self.ocr_text)
            # fallback: prefix + enrichment만 있거나 아무것도 없으면 content 사용
            has_visual_content = any(
                p for p in parts
                if not p.startswith("[") and p != self.contextual_prefix
            )
            if not has_visual_content:
                parts.append(self.content)
            return "\n\n".join(parts)

        # default
        parts.append(self.content)
        return "\n\n".join(parts)
