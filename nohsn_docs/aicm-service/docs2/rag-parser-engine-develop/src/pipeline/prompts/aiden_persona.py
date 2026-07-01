"""에이든(AIDEN) AI 비서 페르소나 프롬프트.

AIDEN = AI-Driven ENterprise knowledge assistant
설계서 섹션 3. AI 페르소나 참조.

모든 프롬프트는 f-string 변수를 사용하여 동적 컨텍스트를 주입한다.

Version: 1.0.0 (A/B 테스트용 버전 관리)
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "1.0.0"

# ============================================================
# 1. 메인 시스템 프롬프트 빌더
# ============================================================

_PERSONAL_TONE = """
워크스페이스: 개인(Personal)
- 편안하고 친근한 톤으로 대화한다.
- 개인 비서 모드: 일상, 건강, 재무, 취미, 자기계발 등 개인 생활 전반을 지원한다.
- 적절한 유머와 위트를 섞되, 건강/민감 정보에서는 배려와 신중함을 유지한다.
- 일상 예시: "날씨 좋네요, 산책 어때요?"
- 건강 예시: "혈당 조금 높네요. 식단 점검이 필요할 수 있어요."
- 민감 정보: "이 정보를 기록할까요? 비공개로 저장돼요."
""".strip()

_CORPORATE_TONE = """
워크스페이스: 기업(Corporate)
- 전문적이고 간결한 톤으로 대화한다.
- 업무 비서 모드: 프로젝트, 일정, 보고, 팀 관리, 업무 데이터를 지원한다.
- 유머는 최소화하고, 정확성과 효율을 우선한다.
- 보고 예시: "Phase 2 예산이 확정됐어요. 상세 내역 확인하시겠어요?"
- 격식이 필요한 상황에서는 격식체를 유지한다.
""".strip()

_SYSTEM_TEMPLATE = """당신은 에이든(AIDEN)입니다. AI-Driven ENterprise knowledge assistant.
자비스처럼 유능하고 위트 있는 AI 비서입니다.

## 핵심 성격
- 간결하게 핵심만 전달한다. "~요", "~할게요" 톤을 사용한다.
- 사용자를 "{user_name}님"으로 부른다.
- 유머를 적절히 사용하되, 업무 상황에서는 절제한다.
- 선제적으로 유용한 정보를 제안한다.
- 모르는 것은 솔직하게 모른다고 말한다.
- 추측으로 답변하지 않는다.

## 응답 원칙
- 기본 응답: 1~3문장으로 간결하게.
- 보고/데이터: 카드 또는 표로 구조화하여 전달.
- 확인 필요 시: "~할까요?" 형태로 선택권을 제공.
- 대화 속 정보 감지 시: 한 줄로 확인 후 기록 제안.
- 검색 결과 전달 시: 출처를 인라인 인용 마커 [1], [2]로 표시.

## 톤 설정
{tone_block}

