# asst-web TODO 정리

> 작성일: 2026-04-22
> 최종 업데이트: 2026-04-22 (Phase 4 Auth + 레거시 정리 완료)
> 대상: `asst-web/src`
> 관련 계획서: [BFF 전환 계획](./2026-04-16-bff-transition-plan.md)

---

## 0순위 — 보안 즉시 수정 ✅ 완료

| 파일 | 라인 | 문제 | 조치 |
|------|------|------|------|
| ~~`src/envs.ts`~~ | ~~3-4~~ | ~~AES128 키/IV 하드코딩~~ | ✅ 환경변수(`VITE_AES128_*`)로 이동 |
| ~~`src/utils/token.js`~~ | ~~25~~ | ~~`console.log` 복호화 토큰 노출~~ | ✅ 제거 |
| ~~`src/utils/postMessage.ts`~~ | ~~84, 95~~ | ~~`postMessage(tokenData, "*")`~~ | ✅ `iframeDomainAndPort.value`로 교체 |
| `.env.aws`, `.env.ncp`, `.env.test` | — | `VITE_AES128_*` 키 미추가 | ⏳ 사용자 직접 추가 필요 |

---

## 1순위 — 하드코딩 URL 제거 ✅ 완료

| 파일 | 라인 | 내용 |
|------|------|------|
| ~~`src/api/modules/request.ts`~~ | ~~12~~ | ~~`baseURL = "http://10.1.1.1:3030"`~~ | ✅ 환경변수로 교체 |
| ~~`src/utils/SocketClient.js`~~ | ~~21~~ | ~~`"http://192.168.0.129:3000"` fallback~~ | ✅ 환경변수로 교체 |
| ~~`src/stores/modules/socket.ts`~~ | ~~83~~ | ~~`"wss://dev-ecp-asst-service.langsa.ai"` fallback~~ | ✅ `VITE_ADVISOR_SOCKET_URL`로 교체 |
| ~~`src/utils/AppInitializer.ts`~~ | ~~54~~ | ~~`"wss://dev-ecp-asst-service.langsa.ai"` 하드코딩~~ | ✅ `VITE_ADVISOR_SOCKET_URL`로 교체 |

---

## 2순위 — BFF 전환 (계획서 Phase 0~5)

> 상세 실행 계획: [2026-04-16-bff-transition-plan.md](./2026-04-16-bff-transition-plan.md)

### Phase 0: 백엔드 인프라 준비 ✅ 완료
- [x] `asst-service/src/common/services/http-client.service.ts` 생성 (raw axios 기반 공통 HTTP 클라이언트)
- [x] `asst-service/src/common/proxy/` 디렉토리 및 모듈 구조 생성 (`proxy.module.ts`)
- [x] 백엔드 환경변수 validation 추가: `KNOWLEDGE_HOST`, `TA_HOST`, `QA_API_URL`, `AUTH_SERVICE_API_URL` (optional)

### Phase 1: User 서비스 전환 ✅ 완료
- [x] `asst-service/src/common/proxy/user-proxy.controller.ts` 생성
  - `GET /proxy/user/get_user`
  - `GET /proxy/user/profile/:id`
  - `GET /proxy/user/get_managers`
  - `GET /proxy/user/organization/affiliation`
  - `PATCH /proxy/user/update_role`
  - `PATCH /proxy/user/update_permission`
  - `PATCH /proxy/user/update_assigned_workspace_id`
- [x] `asst-web/src/common/interface/user.ts` — 직접 axios 호출 → `advisor` 인스턴스 BFF 경유
- [x] `assignWorkspace()` 제거 (→ `ManageWorkspace.vue` import도 `updateAssignedWorkspace`로 교체)
- [x] `getCenterTeamPart()` → `getOrganizations()` 위임으로 단순화
- [ ] `VITE_NEW_USER_SERVICE_API_URL` 환경변수 제거 (account.api.ts, organization.api.ts 전환 후 가능)

### Phase 2: Knowledge + TA 서비스 전환 ✅ 완료
- [x] `asst-service/src/common/proxy/knowledge-proxy.controller.ts` 생성
  - `POST /proxy/knowledge/search/retrieve_doc`
  - `GET /proxy/knowledge/indexes/get_doc_idx`
  - `GET /proxy/knowledge/sections/get_section`
  - `GET /proxy/knowledge/docs/get_doc`
