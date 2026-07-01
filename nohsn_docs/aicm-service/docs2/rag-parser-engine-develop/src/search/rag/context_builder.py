"""RAG 컨텍스트 빌더 — Direct Mode / Generation Mode + TableAwareContextBuilder 연동."""

from __future__ import annotations

from src.common.logging import get_logger
from src.search.models import RAGContextResponse, RAGSource, SearchHit, SourceLocation
from src.search.rag.prompt_templates import (
    CONTEXT_BLOCK_TEMPLATE,
    CONTEXT_SEPARATOR,
    build_rag_prompt,
    has_table_chunks,
    format_source_list,
)
from src.search.rag.source_formatter import (
    format_source_for_direct,
    format_source_for_rag,
)
from src.search.rag.table_context import TableAwareContextBuilder, is_table_chunk

log = get_logger(__name__)


def _page_info_str(loc: SourceLocation | None) -> str | None:
    """SourceLocation에서 페이지/시트 정보 문자열 생성."""
    if not loc:
        return None
    parts: list[str] = []
    if loc.page_range:
        parts.append(f"p.{loc.page_range[0]}-{loc.page_range[1]}")
    elif loc.page_number:
        parts.append(f"p.{loc.page_number}")
    if loc.sheet_name:
        parts.append(f"시트: {loc.sheet_name}")
    return ", ".join(parts) if parts else None


def _format_block_for_context(hit: SearchHit) -> str:
    """블럭 타입에 따라 RAG 컨텍스트를 포맷한다.

    block_type 별로 마크다운 형식을 적용하여 LLM이 구조를 이해할 수 있도록 한다.
    """
    block_type = hit.block_type or "paragraph"
    content = hit.content
    metadata = hit.metadata or {}

    if block_type.startswith("heading"):
        # heading_1, heading_2, heading_3 등
        level_str = block_type.split("_")[-1] if "_" in block_type else "1"
        try:
            level = int(level_str)
        except ValueError:
            level = 1
        level = max(1, min(level, 6))
        return f"{'#' * level} {content}"

    elif block_type == "code":
        lang = metadata.get("language", "")
        return f"```{lang}\n{content}\n```"

    elif block_type == "quote":
        return "\n".join(f"> {line}" for line in content.split("\n"))

    elif block_type == "callout":
        callout_type = metadata.get("callout_type", "info")
        prefix = {"warning": "[!]", "tip": "[TIP]", "info": "[i]"}.get(callout_type, "[i]")
        return f"{prefix} {content}"

    elif block_type in ("bulleted_list", "numbered_list"):
        # 이미 마커가 포함되어 있으므로 그대로 반환
        return content

    elif block_type == "table":
        # 표 마크다운은 원형 보존
        return content

    elif block_type == "image":
        desc = metadata.get("image_description", "")
        ocr = metadata.get("ocr_text", "")
        parts = ["[이미지]"]
        if desc:
            parts.append(f"설명: {desc}")
        if ocr:
            parts.append(f"텍스트: {ocr}")
        return " | ".join(parts)

    elif block_type == "divider":
        return "---"

    else:
        return content


def _count_tokens(text: str) -> int:
    """
    간이 토큰 수 추정.

    정확한 토크나이저 대신 한국어 기준 약 3.5 문자/토큰으로 추정.
    영문은 약 4 문자/토큰.
    """
    if not text:
        return 0
    # 한국어 비율 추정
    korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    total_chars = len(text)
    if total_chars == 0:
        return 0
    korean_ratio = korean_chars / total_chars
    avg_chars_per_token = 3.5 * korean_ratio + 4.0 * (1 - korean_ratio)
    return max(1, int(total_chars / avg_chars_per_token))


