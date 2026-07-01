"""한국어 document_type (Stage1 산출) → 영문 slug (_DOC_TYPE_HINTS 키) 매핑.

Stage1 의 _STAGE1_PROMPT 는 한국어 자유 문자열을 산출하고
(_STAGE1_PROMPT: 매뉴얼/보고서/사양서/단가표/계약서/논문/기타,
 _STAGE1_PPT_PROMPT: 발표자료/제안서/교육자료/보고서/기타),
block_segmentation._DOC_TYPE_HINTS 는 영문 slug 키를 쓴다 (faq/slide/manual/report/memo/generic).
이 모듈이 둘을 잇는다. LLM 자유 문자열이므로 부분 일치로 흡수.
"""
from __future__ import annotations

# (한국어 키워드, slug) — 부분 일치. 앞쪽이 우선.
_RULES: list[tuple[str, str]] = [
    ("faq", "faq"),
    ("자주", "faq"),
    ("질문", "faq"),
    ("발표", "slide"),
    ("제안", "slide"),
    ("교육자료", "slide"),
    ("슬라이드", "slide"),
    ("매뉴얼", "manual"),
    ("사양", "manual"),
    ("지침", "manual"),
    ("가이드", "manual"),
    ("보고서", "report"),
    ("논문", "report"),
    ("사례집", "report"),
    ("메모", "memo"),
    ("회의", "memo"),
]


def to_slug(document_type: str) -> str:
    """한국어/영문 document_type → _DOC_TYPE_HINTS slug. 미매칭 시 'generic'."""
    if not document_type:
        return "generic"
    low = document_type.strip().lower()
    for keyword, slug in _RULES:
        if keyword in low:
            return slug
    return "generic"
