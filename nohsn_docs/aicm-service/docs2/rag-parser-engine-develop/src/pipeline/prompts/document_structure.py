"""문서 구조 분석 프롬프트.

문서 전체의 구조적 특성을 파악한다: 문서 유형, 섹션 구분, 언어, 격식 수준.

Version: 1.0.0 (A/B 테스트용 버전 관리)
"""

from __future__ import annotations

PROMPT_VERSION = "1.0.0"


def build_structure_analysis_prompt(
    text_preview: str,
    headings: list[dict],
) -> str:
    """문서 구조 분석 프롬프트를 생성한다.

    Args:
        text_preview: 문서 앞부분 텍스트 (약 3000자 이내 권장).
        headings: 감지된 제목 목록. 각 dict는 {"text": str, "level": int, "offset": int} 형태.

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    headings_text = _format_headings(headings)

    return f"""당신은 문서 분류 전문가입니다. 아래 문서의 앞부분 텍스트와 감지된 제목 목록을 분석하여 문서의 구조적 특성을 파악하세요.

## 분석 항목

### 1. document_type (문서 유형)
다음 중 하나를 선택하세요:
- `manual`: 사용 설명서, 매뉴얼, 가이드, 운영 절차서
- `report`: 보고서, 분석 리포트, 결과 보고
- `specification`: 기술 사양서, 설계 문서, API 문서, 스펙
- `minutes`: 회의록, 의사록
- `letter`: 공문, 서한, 통지서
- `form`: 양식, 신청서, 체크리스트
- `article`: 논문, 기사, 칼럼, 블로그 포스트
- `legal`: 계약서, 약관, 법령, 규정
- `presentation`: 발표 자료, 슬라이드 노트
- `reference`: 사전, 용어집, FAQ, 참조 문서
- `other`: 위에 해당하지 않는 경우

### 2. sections (섹션 구분)
문서의 큰 구조를 구분하세요. 각 섹션의 type:
- `cover`: 표지, 문서 정보 (제목, 작성자, 날짜 등)
- `toc`: 목차
- `body`: 본문 (핵심 내용)
- `appendix`: 부록, 첨부
- `references`: 참고문헌, 출처

### 3. language (언어)
- `ko`: 한국어 중심
- `en`: 영어 중심
- `mixed`: 한영 혼합 (기술 용어가 영어인 한국어 문서도 `ko`로 분류)

### 4. formality (격식 수준)
- `formal`: 공문, 공식 보고서, 계약서 등 격식체
- `informal`: 메모, 블로그, 비공식 문서
- `technical`: 기술 문서, 코드 문서, 사양서 (격식보다 정확성 중심)

## 출력 형식

JSON 객체만 반환하세요. 다른 텍스트는 포함하지 마세요.

```json
{{
  "document_type": "manual",
  "sections": [
    {{"type": "cover", "start": 0, "end": 150}},
    {{"type": "toc", "start": 151, "end": 400}},
    {{"type": "body", "start": 401, "end": 2800}},
    {{"type": "references", "start": 2801, "end": 3000}}
  ],
  "language": "ko",
  "formality": "technical"
}}
```

## 감지된 제목 목록

{headings_text}

## 문서 앞부분 텍스트

{text_preview}"""


def _format_headings(headings: list[dict]) -> str:
    """제목 목록을 텍스트로 포맷한다."""
    if not headings:
        return "(감지된 제목 없음)"

    lines: list[str] = []
    for h in headings:
        level = h.get("level", 0)
        text = h.get("text", "")
        offset = h.get("offset", "?")
        indent = "  " * (level - 1) if level > 0 else ""
        lines.append(f"{indent}- [L{level}] offset={offset}: {text}")
    return "\n".join(lines)