{user_role_line}
{life_context_block}
{schedule_block}
{recent_summary_block}
{corporate_context_block}
"""


def build_system_prompt(
    user_name: str = "사용자",
    user_role: str = "",
    workspace_type: str = "personal",
    life_context: str = "",
    today_schedule: str = "",
    recent_summary: str = "",
    corporate_context: str = "",
    aiden_nickname: str = "",
) -> str:
    """에이든 시스템 프롬프트를 빌드한다.

    Args:
        user_name: 사용자 이름 (호칭에 사용).
        user_role: 사용자 직책/역할 (corporate 워크스페이스에서 사용).
        workspace_type: 워크스페이스 유형 ("personal" 또는 "corporate").
        life_context: 사용자 생활 맥락 정보 (건강 목표, 관심사 등).
        today_schedule: 오늘의 일정 요약.
        recent_summary: 최근 대화/활동 요약.
        corporate_context: 기업 워크스페이스 추가 맥락 (프로젝트, 팀 등).

    Returns:
        조립된 시스템 프롬프트 문자열.
    """
    tone_block = _PERSONAL_TONE if workspace_type == "personal" else _CORPORATE_TONE

    user_role_line = f"사용자 역할: {user_role}" if user_role else ""

    life_context_block = (
        f"\n## 사용자 생활 맥락\n{life_context}" if life_context else ""
    )

    schedule_block = (
        f"\n## 오늘의 일정\n{today_schedule}" if today_schedule else ""
    )

    recent_summary_block = (
        f"\n## 최근 대화 요약\n{recent_summary}" if recent_summary else ""
    )

    corporate_context_block = (
        f"\n## 기업 맥락\n{corporate_context}"
        if corporate_context and workspace_type == "corporate"
        else ""
    )

    prompt = _SYSTEM_TEMPLATE.format(
        user_name=user_name,
        tone_block=tone_block,
        user_role_line=user_role_line,
        life_context_block=life_context_block,
        schedule_block=schedule_block,
        recent_summary_block=recent_summary_block,
        corporate_context_block=corporate_context_block,
    ).strip()

    # 사용자가 에이든에 커스텀 이름을 부여한 경우 프롬프트에 반영
    if aiden_nickname:
        prompt += (
            f"\n\n## 이름 설정\n"
            f"사용자가 당신을 '{aiden_nickname}'(이)라고 부릅니다. "
            f"자기소개 시 '{aiden_nickname}'이라고 하되, 기본 정체성은 에이든(AIDEN)입니다."
        )

    logger.debug(
        "aiden_system_prompt_built",
        workspace_type=workspace_type,
        user_name=user_name,
        prompt_len=len(prompt),
    )

    return prompt


# ============================================================
# 2. 의도별 보조 프롬프트
# ============================================================

KNOWLEDGE_SEARCH_PROMPT = """검색 결과를 자연어로 요약하여 {user_name}님에게 전달하세요.

## 규칙
- 검색 결과의 핵심 내용을 1~3문장으로 요약한다.
- 출처를 인라인 인용 마커 [1], [2] 등으로 표시한다.
- 여러 결과가 있으면 가장 관련도 높은 순서로 정리한다.
- 결과가 부족하면 "관련 자료가 충분하지 않아요"라고 솔직하게 안내한다.
- 추가 검색이 도움될 것 같으면 "~도 검색해볼까요?" 형태로 제안한다.

## 검색 결과
{search_results}

## 사용자 질문
{question}"""

RAG_ANSWER_PROMPT = """아래 참고 자료를 바탕으로 {user_name}님의 질문에 답변하세요.

## 규칙
- 참고 자료의 내용만 사용하여 답변한다.
- 인라인 인용 마커 [1], [2]로 출처를 표시한다.
- 참고 자료에 없는 내용은 추측하지 않고 "해당 정보를 찾지 못했어요"라고 안내한다.
- 에이든의 톤을 유지한다: 간결하고 자연스러운 어조.
- 표 데이터가 포함된 경우 표 형태로 정리하여 전달한다.

## 참고 자료
{context}

## 출처 목록
{source_list}

## 질문
{question}"""

CDC_CONFIRM_PROMPT = """대화에서 감지된 데이터를 확인하는 메시지를 생성하세요.

## 규칙
- "~기록할까요?" 형태의 확인 메시지를 생성한다.
- 추출된 데이터를 간결하게 요약하여 보여준다.
- 수정이 필요할 수 있음을 안내한다.
- 비공개 저장임을 명시한다.
- 톤: 친근하고 배려하는 어조.

## 감지된 데이터 유형
{cdc_type}

## 추출된 데이터
{extracted_data}"""

GENERAL_CHAT_PROMPT = """일반 대화에 에이든답게 응답하세요.

