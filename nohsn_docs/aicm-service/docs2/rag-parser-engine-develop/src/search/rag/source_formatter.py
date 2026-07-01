"""출처 정보 포매터 — 페이지 번호, 목차 경로, 파일 URL 등."""

from __future__ import annotations

from src.search.models import SearchHit, SourceLocation


def format_source_label(hit: SearchHit) -> str:
    """검색 결과 항목의 출처 라벨 생성."""
    parts: list[str] = []

    # 문서 제목
    if hit.document_title:
        parts.append(hit.document_title)

    # 섹션 제목
    if hit.section_title:
        parts.append(hit.section_title)

    label = " > ".join(parts) if parts else "알 수 없는 출처"

    # 페이지 정보 추가
    page_info = format_page_info(hit.source_location)
    if page_info:
        label = f"{label} ({page_info})"

    return label


def format_page_info(loc: SourceLocation) -> str | None:
    """페이지/시트 위치 정보 텍스트 생성."""
    parts: list[str] = []

    if loc.page_range:
        parts.append(f"p.{loc.page_range[0]}-{loc.page_range[1]}")
    elif loc.page_number:
        parts.append(f"p.{loc.page_number}")

    if loc.sheet_name:
        parts.append(f"시트: {loc.sheet_name}")

    if loc.table_index is not None:
        parts.append(f"표 {loc.table_index + 1}")

    return ", ".join(parts) if parts else None


def format_heading_path(loc: SourceLocation) -> str | None:
    """목차 경로 텍스트 생성."""
    if not loc.heading_path:
        return None
    return " > ".join(loc.heading_path)


def format_source_for_rag(hit: SearchHit) -> dict:
    """RAG 컨텍스트용 출처 정보 딕셔너리 생성."""
    loc = hit.source_location
    return {
        "doc_title": hit.document_title,
        "section": hit.section_title,
        "score": round(hit.score, 3),
        "source_location": {
            "file_path": loc.file_path,
            "file_url": loc.file_url,
            "page_number": loc.page_number,
            "page_range": list(loc.page_range) if loc.page_range else None,
            "heading_path": loc.heading_path if loc.heading_path else None,
            "sheet_name": loc.sheet_name,
            "table_index": loc.table_index,
        },
    }


def format_source_for_direct(hit: SearchHit, rank: int) -> dict:
    """Direct Mode 어드바이저용 출처 정보 딕셔너리 생성."""
    loc = hit.source_location
    result = {
        "rank": rank,
        "document_title": hit.document_title,
        "section_title": hit.section_title,
        "content": hit.content,
        "document_type": hit.document_type,
        "score": round(hit.score, 3),
        "categories": hit.category_names,
        "source_location": {
            "file_path": loc.file_path,
            "file_url": loc.file_url,
            "page_number": loc.page_number,
            "page_range": list(loc.page_range) if loc.page_range else None,
            "heading_path": loc.heading_path if loc.heading_path else None,
            "sheet_name": loc.sheet_name,
            "table_index": loc.table_index,
        },
    }

    # 스크립트 타입이면 권장 응대 문구 추가
    if hit.document_type == "script":
        result["script_suggestion"] = _format_script(hit)

    return result


def _format_script(hit: SearchHit) -> str:
    """스크립트 문서를 권장 응대 문구로 포매팅."""
    from src.search.rag.prompt_templates import SCRIPT_SUGGESTION_TEMPLATE

    return SCRIPT_SUGGESTION_TEMPLATE.format(
        script_content=hit.content,
        doc_title=hit.document_title,
        section_title=hit.section_title or "",
    )
