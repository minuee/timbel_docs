# assist-stream 렌더링 속도 개선 — 분석 및 작업 정리

> 작성일: 2026-06-21
> 목적: 상담화면의 두 스트리밍 API(자동/수동) 중 **자동(assist-stream)이 API 응답 이후 화면에 그려지는 속도가 느린 문제**의 원인 분석과 개선 방안 정리. 내일(회사 최신 소스) 테스트용 체크리스트 포함.

---

## 0. 용어

- **자동 = `assist-stream`**: 고객 발화 STT `final` 시 자동 호출. AI 요약 + 문서 노출.
- **수동 = `stream`**: 상담사가 검색창에서 직접 호출하는 수동 문서검색.

---

## 1. 두 API 개요

| 구분 | 자동 (assist-stream) | 수동 (stream) |
|---|---|---|
| 엔드포인트 | `POST /aicc/asst-service/api/asst/v1/assist-stream` | `POST /aicc/asst-service/api/asst/v1/stream` |
| API 함수 | `callAssistStream` (`src/api/apis/assist-stream.api.ts`) | `callDocumentStream` (`src/api/apis/document-search.api.ts`) |
| 호출 핸들러 | `useChatAssist.ts` → `handleAssistStream` | `useKnowledgeSearch.ts` → `handleSearch` |
| 트리거 | STT `final` (Socket `nlp:complete`, 고객 발화) **자동** | 검색창 입력 **수동** |
| 요청 body | `{ query, conversationHistory(직전 2턴), callId }` | `{ query }` |
| 전송 방식 | SSE (`fetch` + `ReadableStream`, `sse-parser.ts`) | 동일 |
| SSE 이벤트 | `intent`→`sources`→`distilled`→`token`(N)→`done`/`error` | `sources`→`distilled`→`token`(N)→`done`/`error` (intent 미사용) |

> 백엔드 확인 결과: 두 API 모두 **API 서버가 받은 body를 RAG 서버로 그대로 전달**하고 그 결과를 SSE로 프론트에 중계. 즉 body 차이는 RAG 입력 차이로만 이어짐.

---

## 2. 핵심 결론 (오늘 합의된 내용)

문제는 **두 갈래**로 나뉜다. 둘은 경쟁이 아니라 보완 관계.

1. **백엔드 지연 축** — 요청 body의 `conversationHistory`가 RAG 입력 토큰을 늘려 `intent`/`distill`/`generate` 단계 시간을 늘릴 가능성. (`callId`는 단순 식별자라 영향 미미.)
2. **프론트 렌더링 축 (주범 후보)** — *"API 응답 이후 화면 그리기"* 가 느린 것은 body와 무관. 자동 경로가 **수신 데이터를 화면에 반영하는 방식**이 수동과 근본적으로 다르기 때문.

---

## 3. 프론트 렌더링이 느린 이유 (코드 기준)

### 3-1. 토큰을 "공유 문서 객체"에 직접 써넣는다 (가장 큰 비용)

- **수동** (`useKnowledgeSearch.ts:121-127`): 토큰을 **문서와 분리된 별도 문자열**(`searchSession.streamingAnswer`)에 저장 → 토큰마다 텍스트 노드 1곳만 갱신.
- **자동** (`useChatAssist.ts:422-435`): 토큰마다
  - `chatDataStore.appendAssistStreamToken()` → store 반응성 → `knowledge/index.vue:534` watch에서 **regex 재실행**
  - `item.data.search_summary = displayText` → **지식저장소 카드/상세/채팅 버블에 공유된 같은 객체를 deep-mutate** → 구독 컴포넌트 연쇄 리렌더
  - 누적 문자열 전체에 **regex 2회/토큰** (요약 길어지면 O(n²))

→ 토큰당 reactive write가 **두 군데(store + item.data)**, regex가 **두 번(핸들러 + store watch)**. 토큰이 초당 15~20개면 그만큼 리렌더·regex 폭주.

### 3-2. distilled 시점에 문서 상세를 자동으로 미리 연다 (자동만)

- `useChatAssist.ts:398-420`: `emit("detailItemClick", ...)`로 첫 문서 상세를 **자동 오픈** → 이후 모든 토큰의 mutation이 *열린 상세 패널*까지 리렌더.
- 부수효과: `selectedKeywordForBubble[id]` 변경 → 채팅 버블 `v-memo` 무효화 → 버블 리렌더 + 내부 computed 재계산.
- 수동은 사용자가 클릭해야 열림 → 토큰 구간에 상세 패널 리렌더 없음.