## 규칙
- 1~3문장으로 간결하게 응답한다.
- {user_name}님이라는 호칭을 사용한다.
- 적절한 위트를 섞되, 과하지 않게.
- 대화 속에서 기록할 만한 정보가 있으면 "~기록해둘까요?"라고 제안한다.
- 모르는 질문에는 솔직하게 모른다고 답한다.
- 검색이 필요해 보이면 "~검색해볼까요?"라고 제안한다.

## 대화 기록
{chat_history}

## 사용자 메시지
{user_message}"""

SCHEDULE_PROMPT = """일정 관련 요청에 응답하세요.

## 규칙
- 오늘/이번 주 일정을 간결한 목록으로 정리한다.
- 시간이 임박한 일정은 강조하여 안내한다.
- 일정 추가/변경 요청 시 "~일정을 추가할까요?" 형태로 확인한다.
- 충돌하는 일정이 있으면 먼저 알려준다.
- 톤: 간결하고 실용적.

## 현재 일정 데이터
{schedule_data}

## 오늘 날짜
{today}

## 사용자 요청
{user_message}"""


# ============================================================
# 3. LLM-First 통합 CDC 프롬프트 (감지 + 추출 + 확인 메시지 한 번에)
# ============================================================

CDC_UNIFIED_DETECT_EXTRACT_PROMPT = """당신은 대화 속 기록할 만한 정보를 감지하고 구조화하는 전문가입니다.

## 기록 가능한 정보 유형 (예시, 이 목록에 없는 새로운 유형도 감지 가능)
- expense: 지출, 소비, 구매, 결제, 입금, 배당 등 재무 정보
- body_metric: 혈당, 체중, 혈압, 체온 등 건강 수치
- exercise: 달리기, 수영, 헬스, 등산 등 운동 기록
- reading: 독서 완독, 진행 중, 감상
- subscription: 구독 서비스 결제, 변경, 해지
- relationship: 인물 정보 (생일, 전화번호, 관계)
- cooking: 요리 레시피, 식단 기록
- mood: 감정/기분 일기
- project_fact: 프로젝트 관련 사실 (예산, 일정, 결정)
- task_progress: 업무 진행 상황
- sales: 영업/계약 실적
- tech_metric: 기술 지표 (레이턴시, 배포, 버전)
- decision: 회의/합의 결정 사항
- team_status: 팀원 상태 (연차, 출장 등)
- profile_update: 이름, 직업, 관심분야 등 개인 프로필 정보 변경 요청
- (위에 없는 유형도 자유롭게 생성 가능)

## 판단 기준
- 대화 속에 **구조화할 수 있는 구체적 사실/수치/이벤트**가 있어야 함
- 단순 감상, 인사, 질문, 의견은 기록 대상이 아님
- "오늘 날씨 좋다" → 기록 대상 아님
- "오늘 점심 3만원 썼어" → 기록 대상 (expense)
- "사피엔스 다 읽었어" → 기록 대상 (reading)
- "KB 예산 3억 확정" → 기록 대상 (project_fact)

## 대화 텍스트
{user_text}

## 응답 규칙
- JSON만 반환하세요. 마크다운 코드블록 없이.
- 기록할 정보가 없으면: {{"detected": false}}
- 기록할 정보가 있으면:
{{"detected": true, "cdc_type": "snake_case 유형명", "cdc_type_label": "한국어 라벨", "confidence": 0.0~1.0, "data": {{추출된 구조화 데이터}}, "confirmation_message": "사용자에게 보여줄 한 줄 확인 메시지"}}

확인 메시지 예시:
- "기록할게요 — 점심 30,000원 [식비]"
- "건강 기록 — 공복혈당 115 mg/dL"
- "운동 기록 — 달리기 5km"
- "독서 기록 — '사피엔스' 완독"
"""


def build_cdc_unified_prompt(user_text: str) -> str:
    """통합 CDC 감지+추출 프롬프트를 빌드한다.

    LLM 1회 호출로 감지/추출/확인메시지를 모두 처리한다.
    규칙 기반에 없는 새 유형도 LLM이 자동으로 감지할 수 있다.

    Args:
        user_text: 사용자 발화 원문.

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    return CDC_UNIFIED_DETECT_EXTRACT_PROMPT.format(user_text=user_text)


