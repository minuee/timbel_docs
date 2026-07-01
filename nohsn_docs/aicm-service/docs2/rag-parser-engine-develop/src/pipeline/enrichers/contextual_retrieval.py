"""Contextual Retrieval v2 -- 각 청크/블럭에 다층 문서 맥락 프리픽스를 부착.

Phase 2 Task B-6 → v2 확장.

Anthropic의 Contextual Retrieval 기법을 확장하여,
문서 제목/타입/요약, 섹션 경로(다층), 인접 블럭 맥락, LLM 생성 검색 키워드를
포함하는 풍부한 프리픽스를 생성한다.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from src.common.logging import get_logger
from src.pipeline.models.document import ChunkObject

log = get_logger(__name__)

_MAX_DOCUMENT_TEXT_CHARS = 10_000
_MAX_CONCURRENT = 1
_NEIGHBOR_PREVIEW_CHARS = 50
_MIN_CONTENT_LEN_FOR_KEYWORDS = 30

# ---------------------------------------------------------------------------
# v1 프롬프트 (레거시 호환)
# ---------------------------------------------------------------------------
CONTEXTUAL_PROMPT = """<document>
{document_text}
</document>

위 문서에서 아래 청크가 위치한 맥락을 간결하게 설명하세요 (1-2문장).
문서 제목, 해당 섹션의 주제, 청크가 다루는 핵심 내용을 포함하세요.

<chunk>
{chunk_content}
</chunk>

맥락 설명:"""

# ---------------------------------------------------------------------------
# v2 프롬프트: 구조화된 다층 맥락 + 검색 키워드
# ---------------------------------------------------------------------------
CONTEXTUAL_V2_PROMPT = """<document>
{document_text}
</document>

## 블럭 정보
- 문서 제목: {document_title}
- 문서 유형: {document_type}
- 문서 요약: {document_summary}
- 섹션 경로: {heading_path}
- 직전 블럭: {prev_context}
- 직후 블럭: {next_context}

## 현재 블럭
{chunk_content}

## 지시사항
위 정보를 바탕으로 두 가지를 생성하세요:

1. **맥락 설명** (1-2문장): 이 블럭이 문서 전체에서 어떤 위치에 있고, 무엇을 다루는지 설명.
2. **검색 키워드** (3-5개): 사용자가 이 블럭을 찾기 위해 검색할 가능성이 높은 키워드/구문.

