"""테이블/이미지 캡션 감지 프롬프트.

표나 이미지 주변 텍스트에서 캡션(제목, 설명)을 추출한다.

Version: 1.0.0 (A/B 테스트용 버전 관리)
"""

from __future__ import annotations

PROMPT_VERSION = "1.0.0"


def build_caption_detection_prompt(context_text: str, element_type: str) -> str:
    """캡션 감지 프롬프트를 생성한다.

    Args:
        context_text: 표/이미지 주변 텍스트 (앞 100자 + 뒤 100자 권장).
        element_type: 대상 요소 타입 ("table" 또는 "image").

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    element_label = "표(Table)" if element_type == "table" else "이미지(Image)"
    caption_patterns = _get_patterns(element_type)

    return f"""당신은 문서 구조 분석 전문가입니다. 아래 텍스트는 문서에서 {element_label}의 바로 앞뒤에 위치한 텍스트입니다.
이 텍스트에서 해당 {element_label}의 캡션(제목 또는 설명)을 찾아주세요.

## 캡션 인식 패턴

{caption_patterns}

## 규칙

1. 캡션이 명확하게 존재하면 해당 텍스트를 추출하세요.
2. 캡션이 없으면 `null`을 반환하세요.
3. 캡션에서 번호 접두사는 유지하세요 (예: "표 3-1. 공정별 불량률" → 그대로 유지).
4. 캡션이 아닌 일반 본문 텍스트는 캡션으로 판단하지 마세요.
5. `[{element_label} 위치]` 마커를 기준으로 앞(before)과 뒤(after)를 구분합니다.

## 출력 형식

JSON 객체만 반환하세요. 다른 텍스트는 포함하지 마세요.

```json
{{"caption": "표 3-1. 공정별 불량률 현황"}}
```

또는 캡션이 없는 경우:

```json
{{"caption": null}}
```

## 주변 텍스트

[before]
{context_text}
[{element_label} 위치]
[after]"""


def _get_patterns(element_type: str) -> str:
    """요소 타입별 캡션 인식 패턴을 반환한다."""
    if element_type == "table":
        return """- "표 N.", "Table N.", "<표 N>", "[표 N]" 형태의 번호 + 제목
- "〈표 N〉", "【표 N】" 형태의 한국식 번호 매김
- 표 바로 위에 있는 짧은 설명문 (1줄, 볼드 또는 별도 스타일)
- 표 바로 아래에 있는 "(단위: 억원)" 같은 보조 설명도 캡션의 일부"""
    else:
        return """- "그림 N.", "Figure N.", "Fig. N.", "<그림 N>", "[그림 N]" 형태의 번호 + 제목
- "〈그림 N〉", "【그림 N】" 형태의 한국식 번호 매김
- "사진 N.", "도면 N.", "화면 N." 형태의 번호 + 제목
- 이미지 바로 아래에 있는 짧은 설명문 (1줄)
- "[출처: ...]" 형태의 출처 표기도 캡션의 일부"""
