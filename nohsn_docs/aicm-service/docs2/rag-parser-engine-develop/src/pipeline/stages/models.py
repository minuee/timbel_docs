"""3단계 LLM 파이프라인 데이터 모델.

Stage 1 → DocumentContext (문서 이해)
Stage 2 → RawBlock (블럭 분할)
Stage 3 → RawBlock 보강 (table_nl, image_description, keywords)
StageResult → 전체 파이프라인 결과
PageData → 2단계 입력용 페이지 데이터
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentContext(BaseModel):
    """1단계 출력: 문서 전체 맥락."""

    document_type: str = ""  # 매뉴얼, 보고서, 사양서, 단가표, etc.
    title: str = ""
    core_topic: str = ""
    noise_patterns: list[str] = Field(default_factory=list)
    search_scenarios: list[str] = Field(default_factory=list)
    language: str = "ko"
    # PPT 모드에서만 채워지는 주요 섹션/주제 그룹 (Stage2 가 슬라이드 분할 시 참고).
    key_sections: list[str] = Field(default_factory=list)


class RawBlock(BaseModel):
    """2단계 출력: 분할된 블럭."""

    type: str  # heading_1, paragraph, table, image, noise, etc.
    content: str
    page: int
    reason: str = ""  # noise 사유
    table_nl: str = ""  # 3단계에서 채워짐
    image_description: str = ""  # 3단계에서 채워짐
    keywords: list[str] = Field(default_factory=list)  # 3단계에서 채워짐
    properties: dict = Field(default_factory=dict)

    # Ontology classification (Phase A)
    nature: str = ""  # fact/opinion/schedule/record/reference/casual
    time_reference: dict = Field(default_factory=dict)  # {"raw": "...", "resolved": "ISO", "basis": "..."}
    entities: dict = Field(default_factory=dict)  # {"speakers": [], "people": [], "orgs": [], "locations": []}
    domain_category_ids: list[dict] = Field(default_factory=list)  # [{"id": "...", "name": "...", "confidence": 0.9}]
    classification_confidence: float = 0.0
    classification_reasoning: str = ""


class PageData(BaseModel):
    """2단계 입력용 페이지 데이터."""

    page_num: int
    image_bytes: bytes
    extracted_text: str
    # Stage1.5 LayoutMapper 가 채우는 표/도표 영역 — Stage2 가 hint 로 사용.
    # 각 항목: {"bbox": [x0,y0,x1,y1], "kind": "box_table"|"grid_table", "confidence": float}
    detected_tables: list[dict] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class StageResult(BaseModel):
    """전체 파이프라인 결과."""

    document_context: DocumentContext
    blocks: list[RawBlock]
    noise_blocks: list[RawBlock]  # 제외된 블럭
    stats: dict = Field(default_factory=dict)
