# 상담사 화면 지식/문서 검색(RAG) 프로세스 분석

> 작성일: 2026-06-11 / 대상 브랜치: develop_nohsn
> 범위: 상담사(advisor) 화면의 지식·문서 검색 RAG 파이프라인 (프론트엔드 기준)

---

## 0. 한 줄 요약

프론트엔드에는 **LLM(OpenAI/Anthropic 등) 직접 호출이 전혀 없음**. 프론트는 `query`만 백엔드(`asst-service`)에 전달하고, 백엔드가 RAG 파이프라인을 수행해 **SSE 이벤트로 단계별 결과를 스트리밍**한다. 통화요약/감정 기능과 동일한 "백엔드 프록시" 패턴.

- grep 결과: `src` 전체에 `openai|anthropic|@anthropic|claude-|langchain|gemini|genai|mistral|cohere|ollama` 직접 호출 **0건**.

---

## 1. RAG 진입 경로 (2개 — 둘 다 같은 SSE 이벤트 규약 공유)

| 경로 | 트리거 | API 함수 / 파일 | 엔드포인트 |
|---|---|---|---|
| **① 자동 어시스턴트 (메인)** | 고객 발화 STT 완료 시 자동 | `callAssistStream` / `src/api/apis/assist-stream.api.ts` | `POST /aicc/asst-service/assist-stream` |
| **② 수동 검색** | 상담사가 지식저장소 검색바 입력 | `callDocumentStream` / `src/api/apis/document-search.api.ts` | `POST /aicc/asst-service/stream` |

- 두 경로 모두 `parseSseStream`(`src/api/apis/sse-parser.ts`)으로 `event:`/`data:` 프레임을 파싱.
- 파서는 `event === "done" || "error"` 수신 시 즉시 종료. 프레임 구분자는 `\n\n`.
- 엔드포인트 상수: `path.ADVISOR.API.ASSIST_STREAM = "/assist-stream"`, `path.ADVISOR.API.SEARCH = "/stream"` (`src/api/config/path.ts:55-56`).
- Base URL: `LANGSA_GATEWAY_URL` + prefix `/aicc/asst-service`. 인증: `Authorization: Bearer` + `x-auth-token` 헤더.

### 부가 경로
- `useKeywordDetail.ts`(상담이력 모달)도 `callDocumentStream` 사용 → 이력 화면에서 키워드 클릭 시 동일 검색 재현.

---

## 2. ① 자동 흐름 (메인) — 트리거 조건이 핵심

```
STT 소켓 → useChatSocket → useChatMessageParser (메시지 파싱)
  └ 고객 발화(isUser)이고 ending=final 일 때만  (useChatMessageParser.ts:479)
     → handleAssistStream(displayText, messageId, turnIdx, customerQuery)
        → callAssistStream → POST /assist-stream (SSE)
```

### 트리거 규칙 (중복/오호출 방지 설계)
- **고객 발화(`isUser`)에만, `final` 턴에만** 검색 실행 (`useChatMessageParser.ts:478-483`).
- 미완(partial) 발화는 보류 → chain이 final로 마무리될 때 **합쳐진 전체 텍스트로 한 번만** 검색.
- 동일 `messageId`의 이전 스트림은 `AbortController.abort()`로 취소 후 새로 시작 (`useChatAssist.ts:217-220`).
- 컴포넌트 unmount 시 모든 AbortController 정리.

### 요청 바디 (`AssistStreamReq`)
```ts
{
  query,                       // 고객 발화 텍스트
  conversationHistory,         // 직전 2턴만 (아래 3절 참고)
  callId,                      // currentCallId
  turnIdx,                     // STT 턴 인덱스 (VOC 결과 1:1 매핑 키, null 허용)
  company                      // get_user의 company (실시간 VOC LLM의 X-Tenant-Id용, 없어도 OK)
}
```

---

## 3. 백엔드 RAG 파이프라인 단계 = SSE 이벤트로 그대로 노출