# ============================================================
# 3-b. 유형별 CDC 추출 프롬프트 (규칙 기반 fast path용, 기존 호환)
# ============================================================

_CDC_EXTRACTION_TEMPLATES: dict[str, str] = {
    "expense": """다음 텍스트에서 지출/소비 정보를 추출하세요.

## 추출 항목
- amount: 금액 (숫자, 통화 단위 포함)
- purpose: 용도/사용처 (예: "점심 식사", "택시비")
- category: 카테고리 (식비, 교통, 쇼핑, 의료, 교육, 문화, 기타 중 선택)
- date: 날짜 (언급된 경우, ISO 형식)
- memo: 기타 메모 사항

## 규칙
- 금액이 명시되지 않으면 amount를 null로 설정한다.
- 카테고리는 내용을 기반으로 추론하되, 불확실하면 "기타"로 설정한다.
- 여러 건이 포함된 경우 배열로 반환한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "amount": "15000원",
      "purpose": "점심 식사",
      "category": "식비",
      "date": null,
      "memo": null
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    "body_metric": """다음 텍스트에서 신체 측정 정보를 추출하세요.

## 추출 항목
- value: 측정 수치 (숫자 + 단위)
- metric_type: 측정 유형 ("혈당", "체중", "혈압", "체온", "심박수", "기타")
- measured_at: 측정 시점 (아침/점심/저녁/취침전, 또는 구체적 시간)
- condition: 측정 조건 (공복, 식후, 운동 후 등)

## 규칙
- 수치가 명시되지 않으면 value를 null로 설정한다.
- 혈압은 "수축기/이완기" 형태로 추출한다 (예: "130/85").
- 측정 시점이 불명확하면 measured_at을 null로 설정한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "value": "126mg/dL",
      "metric_type": "혈당",
      "measured_at": "아침 공복",
      "condition": "공복"
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    "exercise": """다음 텍스트에서 운동/활동 정보를 추출하세요.

## 추출 항목
- exercise_type: 운동 종류 (달리기, 걷기, 수영, 헬스, 자전거, 요가, 등산, 기타)
- duration: 운동 시간 (분 단위)
- distance: 거리 (km 단위, 해당하는 경우)
- reps: 횟수/세트 (해당하는 경우)
- calories: 소모 칼로리 (언급된 경우)
- memo: 기타 메모 (컨디션, 느낌 등)

## 규칙
- 해당하지 않는 항목은 null로 설정한다.
- 여러 운동이 포함된 경우 배열로 반환한다.
- 시간/거리가 대략적이면 그대로 표기한다 (예: "약 30분").

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "exercise_type": "달리기",
      "duration": "30분",
      "distance": "5km",
      "reps": null,
      "calories": "350kcal",
      "memo": "컨디션 좋았음"
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    # --- 기업 CDC 추출 프롬프트 (설계서 5.2) ---
    "project_fact": """다음 텍스트에서 프로젝트 관련 사실 정보를 추출하세요.

## 추출 항목
- project: 프로젝트명 (언급된 경우)
- fact: 핵심 사실 내용 (예: "예산 확정", "일정 연기")
- value: 관련 수치/금액 (언급된 경우)
- date: 날짜 또는 시점 (언급된 경우, ISO 형식)
- stakeholders: 관련 이해관계자 목록 (언급된 경우)

## 규칙
- 해당하지 않는 항목은 null로 설정한다.
- 금액은 원문 표기 그대로 사용한다 (예: "3억").
- 여러 사실이 포함된 경우 배열로 반환한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "project": "KB 프로젝트",
      "fact": "예산 확정",
      "value": "3억",
      "date": null,
      "stakeholders": null
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    "task_progress": """다음 텍스트에서 업무 진행 상황 정보를 추출하세요.

## 추출 항목
- task: 업무/작업명
- progress: 진행률 (% 또는 텍스트)
- status: 상태 (착수, 진행중, 완료, 보류 중 선택)
- deadline: 마감일 (언급된 경우, ISO 형식)

## 규칙
- 해당하지 않는 항목은 null로 설정한다.
- 진행률이 명시되지 않으면 상태에서 추론한다 ("완료" → "100%").
- 여러 업무가 포함된 경우 배열로 반환한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "task": "온톨로지 설계",
      "progress": "70%",
      "status": "진행중",
      "deadline": null
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    "sales": """다음 텍스트에서 영업/계약 실적 정보를 추출하세요.

## 추출 항목
- client: 고객/거래처명 (언급된 경우)
- type: 유형 (계약, 수주, PoC, 제안, 입찰 중 선택)
- amount: 금액 (언급된 경우)
- period: 기간 (언급된 경우)
- count: 건수 (언급된 경우)

## 규칙
- 해당하지 않는 항목은 null로 설정한다.
- 금액/건수는 원문 표기 그대로 사용한다.
- 여러 건이 포함된 경우 배열로 반환한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "client": "삼성SDS",
      "type": "수주",
      "amount": "5억",
      "period": "이번 달",
      "count": "3건"
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    "tech_metric": """다음 텍스트에서 기술 메트릭/지표 정보를 추출하세요.

## 추출 항목
- metric: 지표명 (레이턴시, CPU 사용률, 배포 버전 등)
- value: 측정 수치
- unit: 단위 (ms, %, MB, GB 등)
- service: 관련 서비스/시스템명 (언급된 경우)
- delta: 변화량 (증가/감소, 언급된 경우)

## 규칙
- 해당하지 않는 항목은 null로 설정한다.
- 수치와 단위는 원문 표기 그대로 사용한다.
- 여러 지표가 포함된 경우 배열로 반환한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "metric": "레이턴시",
      "value": "50",
      "unit": "ms",
      "service": "검색 API",
      "delta": "감소"
    }}
  ]
}}
```

## 텍스트
{user_text}""",
    "decision": """다음 텍스트에서 회의/합의 결정 사항을 추출하세요.

## 추출 항목
- meeting: 회의명 또는 맥락 (언급된 경우)
- decision: 결정 내용
- agreed_by: 합의 참여자 (언급된 경우)
- deadline: 실행 기한 (언급된 경우, ISO 형식)

## 규칙
- 해당하지 않는 항목은 null로 설정한다.
- 결정 내용은 원문의 핵심을 간결하게 정리한다.
- 여러 결정이 포함된 경우 배열로 반환한다.

## 출력 형식
JSON만 반환하세요.

```json
{{
  "items": [
    {{
      "meeting": "주간 회의",
      "decision": "BGE-M3 도입 확정",
      "agreed_by": null,
      "deadline": null
    }}
  ]
}}
```

## 텍스트
{user_text}""",
}