- [x] `asst-service/src/common/proxy/ta-proxy.controller.ts` 생성
  - `GET /proxy/ta/dashboard/main/stat/total`
- [x] `asst-web/src/api/apis/knowledge.api.ts` — `knowledge` 인스턴스 → `advisor` 인스턴스
- [x] `asst-web/src/api/apis/stats.api.ts` — `ta` 인스턴스 → `advisor` 인스턴스
- [ ] `VITE_KNOWLEDGE_API_URL`, `VITE_TA_API_URL` 환경변수 제거 (apiPlugin `knowledge`/`ta` 인스턴스 제거 후 가능)

### Phase 3: CE (REST) + QA 서비스 전환 ✅ 완료
- **QA** ✅ 완료
  - [x] `asst-service/src/common/proxy/qa-proxy.controller.ts` 생성 (`POST /proxy/qa/calls/end`)
  - [x] `CounselingStatus.vue:509` — 직접 `axios.post` → `getClient("advisor")` + BFF 경유
  - [ ] `VITE_QA_API_URL` 환경변수 제거 (백엔드에서만 사용)
- **CE REST** ✅ 완료
  - [x] `asst-service/src/common/proxy/ce-proxy.controller.ts` 생성
    - `GET /proxy/ce/bots`
    - `GET /proxy/ce/bots/:botId`
    - `GET /proxy/ce/nlu-catalog/intents/all`
    - `GET /proxy/ce/nlu-catalog/intents/:intentId`
    - `GET /proxy/ce/lexicon/external-categories/all`
    - `GET /proxy/ce/lexicon/external-categories`
    - `GET /proxy/ce/workspaces`
    - `GET /proxy/ce/workspaces/:workspaceId`
    - `POST /proxy/ce/advisor/search-documents`
  - [x] `asst-service/src/config/validation.config.ts` — `CE_HOST` 환경변수 추가
  - [x] `asst-web/src/api/apis/bot.api.ts` — `ce` 인스턴스 → `advisor` 인스턴스
  - [x] `asst-web/src/api/apis/intent.api.ts` — `ce` 인스턴스 → `advisor` 인스턴스
  - [x] `asst-web/src/api/apis/lexicon.api.ts` — `ce` 인스턴스 → `advisor` 인스턴스
  - [x] `asst-web/src/api/apis/workspace.api.ts` — `ce` 인스턴스 → `advisor` 인스턴스
  - [x] `asst-web/src/api/apis/advisor-search.api.ts` — `ce` 인스턴스 → `advisor` 인스턴스
  - [ ] `VITE_CE_SERVICE_API_URL` apiPlugin에서 제거 (단, Socket.IO 연결용 변수 자체는 유지)

### Phase 4: Auth 전환 + 레거시 정리 ✅ 완료
- [x] `account.api.ts`, `organization.api.ts` — `user` 인스턴스 → `advisor` 경유로 전환
  - [x] `asst-service` `user-proxy.controller.ts` — `GET /account`, `/account/tenant`, `/account/list`, `/organization/centers`, `/organization/centers/:id`, `/organization/teams`, `/organization/teams/:id` 추가
- [x] `dashboard.ts` — `knowledge` 인스턴스 → `advisor` 경유로 전환
  - [x] `asst-service` `knowledge-proxy.controller.ts` — `GET /dashboard/popular` 추가
- [x] `VITE_ACCESS_TOKEN` 폴백 로직 제거 (`apiPlugin.ts` line 43)
- [x] `apiPlugin.ts` — ServiceKey `"advisor" | "auth" | "audio"`로 축소, `user`/`knowledge`/`ta`/`nlp`/`ce` 인스턴스 제거
- [x] `api/apis/index.ts` — ServiceKey 동기화
- [x] `stores/modules/api.ts` — 미사용 getter(`getKnowledgeApi`, `getUserApi`, `getTaApi`, `getCeApi`) 제거
- [x] `consultant/index.vue`, `admin/index.vue`, `admin/management/user/index.vue` — baseUrls를 `advisor`/`auth`/`audio` 3개로 축소
- [x] `admin/index.vue` — `initSocket` 하드코딩 폴백 URL 제거
- [x] `apiPlugin.test.ts` — baseUrls 3개로 축소
- [ ] `api/modules/request.ts` — 활성 import 4개 있어 삭제 보류
- [ ] `VITE_NEW_USER_SERVICE_API_URL`, `VITE_KNOWLEDGE_API_URL`, `VITE_TA_API_URL`, `VITE_QA_API_URL`, `VITE_CE_SERVICE_API_URL` 환경변수 `.env.*` 파일에서 제거 (직접 수정 필요)