이벤트 타입 정의: `src/api/types/assist-stream.type.ts`. 프론트가 받는 이벤트 순서가 곧 백엔드 RAG 단계다.

| 순서 | event | 내용 | 프론트 처리 |
|---|---|---|---|
| 1 | **`intent`** | `{ search, reason, latency_ms, skipped }` 검색 필요 여부 판단 | `skipped=true`(일상 대화)면 **이후 전부 무시·종료**. `reason`은 칩 힌트로 버퍼링 |
| 2 | **`sources`** | `{ sources[], confidence, search_latency_ms, total_candidates }` 검색된 문서 후보 | 코드상 **5개 즉시 표시**(버퍼링), 지식저장소 패널 리스트로 emit |
| 3 | **`distilled`** | `{ selected_refs[], summary, rationale, latency_ms }` LLM 선별 참고문서 | `selected_refs` 비면 **칩 없이 종료**. 아니면 선별 문서로 칩 생성 |
| 4 | **`token`** | `{ text }` LLM 답변 토큰 | 누적해서 실시간 타이핑 효과, `search_summary` 갱신 |
| 5 | **`done`** | `{ model_used, confidence, token_usage, latency_ms, stages }` | 로딩 해제, fallback 처리, snapshot 저장 |
| - | **`error`** | `{ stage: search\|generate\|unknown, code, message }` | 로딩 해제, 결과 없으면 에러 표시 |

- `stages`에 단계별 latency(`intent/search/distill/generate`)가 들어옴 → 백엔드 파이프라인이 4단계임을 시사.
- `done.token_usage`에 `context/prompt/completion/total_tokens` 포함 → 비용/토큰 추적 가능.

---

## 4. 프론트의 결과 가공 로직 (검토 포인트 집중 구역)

위치: `src/view/advisor/components/chat/composables/useChatAssist.ts` (`handleAssistStream`)

- **sources 5개 즉시 표시 → distilled로 필터링**: 일단 5개 다 받아 `pendingAllItems`에 버퍼링, `distilled.selected_refs` 도착 후 선별 문서만 칩 생성 → **깜빡임 방지** (`useChatAssist.ts:291-368`).
- **참고문서 3개 채우기 규칙** (`useChatAssist.ts:362-368`): LLM 참고문서가 3개 미만이면 **비참고 문서로 위에서부터 `MAX_DOCS=3`까지 채움**.
  - ⚠️ 제품 의도 확인 필요: "LLM이 참고하지 않은 문서"를 노출하는 게 맞는지.
- **인용표기 `[1,2]` 제거 정규식**: `token`/`summary`에서 `\s*\[\s*\d+(?:\s*,\s*\d+)*\s*\]` 패턴을 화면용으로 스트립. **두 경로(`useChatAssist`, `useKnowledgeSearch`)에 동일 정규식 중복**.
- **distilled 누락 fallback** (`done` 핸들러, `useChatAssist.ts:460-515`): distilled 없이 sources만 온 경우 done 시점에 지식저장소 탭 자동 생성.
- **첫 문서 자동 선택**: distilled 확인 즉시 `detailItemClick` emit → 상담사 수동 클릭 없이 지식저장소에 첫 문서 자동 표시.
- **snapshot 저장** (`useChatAssist.ts:518-525`): `done`에서 `callId && turnIdx!=null`이면 `AssistSnapshotAPI.saveAssistSnapshot`을 **fire-and-forget(실패 무시)** 로 히스토리 저장.

---

## 5. ② 수동 검색 흐름

위치: `src/view/advisor/components/knowledge/composables/useKnowledgeSearch.ts` (`handleSearch`)

- 검색바 입력 → `workspaceId` 할당 체크(없으면 에러 토스트) → `callDocumentStream({ query }, handlers, signal)`.
- 세션 단위(`SearchSession`)로 결과 관리, 탭별 `AbortController` 보유.
- 동일 SSE 이벤트(`sources`/`distilled`/`token`/`done`/`error`) 처리. distilled의 `selected_refs`는 `highlightedRefs`로 하이라이트.
- 요청 타입은 `DocumentSearchReq`(`ce.type.ts`): `{ query, conversationHistory?, callId?, mode?: "hybrid"|"keyword", topK? }`.
  - 단, 현재 호출은 `{ query }`만 전달 → `mode`/`topK`는 미사용(백엔드 기본값 의존).

