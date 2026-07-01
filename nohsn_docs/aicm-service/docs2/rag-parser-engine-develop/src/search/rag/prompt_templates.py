"""RAG 프롬프트 템플릿 — 한국어, 출처 인용 규칙, 표 전용 규칙 포함."""

from __future__ import annotations

# ============================================================
# Generation Mode 기본 RAG 프롬프트
# ============================================================
RAG_PROMPT_TEMPLATE = """당신은 {organization_type}의 AI 어시스턴트입니다.
아래 참고 자료만을 바탕으로 질문에 답변하세요.
참고 자료에 없는 내용은 "해당 정보를 찾을 수 없습니다"라고 답하세요.

### 참고 자료
{context}

### 출처 목록
{source_list}

### 질문
{question}

### 답변 규칙
1. 참고 자료의 내용만 사용하여 답변하세요.
2. 답변 내에서 해당 내용의 근거를 **인라인 인용 마커** [1], [2] 등으로 표시하세요.
   예: "신용등급 AA 이상은 한도 5,000만원입니다 [1]."
3. 여러 자료를 종합한 경우 관련된 모든 출처 번호를 함께 표시하세요.
   예: "세 가지 방법이 권장됩니다 [1][3]."
4. 답변 마지막에 사용한 출처를 요약하지 마세요 — 인라인 마커만으로 충분합니다.
5. 참고 자료에 없는 내용을 추측하지 마세요. 해당 정보가 부족하면 명시하세요.
6. 친절하고 자연스러운 어조로 답변하세요.

답변:"""

# ============================================================
# 표 데이터 답변 규칙 (표 청크가 포함된 경우 추가)
# ============================================================
TABLE_RAG_RULES = """
### 표 데이터 답변 규칙
1. 표에서 특정 값을 찾는 질문이면, 정확한 셀 값을 인용하세요.
2. 비교 질문이면, 관련 행들을 표 형태로 정리하여 답변하세요.
3. 집계 질문(합계, 평균, 최대/최소)이면, 참고자료의 요약 정보를 활용하세요.
   참고자료에 집계 정보가 없으면 "표 전체를 확인해야 정확한 답변이 가능합니다"라고 안내하세요.
4. 답변에 수치를 포함할 때는 반드시 단위를 함께 표시하세요.
"""

# ============================================================
# 표 포함 Generation Mode 프롬프트
# ============================================================
RAG_PROMPT_TEMPLATE_WITH_TABLE = """당신은 {organization_type}의 AI 어시스턴트입니다.
아래 참고 자료만을 바탕으로 질문에 답변하세요.
참고 자료에 없는 내용은 "해당 정보를 찾을 수 없습니다"라고 답하세요.

### 참고 자료
{context}

### 출처 목록
{source_list}

### 질문
{question}

### 답변 규칙
1. 참고 자료의 내용만 사용하여 답변하세요.
2. 답변 내에서 해당 내용의 근거를 **인라인 인용 마커** [1], [2] 등으로 표시하세요.
   예: "신용등급 AA 이상은 한도 5,000만원입니다 [1]."
3. 여러 자료를 종합한 경우 관련된 모든 출처 번호를 함께 표시하세요.
4. 답변 마지막에 사용한 출처를 요약하지 마세요 — 인라인 마커만으로 충분합니다.
5. 참고 자료에 없는 내용을 추측하지 마세요. 해당 정보가 부족하면 명시하세요.
6. 친절하고 자연스러운 어조로 답변하세요.
{table_rules}
답변:"""

# ============================================================
# Direct Mode 스크립트 포매팅 템플릿
# ============================================================
SCRIPT_SUGGESTION_TEMPLATE = """[권장 응대 문구]
{script_content}

[출처: {doc_title} > {section_title}]"""

# ============================================================
# 컨텍스트 구분선
# ============================================================
CONTEXT_SEPARATOR = "\n\n---\n\n"

# ============================================================
# 단일 참고 자료 블록 포맷 (번호 인용 마커 포함)
# ============================================================
CONTEXT_BLOCK_TEMPLATE = "[{ref_num}] {doc_title} > {section_title}\n{content}"


def format_source_list(sources: list[dict]) -> str:
    """프롬프트용 출처 목록 생성.

    각 소스를 '[번호] 문서명 > 섹션명 (페이지)' 형태로 나열.
    LLM이 인용 마커와 출처를 대조할 수 있게 한다.
    """
    lines: list[str] = []
    for s in sources:
        label = s.get("doc_title", "")
        section = s.get("section", "")
        if section:
            label = f"{label} > {section}"
        page = s.get("page_info", "")
        if page:
            label = f"{label} ({page})"
        lines.append(f"[{s['ref_num']}] {label}")
    return "\n".join(lines)


def has_table_chunks(hits_metadata: list[dict]) -> bool:
    """검색 결과에 표 청크가 포함되어 있는지 확인."""
    for meta in hits_metadata:
        layer = meta.get("layer", "")
        if layer in ("row_nl", "table_markdown", "table_summary"):
            return True
        if meta.get("is_table", False):
            return True
    return False


def build_rag_prompt(
    context: str,
    question: str,
    source_list_entries: list[dict] | None = None,
    organization_type: str = "고객서비스센터",
    include_table_rules: bool = False,
) -> str:
    """RAG 프롬프트 조립.

    Args:
        context: 참고 자료 블럭들을 조립한 문자열.
        question: 사용자 질문.
        source_list_entries: [{"ref_num": 1, "doc_title": ..., "section": ..., "page_info": ...}]
        organization_type: 조직 유형 (프롬프트 페르소나).
        include_table_rules: 표 전용 답변 규칙 포함 여부.
    """
    sl = format_source_list(source_list_entries or [])
    if include_table_rules:
        return RAG_PROMPT_TEMPLATE_WITH_TABLE.format(
            organization_type=organization_type,
            context=context,
            source_list=sl,
            question=question,
            table_rules=TABLE_RAG_RULES,
        )
    return RAG_PROMPT_TEMPLATE.format(
        organization_type=organization_type,
        context=context,
        source_list=sl,
        question=question,
    )
