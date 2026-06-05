# chat/index.vue 리팩토링 구현 계획

> **상태: 완료** — 2026-04-27

**Goal:** 3527줄의 chat/index.vue에서 독립적으로 수정되는 관심사를 composable로 분리해 2000줄 이하로 줄이고, 데모 코드를 제거한다.

**Architecture:** 분리 기준은 "독립적으로 바뀌는 코드" — AI 스트림/검색/소켓/Todo/키워드 상호작용/Popover 드래그/메시지 파서는 각각 별도 composable로 추출. index.vue는 메시지 렌더링 + 필터/클리핑 상태 관리에 집중한다.

**Tech Stack:** Vue 3, TypeScript, Pinia, Socket.IO

---

## 실제 결과

| 항목 | 전 | 후 |
|------|----|----|
| `chat/index.vue` | 3527줄 | **1899줄** (-1628줄, -46%) |
| dead import | useChatFilter/Keyword/Clipping | **삭제** (inline 구현이 이미 존재했음) |
| [데모용] extractDemoTitle | 잔존 | **제거** |
| typecheck (chat 관련) | - | pre-existing 에러 외 신규 없음 |

### 추출된 composable 파일

| 파일 | 줄수 | 담당 |
|------|------|------|
| `useChatAssist.ts` | 779 | AI 스트림, 자동 선택, 검색 쿼리 클릭 |
| `useChatKeywordInteraction.ts` | 348 | 키워드 버블/업다운/상세/추천태그 |
| `useChatMessageParser.ts` | 285 | redis-message 파싱 (call events, nlp:complete 등) |
| `useChatSearch.ts` | 206 | 검색 위치 계산 + 이전/다음 네비게이션 |
| `useChatTodo.ts` | 185 | Todo 상태 + 핸들러 |
| `useChatPopoverDrag.ts` | 104 | Popover 드래그 이동 |
| `useChatSocket.ts` | 82 | 소켓 구독 + redis-message 리스너 |

---

## Task 1: [데모용] extractDemoTitle 코드 제거 ✅

- `extractDemoTitle` 함수 삭제
- 사용처에서 fallback 값으로 교체
- dead import(useChatFilter, useChatKeyword, useChatClipping) 제거 및 파일 삭제
  - 조사 결과 inline 구현이 이미 더 발전된 형태로 존재 → 통합 불필요, 파일 삭제

---

## Task 2: useChatAssist.ts 추출 ✅

- AI 스트림(`handleAssistStream`), 자동 선택(`handleAutoSelectKeyword`, `handleAutoSelectKeywordV2`), 검색 쿼리(`handleSearchQueryClick`), `executeAutoSelection` 이동
- `abortAllStreams`으로 AbortController 일괄 정리
- index.vue에서 ~720줄 감소
- 수정 사항: `emit` 타입 오류 수정, console.log 9개 제거, pendingSources 미사용 변수 제거

---

## Task 3: useChatSearch.ts 추출 ✅

- `calculateSearchPositions`, `goToPreviousSearchResult`, `goToNextSearchResult`, `handleSearchEnterNavigate`, `resetSearch` 이동
- index.vue에서 ~200줄 감소

---

## Task 4: useChatSocket.ts 추출 ✅

- `subscribeChannels`, `unsubscribeChannels`, `setupListeners`, `teardownListeners` 이동
- 소켓 공유 특성상 teardown 시 room/channel 해제 생략 (주석 명시)

---

## Task 5: useChatTodo.ts 추출 ✅

- `todoList`, `showAddTodoForm`, `todoTitle`, `todoLoading`, `todoInputRef` + 핸들러 이동
- `groupList` 목업 제거
- `Promise.all` 내 return 누락 버그 수정

---

## Task 6: useChatKeywordInteraction.ts 추출 ✅

- 키워드 버블 선택, 업다운, 상세, 추천태그 전체 이동 (~350줄)
- `keywordDetailData`, `keywordOrder`, `keywordLabels` 포함

---

## Task 7: useChatPopoverDrag.ts 추출 ✅

- Popover 드래그 시작/이동/종료, 위치 초기화 이동 (~55줄)
- 중복 `resetPopoverPosition` 정의 제거 버그 수정

---

## Task 8: useChatMessageParser.ts 추출 ✅

- `parseMessageData` 전체 이동 (~287줄)
- `:call:events`(start/end), `nlp:complete`, `orchestrator:persisted` 채널 처리 포함
- `callTimer`, `callStartTimestamp`를 `let` → `ref`로 변환하여 composable에 ref로 전달
- stores(agentStatusStore, userListStore, callSummaryInfoStore, customerStore, userProfileStore) composable 내부에서 직접 사용
- `emit` 타입 캐스팅 패턴 정립: `emit as (event: string, ...args: unknown[]) => void`

---

## 부가 작업: CLAUDE.md 파일 분리 기준 업데이트 ✅

- 기존 "파일당 200~400줄, 800줄 초과 금지" → `feedback_file_splitting_criteria.md` 기준으로 교체
- 1000줄 미만 분리 없이 유지, 응집도 우선 원칙 반영
