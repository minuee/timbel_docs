"""문서 처리 난이도 평가 -- specs/02 3.1 공식 그대로 구현."""

from __future__ import annotations

from src.pipeline.models.document import ProcessingDifficulty
from src.pipeline.models.parse_result import ParseResult

# 요소별 가중치
_WEIGHTS: dict[str, float] = {
    "table_density": 0.3,
    "image_density": 0.25,
    "layout_complexity": 0.2,
    "ocr_dependency": 0.15,
    "doc_size": 0.1,
}


def evaluate_difficulty(
    parse_result: ParseResult,
) -> tuple[ProcessingDifficulty, float, dict[str, float]]:
    """문서 처리 난이도를 0.0 ~ 1.0 스코어로 평가한다.

    Returns:
        (difficulty_enum, score, factors_dict)
    """
    factors: dict[str, float] = {}
    total_pages = max(len(parse_result.pages), 1)

    # 표 밀도 (전체 콘텐츠 대비 표 비율)
    table_chars = sum(len(t.markdown) for t in parse_result.tables)
    total_chars = len(parse_result.raw_text) + table_chars
    factors["table_density"] = min(table_chars / max(total_chars, 1), 1.0)

    # 이미지 밀도 (이미지 포함 페이지 비율)
    image_pages = len({img.page_number for img in parse_result.images})
    factors["image_density"] = min(image_pages / total_pages, 1.0)

    # 레이아웃 복잡도 (다단/혼합 레이아웃 페이지 비율)
    complex_pages = sum(1 for p in parse_result.pages if p.layout_type != "single")
    factors["layout_complexity"] = min(complex_pages / total_pages, 1.0)

    # OCR 의존도 (OCR 처리 페이지 비율)
    ocr_pages = sum(1 for p in parse_result.pages if p.ocr_used)
    factors["ocr_dependency"] = min(ocr_pages / total_pages, 1.0)

    # 문서 크기 (100 페이지를 1.0 으로 정규화)
    factors["doc_size"] = min(total_pages / 100, 1.0)

    # 가중 합산
    score = sum(factors[k] * _WEIGHTS[k] for k in _WEIGHTS)

    # 등급 판정
    if score < 0.3:
        difficulty = ProcessingDifficulty.LOW
    elif score < 0.6:
        difficulty = ProcessingDifficulty.MEDIUM
    elif score < 0.8:
        difficulty = ProcessingDifficulty.HIGH
    else:
        difficulty = ProcessingDifficulty.CRITICAL

    return difficulty, round(score, 4), factors
