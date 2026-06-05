# 데모 코드 목록

> 작성일: 2026-04-23  
> 최종 확인: 2026-04-27  
> 목적: 데모용으로 작성된 임시 코드 위치 파악 및 정리 기준 마련

---

## 1. [데모용] 명시적 표시 — 최우선 제거 대상

데모 종료 시 반드시 원복해야 하는 코드들.

| 파일 | 줄 | 설명 | 상태 |
|------|-----|------|------|
| `asst-web/src/view/advisor/components/chat/index.vue` | 2010 | `[데모용]` content에서 "Q. ~~~" 추출해 제목으로 사용 | ✅ 제거됨 |
| `asst-web/src/view/advisor/components/knowledge/ContentCollapse.vue` | 9 | `[데모용]` Q. 추출 제목 우선 표시 (템플릿) | ✅ 제거됨 |
| `asst-web/src/view/advisor/components/knowledge/ContentCollapse.vue` | 275–277 | `[데모용]` 본문에서 Q. 라인 제거 | ✅ 제거됨 |
| `asst-web/src/view/advisor/components/knowledge/ContentCollapse.vue` | 284–310 | `[데모용]` `demoQuestionTitle`, `displayTitle` computed 정의 | ✅ 제거됨 |

---

## 2. 목업/샘플 데이터

### 2-1. 목업 메뉴

| 파일 | 설명 | 상태 |
|------|------|------|
| `asst-web/src/api/modules/menus/mockupMenu.ts` | 서버 API 연동 전 사용한 목업 메뉴 함수 (`getAuthMenuListMockup`) | ⏳ 미제거 |
| `asst-web/src/api/modules/menus/mockupMenuList.ts` | 하드코딩된 메뉴 구조 데이터 (5개 항목) | ⏳ 미제거 |

### 2-2. 하드코딩된 계정 정보

| 파일 | 줄 | 설명 | 상태 |
|------|-----|------|------|
| `asst-web/src/view/advisor/admin/index.vue` | 376–389 | 임시 테스트용 계정 정보 (`id`, `account_id`, `company_id` 등 하드코딩) | ✅ 제거됨 |

### 2-3. 샘플 JSON 파일

| 파일 | 크기 | 설명 | 상태 |
|------|------|------|------|
| `asst-web/src/view/advisor/components/chat/sample.json` | 647 KB | 채팅 샘플 데이터 | ✅ 제거됨 |
| `asst-web/src/view/advisor/components/knowledge/sample.json` | 564 KB | 지식 샘플 데이터 | ✅ 제거됨 |
| `asst-web/src/view/advisor/components/sample.json` | — | 컴포넌트 샘플 | ✅ 제거됨 |
| `asst-web/src/stores/modules/sample.json` | — | 스토어 샘플 | ✅ 제거됨 |

---

## 3. 테스트용 Socket 핸들러 (백엔드)

| 파일 | 줄 | 이벤트명 | 설명 | 상태 |
|------|-----|---------|------|------|
| `asst-service/src/common/gateways/socket.gateway.ts` | 31 | — | `origin: true` 모든 origin 허용 (디버깅용 임시 설정) | ⏳ 미제거 |
| `asst-service/src/common/gateways/socket.gateway.ts` | 411–446 | `create-test-room` | 테스트용 room 생성 핸들러 | ✅ 제거됨 |
| `asst-service/src/common/gateways/socket.gateway.ts` | 448–491 | `broadcast-test-message` | 테스트용 메시지 브로드캐스트 핸들러 | ✅ 제거됨 |
| `asst-service/src/common/gateways/socket.gateway.ts` | 515–527 | `test-event` | 테스트용 단순 이벤트 핸들러 | ✅ 제거됨 |
| `asst-service/public/socket-demo.html` | — | — | Socket.IO 브라우저 테스트 페이지 | ✅ 제거됨 |

---

## 4. 테스트/예제 전용 디렉토리

실서비스와 무관한 테스트·예제 파일 디렉토리.

| 경로 | 주요 파일 | 설명 | 상태 |
|------|----------|------|------|
| `asst-web/src/examples/` | `ChatStateExample.vue`, `SocketStoreExample.vue`, `MultiRoomSocketExample.vue`, `MessageStorageExample.vue`, `ApiStoreExample.vue` | Socket·Chat·API 동작 예제 컴포넌트 | ✅ 제거됨 |
| `asst-web/src/view/example/agentRenewal/` | `AgentDashboardTest.vue`, `CallControlPanelTest.vue` 등 | 상담원 페이지 리뉴얼 UI 테스트, `Math.random()` 기반 데이터 시뮬레이션 포함 | ✅ 제거됨 |
| `asst-web/src/view/example/collection/` | `ButtonExample`, `TableExample`, `ChartExample` 등 | 컴포넌트 예제 모음 | ✅ 제거됨 |
| `asst-web/src/view/example/groupCollection/` | — | 그룹 컬렉션 테스트 | ✅ 제거됨 |
| `asst-web/src/view/example/test/` | — | 기타 테스트 파일 | ✅ 제거됨 |

---

## 5. 임시 구현 (미완성)

| 파일 | 줄 | 내용 | 상태 |
|------|-----|------|------|
| `asst-web/src/utils/SocketRoomOptimizer.ts` | 158 | 연결 지연 측정 `return Math.random() * 100; // 임시 구현` | ⏳ 미제거 |
| `asst-web/src/utils/SocketRoomOptimizer.ts` | 166 | 오류율 계산 `return 0; // 임시 구현` | ⏳ 미제거 |
| `asst-web/src/components/layout/HeaderActionBar/CustomerInfo.vue` | 56 | 상담사 정보 API 미연동 → `consultantName: "-"` 임시 처리 | ⏳ 미제거 |
| `asst-web/src/components/editor/EditorComponent.vue` | 26 | `isDark = ref(false)` 전역 상태 연동 필요 | ⏳ 미제거 |
| `asst-web/src/composables/composables.js` | 404 | `// 임시..` 주석의 미완성 그리드 처리 함수 | ⏳ 미제거 |
| `asst-service/src/common/guards/admin.guard.ts` | 20 | `Math.random()` 기반 임시 요청 ID 생성 | ⏳ 미제거 |

---

## 정리 현황 요약 (2026-04-27 기준)

| 섹션 | 총 항목 | 완료 | 잔여 |
|------|--------|------|------|
| 1. [데모용] 명시 코드 | 4 | 4 | 0 ✅ |
| 2-1. 목업 메뉴 | 2 | 0 | 2 |
| 2-2. 하드코딩 계정 | 1 | 1 | 0 ✅ |
| 2-3. 샘플 JSON | 4 | 4 | 0 ✅ |
| 3. Socket 테스트 핸들러 | 5 | 4 | 1 (`origin: true`) |
| 4. 예제 디렉토리 | 5 | 5 | 0 ✅ |
| 5. 임시 구현 | 6 | 0 | 6 |
| **합계** | **27** | **18** | **9** |

### 잔여 작업 (우선순위순)

1. **`socket.gateway.ts` `origin: true`** — 프로덕션 보안 위험, CORS 도메인 화이트리스트로 교체 필요
2. **목업 메뉴 파일 2개** (`mockupMenu.ts`, `mockupMenuList.ts`) — 실 API 연동 확인 후 삭제
3. **임시 구현 6개** — 실 구현으로 교체 필요 (우선순위: CustomerInfo.vue 상담사 API 연동 → SocketRoomOptimizer 실측 로직 → 나머지)