아래 형식으로만 출력하세요:
맥락: <맥락 설명>
키워드: <쉼표 구분 키워드>"""


class ContextualRetriever:
    """각 청크/블럭에 문서 전체 맥락 프리픽스를 부착한다.

    v2 프로세스
    -----------
    1. 문서 전체 텍스트 (앞 10,000자) + 구조 정보를 LLM에 전달
       - 문서 제목/타입/요약
       - 섹션 경로 (heading_path, 다층 구조)
       - 인접 블럭 미리보기 (직전 1개 + 직후 1개의 첫 50자)
    2. LLM이 구조화된 맥락 설명 + 검색 키워드 생성
    3. 최종 prefix 형식:
       [문서: {title} | 섹션: {heading_path}]
       [직전 맥락: ...{prev_context}]
       [현재 블럭의 핵심: {context_description}]
    4. 검색 키워드는 block.metadata["contextual_keywords"]에 저장

    LLM 라우팅: LLMTask.CONTEXTUAL_RETRIEVAL -> Claude
    비용 최적화: 동일 문서의 청크들은 document_text를 캐싱하여 1회만 전송
    """

    def __init__(self) -> None:
        self._document_cache: dict[str, str] = {}

    async def enrich(
        self,
        chunks: list[ChunkObject],
        document_text: str,
        document_title: str = "",
    ) -> list[ChunkObject]:
        """청크 목록에 contextual prefix 를 부착한다 (v1 호환).

        Parameters
        ----------
        chunks : list[ChunkObject]
            원본 청크 목록
        document_text : str
            문서 전체 텍스트 (앞 10K 자만 사용)
        document_title : str
            문서 제목

        Returns
        -------
        list[ChunkObject]
            contextual_prefix 가 부착된 청크 목록
        """
        if not chunks:
            return chunks

        doc_text = document_text[:_MAX_DOCUMENT_TEXT_CHARS]
        if document_title:
            doc_text = f"[제목: {document_title}]\n\n{doc_text}"

        success_count = 0
        fail_count = 0

        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _enrich_one(chunk: ChunkObject) -> None:
            nonlocal success_count, fail_count
            async with sem:
                try:
                    prefix = await self._generate_prefix(doc_text, chunk.content)
                    chunk.contextual_prefix = prefix
                    success_count += 1
                except Exception as exc:
                    log.warning(
                        "contextual_retrieval_failed",
                        chunk_id=str(chunk.id),
                        error=str(exc),
                    )
                    fail_count += 1

        await asyncio.gather(*[_enrich_one(c) for c in chunks])

        log.info(
            "contextual_retrieval_complete",
            total=len(chunks),
            success=success_count,
            failed=fail_count,
        )

        return chunks

    async def enrich_blocks_v2(
        self,
        blocks: list,
        document_text: str,
        document_title: str = "",
        document_type: str = "",
        document_summary: str = "",
    ) -> list:
        """블럭 목록에 v2 contextual prefix를 부착한다.

        v1 대비 추가 정보:
        - 문서 타입/요약
        - 섹션 경로 (heading_path)
        - 인접 블럭 맥락
        - LLM 생성 검색 키워드

        Parameters
        ----------
        blocks : list[BlockObject]
            블럭 목록
        document_text : str
            문서 전체 텍스트
        document_title : str
            문서 제목
        document_type : str
            문서 유형 (예: 사업계획서, 매뉴얼)
        document_summary : str
            문서 전체 요약 (이전 단계에서 생성)

        Returns
        -------
        list[BlockObject]
            contextual_prefix + contextual_keywords가 부착된 블럭 목록
        """
        from src.pipeline.models.block import BlockType

        if not blocks:
            return blocks

        doc_text = document_text[:_MAX_DOCUMENT_TEXT_CHARS]

        # 인덱스 기반 빠른 조회를 위해 정렬된 블럭 리스트 생성
        sorted_blocks = sorted(blocks, key=lambda b: b.block_index)
        index_map = {b.id: i for i, b in enumerate(sorted_blocks)}

        success_count = 0
        fail_count = 0
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _enrich_one(block: object) -> None:
            nonlocal success_count, fail_count

            # SUMMARY, DIVIDER 등 시스템 블럭은 건너뛴다
            if block.block_type in (BlockType.SUMMARY, BlockType.DIVIDER, BlockType.TABLE_OF_CONTENTS):
                return

            async with sem:
                try:
                    # 인접 블럭 미리보기 수집
                    pos = index_map.get(block.id, -1)
                    prev_ctx = ""
                    next_ctx = ""
                    if pos > 0:
                        prev_block = sorted_blocks[pos - 1]
                        if prev_block.block_type != BlockType.SUMMARY:
                            prev_ctx = prev_block.content[:_NEIGHBOR_PREVIEW_CHARS]
                    if pos >= 0 and pos < len(sorted_blocks) - 1:
                        next_block = sorted_blocks[pos + 1]
                        if next_block.block_type != BlockType.SUMMARY:
                            next_ctx = next_block.content[:_NEIGHBOR_PREVIEW_CHARS]

                    # 섹션 경로 구성
                    heading_path = " > ".join(
                        block.source_location.heading_path
                    ) if block.source_location and block.source_location.heading_path else "최상위"

                    prefix, keywords = await self._generate_prefix_v2(
                        document_text=doc_text,
                        document_title=document_title or "제목 없음",
                        document_type=document_type or "문서",
                        document_summary=document_summary or "요약 없음",
                        heading_path=heading_path,
                        prev_context=prev_ctx,
                        next_context=next_ctx,
                        chunk_content=block.content,
                    )

                    # 구조화된 prefix 생성
                    prefix_parts = []
                    prefix_parts.append(
                        f"[문서: {document_title or '제목 없음'} | 섹션: {heading_path}]"
                    )
                    if prev_ctx:
                        prefix_parts.append(f"[직전 맥락: ...{prev_ctx}]")
                    if prefix:
                        prefix_parts.append(f"[현재 블럭의 핵심: {prefix}]")

                    block.contextual_prefix = "\n".join(prefix_parts)

                    # 검색 키워드를 메타데이터에 저장
                    if keywords:
                        block.metadata["contextual_keywords"] = keywords

                    success_count += 1
                except Exception as exc:
                    log.warning(
                        "contextual_retrieval_v2_failed",
                        block_id=str(block.id),
                        error=str(exc),
                    )
                    fail_count += 1

        await asyncio.gather(*[_enrich_one(b) for b in blocks])

        log.info(
            "contextual_retrieval_v2_complete",
            total=len(blocks),
            success=success_count,
            failed=fail_count,
        )

        return blocks

    async def _generate_prefix(self, document_text: str, chunk_content: str) -> str:
        """LLM 으로 v1 맥락 프리픽스를 생성한다."""
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        prompt = CONTEXTUAL_PROMPT.format(
            document_text=document_text,
            chunk_content=chunk_content,
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt=(
                "당신은 문서 분석 전문가입니다. "
                "청크의 문서 내 맥락을 정확하고 간결하게 설명합니다."
            ),
            max_tokens=200,
            temperature=0.1,
        )

        response = await llm_router.route(
            task=LLMTask.CONTEXTUAL_RETRIEVAL,
            request=request,
        )

        prefix = response.text.strip()
        sentences = prefix.split(".")
        if len(sentences) > 3:
            prefix = ".".join(sentences[:2]) + "."

        return prefix

    async def _generate_prefix_v2(
        self,
        document_text: str,
        document_title: str,
        document_type: str,
        document_summary: str,
        heading_path: str,
        prev_context: str,
        next_context: str,
        chunk_content: str,
    ) -> tuple[str, list[str]]:
        """LLM으로 v2 맥락 프리픽스 + 검색 키워드를 생성한다.

        Returns
        -------
        tuple[str, list[str]]
            (맥락 설명 텍스트, 검색 키워드 리스트)
        """
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        prompt = CONTEXTUAL_V2_PROMPT.format(
            document_text=document_text,
            document_title=document_title,
            document_type=document_type,
            document_summary=document_summary,
            heading_path=heading_path,
            prev_context=prev_context or "(없음)",
            next_context=next_context or "(없음)",
            chunk_content=chunk_content[:1000],
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt=(
                "당신은 문서 분석 전문가입니다. "
                "블럭의 문서 내 맥락과 검색 키워드를 정확하게 생성합니다. "
                "반드시 지시된 형식(맥락: / 키워드:)으로만 출력하세요."
            ),
            max_tokens=300,
            temperature=0.1,
        )

        response = await llm_router.route(
            task=LLMTask.CONTEXTUAL_RETRIEVAL,
            request=request,
        )

        return self._parse_v2_response(response.text)

    @staticmethod
    def _parse_v2_response(raw: str) -> tuple[str, list[str]]:
        """v2 LLM 응답을 파싱하여 (맥락, 키워드 리스트)를 반환한다."""
        context = ""
        keywords: list[str] = []

        for line in raw.strip().splitlines():
            line = line.strip()
            if line.startswith("맥락:"):
                context = line[len("맥락:"):].strip()
            elif line.startswith("키워드:"):
                kw_text = line[len("키워드:"):].strip()
                keywords = [k.strip() for k in kw_text.split(",") if k.strip()]

        # fallback: 파싱 실패 시 전체 텍스트를 맥락으로
        if not context:
            context = raw.strip().split("\n")[0][:200]

        return context, keywords

    @staticmethod
    def get_embedding_text(chunk: ChunkObject) -> str:
        """임베딩에 사용할 텍스트를 반환한다.

        contextual_prefix 가 있으면 prefix + content 를 합친 텍스트를 반환.
        """
        if chunk.contextual_prefix:
            return f"{chunk.contextual_prefix}\n\n{chunk.content}"
        return chunk.content
