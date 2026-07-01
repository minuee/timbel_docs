"""PDF 파싱 후처리 LLM 프롬프트.

노이즈 제거, 단어 분리 복원, 멀티컬럼 재정렬에 사용되는 프롬프트 빌더를 제공한다.

Version: 1.0.0
"""

from __future__ import annotations

PROMPT_VERSION = "1.0.0"


def build_noise_removal_prompt(page_text: str, page_number: int) -> str:
    """페이지 텍스트에서 노이즈를 식별하는 프롬프트를 생성한다.

    Args:
        page_text: 페이지 원문 텍스트 (최대 3000자까지 사용).
        page_number: 현재 페이지 번호.

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    return f"""다음은 PDF 문서의 {page_number}페이지에서 추출된 텍스트입니다.
본문이 아닌 노이즈 라인을 식별하세요.

## 노이즈 유형
- 페이지 번호 (예: "- 3 -", "Page 5/12", "3 / 10")
- 반복되는 헤더/푸터 (회사명, 문서 제목 반복, 기밀 등급, 날짜 등)
- 워터마크 텍스트 ("DRAFT", "Confidential", "대외비", "초안" 등)
- 저작권 표시 ("Copyright ©", "All rights reserved" 등)
- 각주 번호만 단독으로 있는 라인

## 보존 대상
- 본문 내용 (설명, 절차, 데이터)
- 표 내용
- 목차 항목
- 의미 있는 제목/소제목

## 판단 기준
- 매 페이지 동일 위치에 반복될 가능성이 높은 짧은 텍스트 → 노이즈
- 문서 내용과 무관한 메타 정보 → 노이즈
- 확신이 없으면 보존하세요

## 페이지 텍스트

{page_text[:3000]}

## 출력 형식

JSON만 반환하세요. 다른 텍스트는 포함하지 마세요.

```json
{{
  "noise_lines": ["제거할 라인의 정확한 텍스트1", "라인2"],
  "confidence": 0.85,
  "reasoning": "판단 근거 요약 (1문장)"
}}
```"""


def build_word_break_fix_prompt(
    line_end_fragment: str,
    next_line_start_fragment: str,
    surrounding_context: str,
) -> str:
    """줄바꿈/페이지 경계에서 분리된 단어 복원 프롬프트를 생성한다.

    Args:
        line_end_fragment: 이전 줄 끝의 단어 조각 (예: "autom-", "Ru").
        next_line_start_fragment: 다음 줄 시작의 단어 조각 (예: "atically", "st").
        surrounding_context: 주변 맥락 텍스트 (2-3 문장).

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    return f"""다음은 PDF에서 줄바꿈 또는 페이지 경계에서 분리된 것으로 의심되는 두 텍스트 조각입니다.
이 두 조각이 원래 하나의 단어인지 판단하세요.

## 조각 정보
- 이전 줄 끝: "{line_end_fragment}"
- 다음 줄 시작: "{next_line_start_fragment}"

## 주변 맥락
{surrounding_context}

## 판단 기준
- 하이픈("-")으로 끝나는 경우: 단어 분리일 가능성 높음 (예: "autom-" + "atically" → "automatically")
- 두 조각을 합치면 유효한 단어가 되는 경우: 분리된 단어임 (예: "Ru" + "st" → "Rust")
- 독립적으로 의미가 있는 두 단어인 경우: 분리가 아님 (예: "the" + "process")

## 출력 형식

JSON만 반환하세요.

```json
{{
  "should_merge": true,
  "merged_word": "automatically",
  "confidence": 0.95
}}
```

merge하지 않는 경우:
```json
{{
  "should_merge": false,
  "merged_word": "",
  "confidence": 0.9
}}
```"""


def build_column_reorder_prompt(page_text: str, page_number: int) -> str:
    """멀티컬럼 페이지의 올바른 읽기 순서를 결정하는 프롬프트를 생성한다.

    Args:
        page_text: 현재 추출된 텍스트 (컬럼 순서가 뒤섞일 수 있음).
        page_number: 현재 페이지 번호.

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    return f"""다음은 PDF {page_number}페이지에서 추출된 텍스트입니다.
이 페이지는 다단(multi-column) 레이아웃으로 감지되었으며, 텍스트 추출 순서가 올바르지 않을 수 있습니다.

## 현재 추출된 텍스트

{page_text[:4000]}

## 작업
1. 텍스트에서 각 컬럼에 해당하는 부분을 식별하세요.
2. 올바른 읽기 순서(왼쪽→오른쪽, 위→아래)로 텍스트를 재정렬하세요.
3. 컬럼 구분이 불명확하면 원본 순서를 유지하세요.

## 출력 형식

JSON만 반환하세요.

```json
{{
  "columns_detected": 2,
  "reordered_text": "올바른 순서로 재정렬된 전체 텍스트",
  "confidence": 0.8,
  "reordered": true
}}
```

재정렬이 불필요한 경우:
```json
{{
  "columns_detected": 1,
  "reordered_text": "",
  "confidence": 0.9,
  "reordered": false
}}
```"""