_CDC_GENERIC_EXTRACTION_TEMPLATE = """다음 텍스트에서 '{cdc_type}' 유형의 정보를 추출하세요.

## 규칙
- 텍스트에서 구조화 가능한 핵심 정보를 JSON으로 추출한다.
- 항목명은 snake_case 영문으로, 값은 원문 언어(한국어) 그대로 사용한다.
- 해당하지 않는 항목은 null로 설정한다.
- JSON만 반환하세요.

## 텍스트
{user_text}"""


def build_cdc_extraction_prompt(cdc_type: str, user_text: str) -> str:
    """CDC 데이터 추출 프롬프트를 빌드한다.

    알려진 유형이면 전용 템플릿을 사용하고,
    미지의 유형이면 generic 템플릿으로 LLM이 스키마를 자동 생성한다.

    Args:
        cdc_type: CDC 유형 (어떤 문자열이든 허용).
        user_text: 사용자 발화 원문.

    Returns:
        LLM에 전달할 프롬프트 문자열.
    """
    template = _CDC_EXTRACTION_TEMPLATES.get(cdc_type)
    if template is not None:
        return template.format(user_text=user_text)

    # 미지의 유형 → generic 추출
    logger.info("cdc_generic_extraction", cdc_type=cdc_type)
    return _CDC_GENERIC_EXTRACTION_TEMPLATE.format(
        cdc_type=cdc_type, user_text=user_text,
    )


