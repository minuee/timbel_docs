# 어드바이저 LLM 기능 명세 (통화 요약 / 자동 To-Do)

전화 상담 1건의 대화 전체를 LLM이 분석하는 두 기능. 별도 API 요청용 정리.

## 공통 입력
`callstats_id` 로 통화의 발화(turn)를 DB에서 꺼내 아래 텍스트로 조립해 LLM에 입력한다.
```
상담사: 안녕하세요 무엇을 도와드릴까요
고객: 환불이 안 됐어요
...
```

> 프롬프트 위치: 요약·키워드·자동todo 프롬프트는 **LLM Orchestrator에 이름으로 등록**돼 있고(코드엔 이름만), 상담유형 프롬프트만 **코드에 내장**. 전문이 필요하면 Orchestrator에서 조회.

---

## ① 통화 요약 — `POST /api/asst/v1/summary`

LLM을 4갈래로 병렬 호출해 한 번에 묶어서 반환.

### 입력
| 필드 | 타입 | 설명 |
|------|------|------|
| `callstats_id` | string | 요약할 통화 ID |
| `keyword_count` | number(1~5) | 뽑을 키워드 개수 |

### 처리 (4갈래)
| 항목 | 프롬프트 | 넘기는 변수 | 결과 |
|------|----------|-------------|------|
| 요약문 | `adv-conversations-summarize` (Orchestrator) | conversation | 4항목: 고객문의/처리결과/후속조치/특이사항 → 마크다운 조립 |
| 키워드 | `adv-conversations-summarize-keyword` (Orchestrator) | conversation, count | 키워드 문자열 배열 |
| 상담유형 | 코드 내장 (gpt-4o-mini) | conversation | 사전정의 유형목록에서 최대 3개 `{id, categoryPath}` |
| 감정·위험 | **CE 서비스 API** (`CE_API_LLM_URL`) | conversation | 3축: emotion / complaintRisk / churnRisk |

- **요약문 마크다운 형태:**
  ```
  ## 상담 요약
  **1. 고객 문의**
  - ...
  **2. 처리 결과**
  - ...
  **3. 후속 조치**
  - ...
  **4. 특이 사항**
  - ...
  ```
- **상담유형 프롬프트 요지:** "콜센터 상담을 분석해 가장 적합한 상담유형 최대 3개 분류. '대분류 > 중분류 > 소분류' 3계층(금융/결제/계정/증권/보험/통신/유통/서비스). 정확히 일치 없어도 가장 유사한 것 선택, 빈 배열 금지. JSON으로만 응답." (전체 유형목록은 코드 `summary.service.ts` 참고)
- **감정 type 값:** angry / dissatisfied / normal / satisfied / thanks. score는 0~1.

### 리턴
```jsonc
{
  "summary": "## 상담 요약\n**1. 고객 문의**\n- ...",   // 마크다운 문자열
  "keywords": ["중복결제", "환불", "..."],
  "counselingTypes": [
    { "id": "1", "categoryPath": "결제 > 온라인결제 > 환불요청" }
  ],
  "emotion":       { "type": "angry", "score": 0.87, "summary": "환불 지연으로 화남" },
  "complaintRisk": { "score": 0.4, "summary": "책임자 연결 요구" },   // 민원위험
  "churnRisk":     { "score": 0.2, "summary": "해지 언급" }           // 이탈징후
}
```

---

## ② 자동 To-Do — `POST /api/asst/v1/todos/auto-create`

통화 내용에서 상담사가 처리할 할일을 LLM이 뽑아 `todos` 테이블에 저장.

### 입력
| 필드 | 타입 | 설명 |
|------|------|------|
| `callstats_id` | string | 분석할 통화 ID |
| `maxLength` | number | 할일 1개 최대 길이 |
| `includeSimple` | boolean | 간단한 할일 포함 여부 |
| `user_key` | string | 할일을 받을 상담사 키 |

### 처리
- **프롬프트:** `adv-auto-create-todos` (Orchestrator)
- **넘기는 변수:** callStat(대화 전체), maxLength, includeSimple
- **LLM 출력:** `{ "todos": ["고객에게 환불 결과 안내", "결제 오류 티켓 등록"] }`
- 각 할일을 1건씩 저장(state=0 진행중)

### 리턴 (저장된 할일 배열)
```jsonc
[
  {
    "id": "todo_3f9a...",
    "user_key": "user_123",
    "callstats_id": "callstats_123",
    "title": "고객에게 환불 처리 결과 안내",
    "state": 0,                       // 0=진행중
    "created_at": "2026-06-24T01:00:00.000Z",
    "updated_at": "2026-06-24T01:00:00.000Z"
  }
]
```

---

## 요약 표
| 기능 | 엔드포인트 | 프롬프트 | 핵심 리턴 |
|------|-----------|----------|----------|
| 통화 요약 | `POST /summary` | `adv-conversations-summarize` 외 3 | summary, keywords, counselingTypes, emotion, complaintRisk, churnRisk |
| 자동 To-Do | `POST /todos/auto-create` | `adv-auto-create-todos` | 저장된 todo 객체 배열 |