class ContextBuilder:
    """
    RAG 컨텍스트 빌더.

    두 가지 모드 지원:
    - direct (context) mode: 원문 + 출처 반환 (어드바이저, 사내 포탈)
    - generation (answer) mode: 컨텍스트 + 프롬프트 템플릿 반환 (봇)

    표 청크가 검색 결과에 포함되면 TableAwareContextBuilder를 통해
    같은 표의 형제 청크(Summary, Markdown, Row NL)를 자동 보강한다.
    """

    def __init__(
        self,
        table_context_builder: TableAwareContextBuilder | None = None,
    ) -> None:
        self._table_builder = table_context_builder

    async def enrich_with_table_context(
        self,
        hits: list[SearchHit],
        collection_name: str,
        max_context_tokens: int = 2000,
    ) -> list[SearchHit]:
        """표 청크가 포함된 결과를 TableAwareContextBuilder로 보강."""
        if self._table_builder is None:
            return hits

        has_table = any(is_table_chunk(h) for h in hits)
        if not has_table:
            return hits

        return await self._table_builder.enrich_table_context(
            hits=hits,
            collection_name=collection_name,
            max_context_tokens=max_context_tokens,
        )

    @staticmethod
    def auto_select_mode(hits: list[SearchHit], threshold: float = 0.85) -> str:
        """Top-1 신뢰도 기반 RAG 모드 자동 선택.

        - 확신 높음 (score >= threshold): 'direct' → 블럭 원문 직접 반환
        - 확신 낮음: 'generation' → LLM이 여러 블럭을 종합하여 답변 생성
        """
        if hits and hits[0].score >= threshold:
            return "direct"
        return "generation"

    def build_direct(self, hits: list[SearchHit]) -> RAGContextResponse:
        """
        Direct Mode — 검색 결과를 원문 그대로 포매팅.

        어드바이저/사내 포탈에서 사용자가 직접 읽고 참고하는 용도.
        번호 마커 [1], [2] 등으로 근거 문서를 명시한다.
        """
        recommendations: list[dict] = []
        sources: list[RAGSource] = []

        for rank, hit in enumerate(hits, 1):
            recommendations.append(format_source_for_direct(hit, rank))
            page_info = _page_info_str(hit.source_location)
            sources.append(
                RAGSource(
                    ref_num=rank,
                    doc_title=hit.document_title,
                    section=hit.section_title,
                    score=round(hit.score, 3),
                    source_location=hit.source_location,
                    page_info=page_info,
                )
            )

        context_parts: list[str] = []
        for rank, hit in enumerate(hits, 1):
            formatted_content = _format_block_for_context(hit)
            block = CONTEXT_BLOCK_TEMPLATE.format(
                ref_num=rank,
                doc_title=hit.document_title,
                section_title=hit.section_title or "",
                content=formatted_content,
            )
            context_parts.append(block)

        context = CONTEXT_SEPARATOR.join(context_parts)

        log.info("direct_context_built", hit_count=len(hits))
        return RAGContextResponse(
            context=context,
            sources=sources,
            prompt_template=None,
        )

    def build_generation(
        self,
        query: str,
        hits: list[SearchHit],
        max_context_tokens: int = 2000,
        organization_type: str = "고객서비스센터",
    ) -> RAGContextResponse:
        """
        Generation Mode — LLM 프롬프트에 주입 가능한 형태로 조립.

        토큰 예산 내에서 컨텍스트를 조립하고, 완성된 프롬프트 템플릿을 반환.
        각 참고 자료에 [1], [2] 등 인용 번호를 부여하여 LLM이 인라인 인용하도록 한다.
        """
        context_parts: list[str] = []
        total_tokens = 0
        sources: list[RAGSource] = []
        source_list_entries: list[dict] = []
        metadata_list: list[dict] = []
        ref_num = 0

        for hit in hits:
            formatted_content = _format_block_for_context(hit)
            tokens = _count_tokens(formatted_content)
            if total_tokens + tokens > max_context_tokens:
                break

            ref_num += 1
            block = CONTEXT_BLOCK_TEMPLATE.format(
                ref_num=ref_num,
                doc_title=hit.document_title,
                section_title=hit.section_title or "",
                content=formatted_content,
            )
            context_parts.append(block)
            metadata_list.append(hit.metadata)

            page_info = _page_info_str(hit.source_location)
            sources.append(
                RAGSource(
                    ref_num=ref_num,
                    doc_title=hit.document_title,
                    section=hit.section_title,
                    score=round(hit.score, 3),
                    source_location=hit.source_location,
                    page_info=page_info,
                )
            )
            source_list_entries.append({
                "ref_num": ref_num,
                "doc_title": hit.document_title,
                "section": hit.section_title or "",
                "page_info": page_info or "",
            })
            total_tokens += tokens

        context = CONTEXT_SEPARATOR.join(context_parts)

        # 표 청크가 포함되면 표 전용 규칙 추가
        include_table_rules = has_table_chunks(metadata_list)

        prompt = build_rag_prompt(
            context=context,
            question=query,
            source_list_entries=source_list_entries,
            organization_type=organization_type,
            include_table_rules=include_table_rules,
        )

        log.info(
            "generation_context_built",
            hit_count=len(sources),
            total_tokens=total_tokens,
            include_table_rules=include_table_rules,
        )

        return RAGContextResponse(
            context=context,
            sources=sources,
            prompt_template=prompt,
        )
