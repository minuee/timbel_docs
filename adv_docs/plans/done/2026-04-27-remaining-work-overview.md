# 잔여 작업 현황 계획서

> 작성일: 2026-04-27  
> 최종 업데이트: 2026-04-27  
> **상태: 전체 완료 (2026-04-27)**  
> 목적: 현재 확인된 미완료 작업 전체 정리

---

## 우선순위 요약

| 순위 | 카테고리 | 난이도 | 상태 |
|------|---------|-------|------|
| 1 | 데모 코드 정리 | 낮음 | ✅ 완료 (2026-04-27) |
| 2 | 백엔드 리팩토링 잔여 | 중간 | ✅ 완료 (2026-04-27) |
| 3 | BFF 환경변수 잔여 정리 | 낮음 | ✅ 완료 (2026-04-27) |
| 4 | 프론트엔드 대형 컴포넌트 분리 | 높음 | ✅ 완료 (2026-04-27) |

---

## 1. 데모 코드 정리 ✅ 완료 (2026-04-27)

> 참고: `adv_docs/plans/demo-code-inventory.md`  
> 커밋: asst-web `03430d7`, asst-service `f29e541`

### ~~1-1. [데모용] 주석 코드~~ ✅

- ~~`ContentCollapse.vue`~~: `demoQuestionTitle`/`displayTitle` computed 제거, `props.title` 직접 사용
- `chat/index.vue`: 데모 코드 없음 (chat 리팩토링 시 이미 제거됨)

### ~~1-2. 테스트용 Socket 핸들러~~ ✅

- ~~`socket.gateway.ts`~~: `origin: true` → 환경 기반 CORS, `create-test-room` / `broadcast-test-message` / `test-event` 핸들러 제거
- ~~`socket-demo.html`~~: 삭제

### ~~1-3. 목업/샘플 데이터 (부분 완료)~~ ⚠️

- ~~`admin/index.vue`~~: 하드코딩 계정 fallback 제거
- ~~sample.json 4개~~: 삭제
- `mockupMenu.ts` / `mockupMenuList.ts`: **스킵** — `auth.ts`에서 현재 실 사용 중. 실제 메뉴 API 구현 완료 후 제거 가능

### ~~1-4. 예제/테스트 디렉토리~~ ✅

- ~~`src/examples/`~~: 삭제 (5개 컴포넌트)
- ~~`src/view/example/`~~: 삭제 (agentRenewal, collection, groupCollection, test)

### 1-5. 임시 구현 (실 구현 교체 필요 — 별도 작업)

| 파일 | 내용 |
|------|------|
| `asst-web/src/utils/SocketRoomOptimizer.ts:158,166` | `Math.random()` 임시 구현 |
| `asst-web/src/components/layout/HeaderActionBar/CustomerInfo.vue:56` | 상담사 정보 API 미연동 (`"-"` 임시) |
| `asst-service/src/common/guards/admin.guard.ts:20` | `Math.random()` 기반 임시 요청 ID |

---

## 2. 백엔드 리팩토링 잔여 ✅ 완료 (2026-04-27)

> 참고: `adv_docs/plans/done/2026-04-21-backend-phase1-refactor-plan.md`

### 최종 상태

| 파일 | 결과 | 상태 |
|------|------|------|
| `redis.service.ts` | `coaching-redis.service.ts` (133줄) 분리 | ✅ 완료 |
| `socket.gateway.ts` | `handlers/` 3개 위임 + 테스트 핸들러 제거 (677줄) | ✅ 완료 |
| `summary.service.ts` | 파일 내 private 헬퍼 추출 (커밋: `2fa08ce`) | ✅ 완료 |

### ~~Task A: summary.service.ts — 파일 내 private 메서드 정리~~ ✅

> 파일 분리 없음 — LLM 호출/저장/조회는 항상 함께 보는 코드이므로 같은 파일 유지

**추출 완료:**

| 헬퍼 | 역할 | 비고 |
|------|------|------|
| `saveEntityItems<T>` | 반복 저장 루프 | 이미 구현됨 (이전 세션) |
| `handleDbError` | 4개 catch 블록 → 단일 헬퍼 (`HttpException` 포함 재-throw) | 완료 |
| `logSummaryOp` | 로깅 헬퍼 | **스킵** — 각 로그 메시지가 달라 추상화 실익 없음 |

---

## 3. BFF 환경변수 잔여 정리 ✅ 완료 (2026-04-27)

> `.env*` 파일에서 불필요 환경변수 제거 완료 (사용자 직접 수정)

---

## 4. 프론트엔드 대형 컴포넌트 리팩토링

> 실측 파일 크기 기준 (2026-04-27)  
> CLAUDE.md 기준: 1500줄+ 검토, 2000줄+ 분리 확실

| 파일 | 실측 줄 수 | 우선순위 | 예상 작업 |
|------|-----------|---------|---------|
| `knowledge/TabTypeKnowledgeIndex.vue` | ~~1421줄~~ → 781줄 | ✅ 완료 | useKnowledgeSearch + useKnowledgeContentItems 추출 (커밋: `5d3010d`) |
| `ChatHistoryModal.vue` | ~~1206줄~~ → 640줄 | ✅ 완료 | useAudioPlayer + useKeywordDetail 추출 (커밋: `977b567`) |
| `knowledge/index.vue` | ~~1100줄~~ → 713줄 | ✅ 완료 | 미사용 함수/상태 제거 (커밋: `977b567`) |
| `agent/Dashboard.vue` | 1005줄 | 🟢 낮음 | 경계선, 선택적 |
| `Bookmark.vue` | 756줄 | — | 1000줄 미만, 현상 유지 |
| `AdminCoaching.vue` | 757줄 | — | 1000줄 미만, 현상 유지 |
| `SpeechBubble.vue` | 596줄 | — | 1000줄 미만, 현상 유지 |

---

## 진행 제안 순서

```
✅ 1. 데모 코드 정리 — 완료
✅ 2. 백엔드 summary.service 헬퍼 추출 — 완료
✅ 3. BFF 환경변수 정리 — 완료
✅ 4. 프론트엔드 리팩토링 — 완료 (TabTypeKnowledgeIndex, ChatHistoryModal, knowledge/index)
```