### 3-3. 크로스 컴포넌트 emit 홉 (자동만)

자동: `useChatAssist → chat/index.vue(emit) → agent/index.vue(부모) → knowledge 패널`. 컴포넌트 경계 2~3홉.
수동: 같은 composable 안에서 로컬 ref 직접 갱신 → 홉 0.

### 비교 요약

| | 수동(stream) | 자동(assist-stream) |
|---|---|---|
| 토큰 저장 위치 | 문서와 분리된 별도 문자열 | **문서 객체 내부 deep-mutate** |
| 토큰당 reactive write | 1곳 | **2곳(store + item.data)** |
| 토큰당 regex | 1회 | **2회** |
| 문서 상세 패널 | 클릭 시 오픈 | **자동 오픈 후 토큰마다 갱신** |
| 데이터 전달 | 로컬 ref 직접 | **emit 2~3홉** |

---

## 4. 측정 지점 (백엔드 로그 없이 프론트만으로 가능)

각 SSE 이벤트에 타이밍이 들어온다. **추측 대신 숫자로** 판단할 것.

| 이벤트 | 필드 | 의미 |
|---|---|---|
| `intent` | `latency_ms` | 의도 분류(자동 전용) |
| `sources` | `search_latency_ms` | 문서 검색 |
| `distilled` | `latency_ms` | 참고문서 선별 + 1차 요약 |
| `done` | `stages: {intent, search, distill, generate}` | **단계별 분해** |
| `done` | `token_usage: {context_tokens, prompt_tokens, completion_tokens, total_tokens}` | 입력 토큰량 |

(타입: `src/api/types/assist-stream.type.ts`)

---

## 5. 개선 방안

### A안 — throttle (1차, 최소 위험 / 권장 시작점)

**아이디어:** 데이터 도착 속도(토큰)와 화면 갱신 속도(렌더)를 분리. 토큰은 plain 버퍼에 즉시 누적, reactive write·regex는 프레임/인터벌당 1회로 묶음.

```
토큰 도착   → rawAnswer += text         (즉시, non-reactive, 유실 없음)
            → flush 예약 플래그 set
프레임 도래 → displayText = regex(rawAnswer)  (1회)
            → store / item.data 에 1회 write    (1회 렌더)
```

설계 결정 사항:
- **방식:** `rAF + 최소 100ms 가드` 조합 권장 (부드러움 + 절감 + 백그라운드 탭 자동정지). 더 단순하게는 `setTimeout(100ms)`.
- **leading:** 첫 토큰은 즉시 1회 렌더 후 throttle 시작 (체감 반응성).
- **양쪽 다 묶기:** store append(①)와 `item.data` mutation(②)을 **둘 다** throttle해야 효과. 한쪽만 묶으면 반쪽짜리.

정합성 필수 포인트 (반복 호출 환경이라 특히 중요):
1. **done에서 flush** — 펜딩 타이머 취소 + 최종 raw로 1회 강제 flush (요약 끝 잘림 방지).
2. **abort/error에서 타이머 취소** — 죽은 스트림의 늦은 flush 방지.
3. **스트림별 독립 상태** — throttle 타이머/raw 버퍼를 `handleAssistStream` **클로저 안**에 둘 것. 전역 공유 금지(5~10초마다 새 스트림 떠도 서로 간섭 0).
4. **active-id 가드 유지** — flush 시점에도 `assistStreamActiveMessageId === messageId` 가드 유지 → 새 버블 전환 시 옛 스트림 flush 자동 무시.

한계: 렌더 **빈도**를 줄이는 것이지 렌더 **1회 비용**을 줄이는 건 아님.

### B안(=6번) — 렌더 1회 비용까지 줄이기 (2차, 곱셈 효과)

- 스트리밍 중엔 `item.data.search_summary`를 **아예 안 건드림**. 라이브 표시는 이미 있는 `assistStreamText → aiSearchResultText`(`knowledge/index.vue:534`) 한 경로로만.
- 문서 객체엔 **`done`에서 최종본 1회만** 기록(영속/스크롤백용).
- **전제(반드시 사전 확인):** 상세 패널이 스트리밍 중 `item.data.search_summary`를 직접 바인딩하는지. 그렇다면 그 바인딩을 active-bubble의 store 값으로 돌려야 함. (`knowledge/index.vue` vs `TabTypeKnowledgeIndex.vue` 중 어느 쪽이 라이브 요약을 그리는지 확인 필요.)

---

## 6. 반복 호출(5~10초) 환경 주의사항