---

## 6. 관련 파일 인덱스

### API
- `src/api/apis/assist-stream.api.ts` — `callAssistStream` (자동, SSE)
- `src/api/apis/document-search.api.ts` — `callDocumentStream` (수동, SSE)
- `src/api/apis/sse-parser.ts` — `parseSseStream` (SSE 프레임 파서)
- `src/api/apis/assist-snapshot.api.ts` — `saveAssistSnapshot` (결과 히스토리 저장)
- `src/api/apis/knowledge.api.ts` — `KnowledgeAPI`: retrieveDoc / getDoc / getSection / getDocIndex / getDocumentOriginal (문서 상세·원본 조회, 비스트림 REST)
- `src/api/apis/advisor-search.api.ts` — `searchDocuments` (자동완성 제안)

### 타입
- `src/api/types/assist-stream.type.ts` — `AssistStreamReq`, `IntentEvent`, `SourcesEvent`, `DistilledEvent`, `TokenEvent`, `DoneEvent`, `AssistStreamErrorEvent`, `AssistStreamHandlers`
- `src/api/types/ce.type.ts` — `DocumentSearchReq`, `DocumentSearchResultItem`, `AdvisorSearchReq`
- `src/api/types/knowledge.type.ts` — `SearchKnowledgeReq`

### 트리거/가공 (composables)
- `src/view/advisor/components/chat/composables/useChatMessageParser.ts` — STT 파싱 + RAG 트리거 지점(:482)
- `src/view/advisor/components/chat/composables/useChatAssist.ts` — `handleAssistStream` (자동 RAG 핵심)
- `src/view/advisor/components/chat/composables/useChatSocket.ts` — STT 소켓 수신
- `src/view/advisor/components/knowledge/composables/useKnowledgeSearch.ts` — 수동 검색
- `src/view/advisor/components/knowledge/composables/useKnowledgeAutocomplete.ts` — 자동완성
- `src/view/advisor/components/ChatHistoryModal/useKeywordDetail.ts` — 이력 화면 검색 재현

### UI (지식저장소 패널)
- `src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue` — **실제 메인 패널** (탭 기반)
- `DocumentContentPanel.vue`, `DocumentDetailView.vue`, `ContentCollapse.vue`(토글 트리), `DocumentList.vue`, `DocumentCard.vue`, `DocumentDetailModal.vue`, `DocOriginalViewerModal.vue`(원본뷰어)
- ⚠️ `src/view/advisor/components/knowledge/index.vue` 는 **미사용 레거시**(import 0건). 혼동 주의 — 실사용은 `TabTypeKnowledgeIndex.vue`. (상세는 11절)

---

## 7. 검토하며 발견한 리스크 / 확인거리

1. **검색 파라미터 비대칭**: 자동(`AssistStreamReq`)엔 `top_k`/`mode`/`repositoryId`가 없고, 수동(`DocumentSearchReq`)엔 `mode`/`topK`가 정의돼 있으나 호출 시 미전달. → 두 경로 검색 파라미터가 **전적으로 백엔드 기본값에 의존**.
2. **멀티턴 맥락이 얕음**: `extractRecentConversation`이 **직전 2턴만** 전달(`useChatAssist.ts:209`). 긴 상담 맥락 반영 한계.
3. **검색 범위 격리(멀티테넌트)가 백엔드 100% 의존**: 자동 경로는 `repositoryId`/`workspaceId`를 안 보냄. 어느 지식저장소를 뒤질지 백엔드가 `callId`/`company(X-Tenant-Id)`로 추론하는 구조. 보안/격리 관점 검증 필요.
4. **프론트 가공 로직 중복**: sources→distilled 가공, 인용 제거 정규식, 첫 문서 자동선택 emit이 `useChatAssist`/`useKnowledgeSearch`에 유사하게 흩어짐 → 공용 헬퍼 추출 여지.
5. **"참고 안 한 문서 3개 채우기"** 규칙의 제품 의도 확인 필요(4절).