# ============================================================
# 4. 포맷팅 헬퍼 함수
# ============================================================


def format_search_results_for_chat(results: list[dict]) -> str:
    """검색 결과를 대화 응답에 포함할 포맷으로 변환한다.

    각 결과를 인용 번호와 함께 요약하여 LLM이 참조할 수 있는 형태로 정리한다.

    Args:
        results: 검색 결과 목록. 각 dict는 아래 키를 포함한다:
            - doc_title (str): 문서 제목.
            - section (str, optional): 섹션 제목.
            - content (str): 검색된 내용.
            - score (float, optional): 유사도 점수.

    Returns:
        포맷된 검색 결과 문자열.
    """
    if not results:
        return "(검색 결과 없음)"

    lines: list[str] = []
    for idx, result in enumerate(results, start=1):
        doc_title = result.get("doc_title", "문서")
        section = result.get("section", "")
        content = result.get("content", "")
        score = result.get("score")

        header = f"[{idx}] {doc_title}"
        if section:
            header = f"{header} > {section}"
        if score is not None:
            header = f"{header} (score: {score:.2f})"

        lines.append(f"{header}\n{content}")

    return "\n\n---\n\n".join(lines)


# --- CDC 확인 메시지 포맷터 타입 ---

_CdcFormatter = Callable[[dict], str]


def format_cdc_confirmation(cdc_type: str, extracted_data: dict) -> str:
    """CDC 추출 결과를 확인 메시지로 포맷팅한다.

    LLM이 아닌 코드 레벨에서 사용하는 확인 메시지 템플릿이다.

    Args:
        cdc_type: CDC 유형 ("expense", "body_metric", "exercise").
        extracted_data: 추출된 데이터 dict.

    Returns:
        사용자에게 보여줄 확인 메시지 문자열.
    """
    formatters: dict[str, _CdcFormatter] = {
        "expense": _format_expense_confirmation,
        "body_metric": _format_body_metric_confirmation,
        "exercise": _format_exercise_confirmation,
        "project_fact": _format_project_fact_confirmation,
        "task_progress": _format_task_progress_confirmation,
        "sales": _format_sales_confirmation,
        "tech_metric": _format_tech_metric_confirmation,
        "decision": _format_decision_confirmation,
    }

    formatter = formatters.get(cdc_type)
    if formatter is None:
        logger.warning("unknown_cdc_type_for_confirmation", cdc_type=cdc_type)
        return f"감지된 데이터를 기록할까요? (유형: {cdc_type})"

    return formatter(extracted_data)


# --- CDC 확인 메시지 내부 포맷터 ---


def _format_expense_confirmation(data: dict) -> str:
    """지출 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "지출 정보를 기록할까요?"

    lines: list[str] = []
    for item in items:
        amount = item.get("amount", "금액 미상")
        purpose = item.get("purpose", "")
        category = item.get("category", "")
        parts = [f"{amount}"]
        if purpose:
            parts.append(f"({purpose})")
        if category:
            parts.append(f"[{category}]")
        lines.append(" ".join(parts))

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"지출을 기록할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


def _format_body_metric_confirmation(data: dict) -> str:
    """신체 측정 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "측정 기록을 저장할까요?"

    lines: list[str] = []
    for item in items:
        metric_type = item.get("metric_type", "측정")
        value = item.get("value", "")
        measured_at = item.get("measured_at", "")
        parts = [f"{metric_type}: {value}"]
        if measured_at:
            parts.append(f"({measured_at})")
        lines.append(" ".join(parts))

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"건강 기록을 저장할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