자동은 고객 발화 final마다 **버블별로** 새 스트림이 뜬다. 수정 시 반드시:
- **영속 데이터는 항상 `messageId` 키 기준.** 단일 전역 필드(`assistStreamText`)는 "현재 스트리밍 중 버블의 라이브 표시" 용도로만. (현재 지난 버블 요약 보존은 `item.data.search_summary` + `summaryByKey[messageId]`가 담당.)
- **겹치는 스트림:** AbortController는 *같은 messageId*만 취소 → 백엔드가 느리면 이전/새 스트림 동시 진행 가능. 이전 스트림의 늦은 `done`이 새 버블 화면/선택을 덮어쓰지 않도록 active-id 가드 유지.

---

## 7. 내일 회사에서 할 일 (체크리스트)

### Step 0. 계측 먼저 (10분)
- [ ] `useChatAssist.ts` `done` 핸들러에 `console.log("[assist-stream]", e.stages, e.token_usage)` 추가.
- [ ] `useKnowledgeSearch.ts` `done` 핸들러에 동일 로그 추가.
- [ ] DevTools **Performance 녹화** + Vue DevTools **"Highlight updates"** 준비.

### Step 1. 축 가르기 — body 테스트 (백엔드 지연 여부)
- [ ] 자동 요청 body를 임시로 `{ query }`만 보내도록 수정(`useChatAssist.ts:247`의 `callAssistStream(...)` 인자).
- [ ] 동일/유사 질의로 전/후 비교:
  - `done.token_usage.context_tokens` 가 줄어드는가?
  - `done.stages` 의 어느 단계가 빨라지는가?
  - **렌더링 체감이 빨라지는가?**
- [ ] 판정:
  - 렌더링도 빨라짐 → 백엔드 지연(history)이 1차 원인 → history 최적화 검토.
  - **렌더링 여전히 느림 → 프론트 렌더링이 주범 확정 → Step 2로.**
- [ ] `done.stages.intent` 값 확인 (자동 전용 단계가 추가 지연인지). 크면 백엔드에 intent skip 가능 여부 문의.
- ⚠️ body 테스트는 **품질 영향 가능**(대명사 발화 맥락 손실 등). 최종 설정 아님, 진단용.

### Step 2. 프론트 렌더링 확인 & A안 적용
- [ ] Performance/Highlight updates로 토큰 구간에 카드/상세/버블이 토큰마다 리렌더되는지 확인.
- [ ] A안(throttle) 적용:
  - [ ] token 핸들러: raw 즉시 누적 + flush 예약 구조로 변경.
  - [ ] store append(①) + `item.data` mutation(②) 둘 다 throttle.
  - [ ] regex를 flush 시점 1회로 이동.
  - [ ] `done`/`error`/abort flush·취소 처리.
  - [ ] throttle 상태를 `handleAssistStream` 클로저에 보관(스트림별 독립).
- [ ] 적용 후 재측정 — 토큰 구간 리렌더 빈도 감소 확인.
- [ ] 회귀 확인: **연속 발화로 버블 여러 개 생성** 시 ① 지난 버블 요약 유지 ② 최종 요약 끝 안 잘림 ③ 패널/버블 안 튐.

### Step 3. (선택) B안 검토
- [ ] 상세 패널이 라이브 요약을 `item.data` vs `store(aiSearchResultText)` 중 어디서 읽는지 확인.
- [ ] store 단일 경로로 라이브 표시 가능하면, `item.data` 기록을 `done` 1회로 축소.

---

## 8. 참조 파일

| 용도 | 경로 | 라인 |
|---|---|---|
| SSE 파서 | `src/api/apis/sse-parser.ts` | 전체 |
| 자동 API | `src/api/apis/assist-stream.api.ts` | `callAssistStream` |
| 수동 API | `src/api/apis/document-search.api.ts` | `callDocumentStream` |
| 응답 타입 | `src/api/types/assist-stream.type.ts` | `DoneEvent` 51-67 |
| 자동 핸들러 | `src/view/advisor/components/chat/composables/useChatAssist.ts` | token 422-435 / distilled 334-421 / done 436-517 |
| 수동 핸들러 | `src/view/advisor/components/knowledge/composables/useKnowledgeSearch.ts` | token 121-127 |
| STT final 트리거 | `src/view/advisor/components/chat/composables/useChatMessageParser.ts` | 463-470 |
| store | `src/stores/modules/chatData.ts` | 102-127 |
| 라이브 요약 watch | `src/view/advisor/components/knowledge/index.vue` | 533-538 |
| 부모 emit 리스너 | `src/view/advisor/agent/index.vue` | 45-47, 730-743 |