---

## 8. 다음 검토 후보 방향

- **A. 검색 품질/파라미터** — top_k·mode·멀티턴 맥락 등 요청 파라미터 조정
- **B. 검색 범위 격리** — workspace/repository 미전달이 의도된 건지 (보안/멀티테넌트)
- **C. 프론트 가공 로직** — 3개 채우기 규칙, 중복 정규식 리팩터링
- **D. 현 상태 문서화** — 본 문서 유지·보강

---

## 9. 전화내용(STT) + 문서안내(RAG)가 한 챗봇 화면에 공존하는 구조

### 한 장 요약
```
chatContent 배열 (= 채팅 버블 목록, chat/index.vue:273 v-for로 렌더링)
│
├─ 버블[id=101] 고객발화 "연말정산 어떻게 해요?"   ← STT 소켓이 push
│   └─ (이 버블 바로 아래 인라인) 지식정보 카드 3개 + AI요약  ← RAG가 같은 id=101로 붙임
│
├─ 버블[id=102] 상담사 발화 "네 안내드릴게요"        ← STT push (RAG 트리거 안 됨)
│
└─ 버블[id=103] 고객발화 "혼인공제도 되나요?"
    └─ (아래 인라인) 지식정보 카드 + 요약              ← RAG가 id=103으로 붙임
```

### 두 채널이 같은 화면으로 합류
- **왼쪽(전화내용) — STT 소켓**: `useChatSocket` → `useChatMessageParser`가 발화를 파싱해 `chatContent` 배열에 **버블로 push/append**. `chat/index.vue:273`의 `v-for="item in visibleChatContent"`가 `SpeechBubble`로 렌더링.
- **오른쪽(문서안내) — RAG SSE**: 같은 parser가 고객 발화 final 시점에 **그 버블 id를 `messageId`로 넘겨**(`useChatMessageParser.ts:482`) `handleAssistStream` 호출. 결과 도착 시 `useChatAssist`가:
  - `keywordDetailData[messageId] = [{ type: "지식정보", content: 문서들 }]`
  - `selectedKeywordForBubble[messageId]` 세팅 (= "이 버블 펼쳐라" 신호)
  - 버블의 `highlightKeywords`에 힌트 키워드 칩 세팅

### 연결의 핵심 — `chat/index.vue:313`
```vue
<SpeechBubble ... />                              <!-- ① STT 발화 버블 -->
<div v-if="selectedKeywordForBubble[item.id]">   <!-- ② 같은 id면 그 아래 지식 박스 -->
   <!-- keywordDetailData[id]의 "지식정보" 문서 카드 + AI요약 렌더링 -->
</div>
```
→ 발화 버블과 RAG 결과는 별개 컴포넌트가 아니라 **같은 `item.id`로 묶여 한 버블 단위 안에 세로로 쌓인다**.

### 이중 출력 — 채팅 인라인 + 우측 지식저장소 패널 동시 표시
`useChatAssist`가 부모로 emit하는 4종:
- `updateChatDocumentList` → 지식저장소 패널 문서 리스트
- `updateChatSelectedRefs` → 참고문서 하이라이트
- `updateChatSummary` → AI 요약 텍스트
- `detailItemClick` → 수동 클릭 없이 첫 문서 자동 펼침

→ **하나의 RAG 응답이 ⓐ채팅 버블 아래 인라인 + ⓑ우측 지식저장소 패널 두 곳에 동시 표시**.

### 스트림 상태 보관 (chatData store)
- `chatData` store: `assistStreamActiveMessageId` / `assistStreamText` / `assistStreamSummary`.
- **현재 스트리밍 중인 버블 1개**의 토큰만 누적. `messageId` 불일치 시 무시(`chatData.ts:111`)해서 새 발화로 스트림이 옮겨가면 이전 버블에 안 섞임.

