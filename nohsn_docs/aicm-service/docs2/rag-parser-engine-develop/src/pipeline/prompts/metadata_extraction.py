"""블럭 수준 메타데이터 추출 프롬프트.

개별 블럭에서 키워드, 개체명, 토픽을 추출한다.

Version: 1.0.0 (A/B 테스트용 버전 관리)
"""

from __future__ import annotations

PROMPT_VERSION = "1.0.0"


def build_metadata_prompt(block_content: str, block_type: str) -> str:
    """블럭 메타데이터 추출 프롬프트를 생성한다.

    Args:
        block_content: 블럭의 텍스트 내용.
        block_type: 블럭 타입 (paragraph, heading_1, code 등).

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    type_hint = _get_type_hint(block_type)

    return f"""당신은 정보 추출 전문가입니다. 아래 텍스트 블럭에서 메타데이터를 추출하세요.

## 블럭 정보
- 블럭 타입: `{block_type}`
{type_hint}

## 추출 항목

### 1. keywords (핵심 키워드)
- 이 블럭의 내용을 검색할 때 사용할 키워드 3~7개
- 고유명사, 전문 용어, 핵심 개념 위주
- 너무 일반적인 단어(것, 이, 등, 및)는 제외
- 한국어 키워드는 한국어 그대로, 영어 고유명사는 영어 그대로

### 2. entities (개체명)
- 블럭에 등장하는 고유명사를 추출
- 각 개체의 type: `person`, `organization`, `product`, `location`, `date`, `regulation`, `technology`, `metric`
- 해당하는 개체가 없으면 빈 배열

### 3. topic (토픽)
- 이 블럭이 다루는 주제를 한 단어 또는 짧은 구문으로 (예: "성능 요구사항", "설치 절차", "비용 분석")

## 출력 형식

JSON 객체만 반환하세요. 다른 텍스트는 포함하지 마세요.

```json
{{
  "keywords": ["SMT", "리플로우", "온도 프로파일", "솔더 페이스트"],
  "entities": [
    {{"name": "삼성전자", "type": "organization"}},
    {{"name": "IPC-A-610", "type": "regulation"}}
  ],
  "topic": "SMT 리플로우 공정 조건"
}}
```

## 블럭 내용

{block_content}"""


def build_batch_metadata_prompt(chunks_text: str) -> str:
    """배치 메타데이터 추출 프롬프트 (여러 청크 동시 처리).

    Args:
        chunks_text: "--- 청크 0 ---\\n내용\\n\\n--- 청크 1 ---\\n내용" 형식

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    return f"""당신은 정보 추출 전문가입니다. 아래 여러 청크에서 각각 메타데이터를 추출하세요.

## 추출 항목 (각 청크별)

### 1. keywords (핵심 키워드)
- 검색에 사용할 키워드 3~7개
- 고유명사, 전문 용어, 핵심 개념 위주
- 너무 일반적인 단어(것, 이, 등, 및)는 제외
- 한국어는 한국어, 영어 고유명사는 영어로

### 2. entities (개체명)
- 고유명사(조직명/제품명/인명/지명/법규/기술/지표 등)를 추출
- **문자열 배열**로 반환. 이름만 적고 타입은 포함하지 않음
- 해당 없으면 빈 배열

### 3. topic (토픽)
- 해당 청크의 주제를 한 단어 또는 짧은 구문

## 출력 형식

JSON 배열만 반환. 청크 순서대로 각 요소가 대응.
배열 길이는 입력 청크 수와 **반드시 동일**해야 한다.

```json
[
  {{
    "keywords": ["SMT", "리플로우"],
    "entities": ["삼성전자", "IPC-A-610"],
    "topic": "SMT 공정"
  }},
  {{
    "keywords": ["품질 검사", "AOI"],
    "entities": [],
    "topic": "품질 검사 절차"
  }}
]
```

## 청크들

{chunks_text}"""


def _get_type_hint(block_type: str) -> str:
    """블럭 타입별 추출 힌트를 반환한다."""
    hints: dict[str, str] = {
        "heading_1": "- 이 블럭은 대제목입니다. topic은 이 제목이 가리키는 섹션의 주제를 반영하세요.",
        "heading_2": "- 이 블럭은 중제목입니다. topic은 이 하위 섹션의 주제를 반영하세요.",
        "heading_3": "- 이 블럭은 소제목입니다. topic은 이 세부 항목의 주제를 반영하세요.",
        "code": "- 이 블럭은 코드입니다. keywords에 함수명, 라이브러리명, 명령어 등을 포함하세요.",
        "table": "- 이 블럭은 표입니다. keywords에 컬럼명과 핵심 데이터 항목을 포함하세요.",
        "quote": "- 이 블럭은 인용문입니다. 인용 출처가 있으면 entities에 포함하세요.",
        "callout": "- 이 블럭은 강조/알림입니다. 경고, 주의, 참고 등의 맥락을 topic에 반영하세요.",
        "bulleted_list": "- 이 블럭은 목록입니다. 각 항목의 공통 주제를 topic으로 추출하세요.",
        "numbered_list": "- 이 블럭은 순서 목록입니다. 절차/단계의 전체 주제를 topic으로 추출하세요.",
    }
    return hints.get(block_type, "")
