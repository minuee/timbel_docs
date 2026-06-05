# 문서 검색 기능 설계

## 목표

고객 발화가 수신되면 검색 엔진에 의미 기반(dense) 검색을 요청하고, 결과를 지식정보 패널에 표시한다.
기존 intent 기반 CE서비스 검색은 주석 처리하고 새 검색으로 대체한다.

## 아키텍처

```
Redis nlp:complete
  → 프론트 parseMessageData()
  → 무의미 발화 필터링 (프론트 1차)
  → POST /api/asst/v1/search (asst-service)
      → 무의미 발화 필터링 (백엔드 2차)
      → 검색엔진 POST /api/v1/search (mode: dense) 호출
      → 결과 가공 후 응답
  → keywordDetailData에 저장 → 지식정보 패널 표시
```

## 백엔드 (asst-service)

### 새 모듈: search

```
asst-service/src/advisor/search/
├── search.module.ts
├── search.controller.ts
├── search.service.ts
├── dto/
│   ├── search-request.dto.ts
│   └── search-response.dto.ts
└── constants/
    └── search.constants.ts
```

### 엔드포인트

`POST /api/asst/v1/search`

### 요청 (프론트 → asst-service)

```json
{
  "query": "적금 해지 방법이 궁금해요",
  "conversationHistory": [
    { "speaker": "customer", "content": "보험 해약 방법 알려줘" },
    { "speaker": "agent", "content": "해약은 고객센터 또는 앱에서 가능합니다." }
  ],
  "callId": "optional-call-id"
}
```

### 검색엔진 요청 (asst-service → 검색엔진)

```json
{
  "query": "적금 해지 방법이 궁금해요",
  "repository_id": "00000000-0000-0000-0000-000000000001",
  "document_type_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
  "mode": "hybrid",
  "top_k": 5,
  "enable_rerank": true,
  "use_hyde": true,
  "use_fallback": true,
  "enable_llm_rewrite": true,
  "with_answer": true,
  "distill": true,
  "conversation_history": [
    { "speaker": "customer", "content": "보험 해약 방법 알려줘" },
    { "speaker": "agent", "content": "해약은 고객센터 또는 앱에서 가능합니다." }
  ]
}
```

### 환경변수

- `SEARCH_HOST`: 검색엔진 호스트 URL

### 무의미 발화 필터

- 길이: 공백 제거 후 2자 이하
- 목록: 네, 예, 응, 음, 으음, 아니오, 아니요, 아뇨, 감사합니다, 고맙습니다, 알겠습니다, 그렇습니다, 맞습니다, 여보세요, 네네

## 프론트엔드 (asst-web)

### 변경 사항

1. `api/config/path.ts` — SEARCH 경로 추가
2. 검색 요청/응답 타입 정의
3. `api/apis/` — asst-service 검색 API 클래스 추가
4. `chat/index.vue` — handleAutoSelectKeywordV2 주석 처리, handleDocumentSearch 추가

### conversationHistory 추출

chatContent 배열에서 현재 메시지 직전의:
- sender === "consultant" 가장 마지막 1개 → { speaker: "agent", content }
- sender === "user" 가장 마지막 1개 → { speaker: "customer", content }
시간순 정렬하여 전달

### 결과 표시

기존 keywordDetailData 구조를 재활용하여 지식정보 패널에 표시