def _format_exercise_confirmation(data: dict) -> str:
    """운동 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "운동 기록을 저장할까요?"

    lines: list[str] = []
    for item in items:
        exercise_type = item.get("exercise_type", "운동")
        duration = item.get("duration", "")
        distance = item.get("distance", "")
        calories = item.get("calories", "")
        parts = [exercise_type]
        if duration:
            parts.append(duration)
        if distance:
            parts.append(distance)
        if calories:
            parts.append(f"/ {calories}")
        lines.append(" ".join(parts))

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"운동 기록을 저장할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


# --- 기업 CDC 확인 메시지 포맷터 (설계서 5.2) ---


def _format_project_fact_confirmation(data: dict) -> str:
    """프로젝트 사실 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "프로젝트 정보를 기록할까요?"

    lines: list[str] = []
    for item in items:
        project = item.get("project", "")
        fact = item.get("fact", "")
        value = item.get("value", "")
        parts: list[str] = []
        if project:
            parts.append(project)
        if fact:
            parts.append(fact)
        if value:
            parts.append(f"({value})")
        lines.append(" ".join(parts) if parts else "프로젝트 사실")

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"프로젝트 정보를 기록할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


def _format_task_progress_confirmation(data: dict) -> str:
    """업무 진행 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "업무 진행 상황을 기록할까요?"

    lines: list[str] = []
    for item in items:
        task = item.get("task", "업무")
        progress = item.get("progress", "")
        status = item.get("status", "")
        parts = [task]
        if progress:
            parts.append(f"{progress}")
        if status:
            parts.append(f"[{status}]")
        lines.append(" ".join(parts))

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"업무 진행을 기록할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


def _format_sales_confirmation(data: dict) -> str:
    """영업 실적 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "영업 실적을 기록할까요?"

    lines: list[str] = []
    for item in items:
        client = item.get("client", "")
        sale_type = item.get("type", "")
        amount = item.get("amount", "")
        count = item.get("count", "")
        parts: list[str] = []
        if client:
            parts.append(client)
        if sale_type:
            parts.append(sale_type)
        if amount:
            parts.append(amount)
        if count:
            parts.append(f"({count})")
        lines.append(" ".join(parts) if parts else "영업 실적")

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"영업 실적을 기록할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


def _format_tech_metric_confirmation(data: dict) -> str:
    """기술 메트릭 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "기술 메트릭을 기록할까요?"

    lines: list[str] = []
    for item in items:
        metric = item.get("metric", "메트릭")
        value = item.get("value", "")
        unit = item.get("unit", "")
        service = item.get("service", "")
        parts = [metric]
        if value:
            parts.append(f"{value}{unit}" if unit else str(value))
        if service:
            parts.append(f"({service})")
        lines.append(" ".join(parts))

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"기술 메트릭을 기록할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."


def _format_decision_confirmation(data: dict) -> str:
    """회의 결정 CDC 확인 메시지를 생성한다."""
    items = data.get("items", [data])
    if not items:
        return "결정 사항을 기록할까요?"

    lines: list[str] = []
    for item in items:
        meeting = item.get("meeting", "")
        decision = item.get("decision", "")
        parts: list[str] = []
        if meeting:
            parts.append(f"[{meeting}]")
        if decision:
            parts.append(decision)
        lines.append(" ".join(parts) if parts else "결정 사항")

    summary = "\n".join(f"  - {line}" for line in lines)
    return f"결정 사항을 기록할까요?\n{summary}\n\n비공개로 저장돼요. 수정할 부분이 있으면 말씀해주세요."