---

## 10. ID 체계 정리 (혼동 주의 — 실은 3종 + 이력용 1개)

| 이름 | 코드 표기 | 정체 | 생성 주체 | 범위 |
|---|---|---|---|---|
| **콜 ID** | `callId` / `currentCallId` / `call_id` | **통화 1건** 식별자 | 서버(콜 연결 시) | 통화 전체 |
| **턴 인덱스** | `turn_idx` / `turnIdx` | **발화 턴** 번호(0,1,2…) | 서버 STT | 발화 한 마디 |
| **버블 ID** | `bubbleId` / `messageId` / `item.id` | **채팅 버블** 순번(1,2,3…) | 프론트(`messageIdCounter++`, chat/index.vue:752,1360) | 화면 버블 1개 |
| (이력) | `callStatsId` | 통화 **종료 후** 이력 식별자 | 서버 | 이력 모달 전용 |

### 핵심 포인트
1. **`messageId` == `bubbleId`** — 같은 값이다. 버블 생성 시 `number`(`item.id`), RAG에 넘길 때 `String(targetBubbleId)`로 문자열 변환할 뿐(`useChatMessageParser.ts:482`). 이름이 둘이라 많아 보였을 뿐.
2. **버블 ID는 프론트 로컬 카운터** — `messageIdCounter=1` 시작, 버블마다 `++`. 서버와 무관한 화면용 순번.
3. **포함 관계**: `callId (통화 1건) → turn_idx 0,1,2… (서버 STT 발급) → bubbleId/messageId (프론트 버블) → RAG 결과(messageId로 매핑)`.

### "RAG/상담사 말이 어느 turn에 매핑되나" (정확한 답)
1. **턴↔버블 매핑**: 서버 `turn_idx`가 이전과 같으면 **같은 버블에 머지**, 다르면 **새 버블 생성**(`useChatMessageParser.ts:295, 396, 404`). partial STT 조각이 한 turn으로 뭉쳐 한 버블이 됨.
2. **상담사 말**: 상담사 발화도 버블로 들어옴(sender=consultant). **단 RAG는 고객 발화(`isUser`)에만 트리거** → 상담사 버블엔 문서 안 붙음.
3. **RAG 문서 매핑**: 검색을 트리거한 **그 고객 발화 버블 id(=messageId=그 turn)** 에 결과를 매단다.
4. **turn_idx의 이중 용도**: 화면 매핑(bubbleId) 외에, 백엔드 저장 시 VOC/snapshot과 1:1 묶는 키(`saveAssistSnapshot`의 `turnIdx`). → **turn_idx = 백엔드 저장용 키, bubbleId = 화면 표시용 키**.

### 통신 채널 요약
- **STT**: WebSocket (`useChatSocket`) — 발화 실시간 수신
- **RAG**: SSE (`callAssistStream` / `callDocumentStream`) — 검색·답변 스트리밍
- 두 채널은 별개로 들어오지만 **`turn_idx`에서 만나 같은 버블로 합류**.

---

## 11. "지식저장소" 패널 (챗봇 우측, VOC 영역 아래) — RAG 결과의 풀 버전 표시처

> 챗봇 버블 아래 인라인 카드는 "요약본", 이 패널은 같은 RAG 데이터의 **풀 버전(본문 트리 + 원본 + 북마크)**.
> ⚠️ 실제 컴포넌트는 `TabTypeKnowledgeIndex.vue`. `knowledge/index.vue`는 미사용 레거시(import 0).

### 레이아웃 — VOC와의 관계 (`src/view/advisor/agent/index.vue:55-67`)
```
챗봇 우측 컬럼
├─ CustomerVocPanel       (.adv-voc-area)        ← 고객 VOC 감지, 통화중에만, 별도 영역
└─ TabTypeKnowledgeIndex  (.adv-knowledge-area)  ← "지식저장소" (분석 대상)
```
VOC와 지식저장소는 **위아래로 붙은 별개 컴포넌트**. (VOC=`src/view/advisor/components/voc/CustomerVocPanel.vue`)