### 병행 구조 정리: initApi 중복 초기화 ✅ 완료
- [x] `src/view/advisor/consultant/index.vue` — `baseUrls` 하드코딩 폴백 URL 제거
- [x] `src/view/advisor/admin/index.vue` — 하드코딩 폴백 URL 제거
- [x] `src/view/advisor/admin/management/user/index.vue` — 동일
- [x] `admin/index.vue`, `admin/management/user/index.vue` — `initApi`/`initSocket`/`connect` 중복 호출 제거 (consultant/index.vue에서 1회 초기화하므로 하위 컴포넌트 불필요)

---

## 3순위 — 미구현 기능 ✅ 완료

| 파일 | 내용 |
|------|------|
| ~~`dialog_page.vue` 255, 261~~ | ~~`handleWorkspaceChange`, `handleBotChange` TODO~~ | ✅ `handleEdit`에 워크스페이스/봇 저장 로직 이미 구현됨 — 미사용 dead code 제거 |

---

## 4순위 — 파일/구조 정리 ✅ 완료

| 파일 | 내용 |
|------|------|
| ~~`src/api/config/databaseConstants.ts`~~ | ✅ 미사용 — 삭제 |
| ~~`src/api/config/venderConstants.ts`~~ | ✅ 미사용 — 삭제 |
| ~~`src/stores/modules/global.ts`~~ | ✅ `layout.ts`로 rename, `useGlobalStore` → `useLayoutStore`, store id `"ecp-global"` → `"ecp-layout"`, 27개 파일 import 업데이트 |

---

## 5순위 — 코드 품질 개선 ✅ 완료

| 파일 | 내용 |
|------|------|
| ~~`Message.vue` 106-107~~ | ✅ TODO 주석 제거 — `alert.ts`가 Module Federation 모듈 의존성을 가져 router main bundle에 추가 시 빌드 실패. `onMounted` 방식 유지 (헤더 레이아웃은 리마운트 없이 1회만 실행되므로 중복 없음) |
| ~~`code.ts` 45, 64~~ | ✅ `obj: any` → `obj: Partial<{ sort: string[]; size: number }> = {}` 타입 명시, 불필요한 타입가드 제거 |

---

## 6순위 — 리팩토링 ✅ 완료

| 파일 | 내용 |
|------|------|
| ~~`excel.ts`~~ | ✅ `ExcelColumn` 인터페이스 도입, `any` 타입 제거, 하드코딩 title `"사비스 통계"` → `fileName` 사용, `s2ab` 함수 외부로 분리, TODO 주석 제거 |
| ~~`Maximize.vue` 14~~ | ✅ TODO 주석 제거 — Pinia store 직접 접근이 이미 올바른 패턴 (mitt는 store 없는 컴포넌트 간 통신용이므로 여기엔 불필요) |

---

## 7순위 — 기능 추가 / 스타일

| 파일 | 라인 | 내용 |
|------|------|------|
| `src/styles/tiptap.scss` | 64 | 텍스트 색 편집 기능 추가 시 스타일 수정 필요 |
| `src/view/example/collection/components/Table/index.vue` | 96 | 테이블 리팩토링 시 타입 정확화 필요 |

---

## 참고 — 직접 연결 유지 대상 (전환 제외)

| 파일 | 프로토콜 | 이유 |
|------|----------|------|
| `src/api/apis/assist-stream.api.ts` | SSE (`fetch`) | axios로 처리 불가 |
| `src/api/apis/document-search.api.ts` | SSE (`fetch`) | 동일 |
| `src/components/editor/EditorComponent.vue` | `fetch` | 이미지 blob 처리 특수 케이스 |
| `src/utils/common.ts` | Native WebSocket | 바이너리 오디오 스트리밍 — BFF 경유 불필요 |
| `src/utils/AdvisorbotClient.ts` | Socket.IO | 실시간 양방향 스트리밍 — BFF 경유 시 레이턴시 증가 |
| `src/stores/modules/websocket.ts` | SockJS/STOMP | CCAAS 브로드캐스트 구독 |