### 패널 구조 = 탭 기반 멀티세션 (`TabTypeKnowledgeIndex.vue`)
발화/검색마다 탭이 쌓이며, 탭 type 2종:

| 탭 type | 생성 계기 | 상단 | 본문 |
|---|---|---|---|
| **`chat`** | 고객 발화 RAG 자동 | — | `DocumentContentPanel`(AI답변 + 문서본문) |
| **`search`** | 상담사 수동 검색 | AI답변 스트리밍 박스 고정 | 미선택 시 카드리스트(`DocumentList`) / 선택 시 본문 전체폭 |

### "부분 → 전체 토글"의 실체 (2단 작동)
**1) 문서 본문 트리 = `ContentCollapse.vue` (재귀 아코디언)**
- `isCollapsed` 펼침/접힘, `isUp` 화살표 방향(`ContentCollapse.vue:44,35`).
- `children` 배열을 **자기 자신으로 재귀 렌더**(`:79`) → outline 계층(섹션→하위→손자)을 트리로 펼침.
- 각 섹션에 **북마크**(`BookmarkAPI`) 내장.

**2) "관련 부분만 자동으로 열기" = `useKnowledgeContentItems.handleDetailItemClick`**
- 문서 `contents.outline` → ContentItem 트리 변환(`:61`).
- 핵심 **`shouldBeOpen(title, keywords)`**(`:33`): RAG 힌트 키워드와 제목이 일치하는 섹션만 펼친 채 초기화, 나머지 접힘.
- 그 섹션으로 **자동 스크롤**(`waitForElementsAndScroll`).
- → "전체 문서 중 관련 부분만 펼치고 나머지는 접힘" 동작의 출처.

### "문서와 링크" = 2개 모달
- **`DocumentDetailModal`** — 문서 상세 전체(역시 ContentCollapse 트리).
- **`DocOriginalViewerModal`** — 원본 파일(DOCX/PDF). `KnowledgeAPI.getDocumentOriginal(documentId)`로 원본 바이너리 조회.

### RAG 데이터 → 패널 유입 경로 (10절 RAG와 연결)
```
chat SSE → useChatAssist emit
  → chat/index.vue → agent/index.vue → knowledgeRef(TabTypeKnowledgeIndex)
     ├─ props.chatDocumentList   ← sources (문서 리스트)
     ├─ props.chatSelectedRefs   ← distilled (하이라이트/펼침 대상)
     ├─ props.chatSummary        ← AI 답변 텍스트
     └─ knowledgeRef.handleDetailItemClick(...) 직접 호출 ← 첫 문서 자동 선택·펼침
```

### DocumentContentPanel 내부 (`DocumentContentPanel.vue`)
- 상단 `summary` 있으면 **"AI 답변" 박스**(llm-summary-box) 노출.
- 그 아래 `DocumentDetailView`(→ ContentCollapse 트리)로 문서 본문 렌더.

### 관련 파일
- `src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue` — 탭/패널 메인
- `…/DocumentContentPanel.vue` — AI답변 박스 + 본문
- `…/DocumentDetailView.vue` / `…/ContentCollapse.vue` — 재귀 토글 트리
- `…/DocumentDetailModal.vue` / `…/DocOriginalViewerModal.vue` — 상세/원본 모달
- `…/composables/useKnowledgeContentItems.ts` — outline→ContentItem, 키워드 자동펼침/스크롤
- `…/composables/useKnowledgeModals.ts` — 모달/원본뷰어 오픈
- `src/view/advisor/components/voc/CustomerVocPanel.vue` — VOC 감지(위 영역)

### 참고 (정리 후보)
- `knowledge/index.vue` 미사용 레거시 → 제거 검토 대상.
- `ContentCollapse.vue:284`, `useKnowledgeContentItems.ts:114` 등에 데모용/placeholder 흔적 — 일부 fallback 렌더는 임시 코드.
