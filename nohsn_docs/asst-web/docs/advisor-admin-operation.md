# 상담 어드바이저 관리자 페이지 운영 구조

> `advisor/admin` 경로의 관리자 메인 페이지 분석. 핵심은 **상담사 실시간 모니터링 + 양방향 코칭 + 전체 공지**.
> 메인 파일: `src/view/advisor/admin/index.vue`

---

## 0. 진입 흐름 (역할 분기)

```
로그인 → advisor/consultant (진입점, 프로필로 역할 판별)
           ├─ role=admin → advisor/admin/index.vue   (관리자 메인 ← 본 문서)
           └─ role=agent → advisor/agent/index.vue   (상담사 실무)
```

- 관리자 페이지 안에서 상담사 화면을 그대로 띄워 볼 수도 있음(`AgentComponent`를 Viewer로, `showConsultantView`).

---

## 1. 화면 레이아웃

```
ContentLayout (헤더 + 사이드)
└─ adv-page-layout
   ├─ 좌측: ConsultantDrawer (상담사 목록, 검색/선택, 접기 가능)
   └─ 중앙: [상담사 선택 수에 따라 분기]
        ├─ 0명 → CallHistoryView (콜 이력 조회 화면)
        └─ 1~4명 → Chat ×N (모니터링 그리드)
```

### 중앙 패널 분기 (`admin/index.vue:26~67`)
- **선택 0명** → `CallHistoryView`: 콜 이력 테이블(콜 시작/종료시간·통화시간·콜상태) + "상담이력" 버튼 → `ChatHistoryModal`.
- **선택 1명 이상** → `Chat` 그리드. grid/list 레이아웃 전환.
  - 1명=1열 / 2명=2열 / 3명=좌1+우2 / 4명=2×2 (최대 4명)

> **알려진 TODO** (`admin/index.vue:24~25`): CallHistoryView가 `v-else`라 모니터링 갔다 오면 컴포넌트가 재생성되어 **검색조건·스크롤·페이징 상태가 초기화**됨. 상태유지하려면 store화 필요(미구현, UX 개선용).

---

## 2. 모니터링 (상담사 관제)

### 2-1. 상담사 목록 로드
- `getAgentsOfAdminPage("permission", {page, limit})`를 **`has_next` 동안 페이징 누적** → `userListStore.setAgents()` (`admin/index.vue:250~273`)
- `ConsultantDrawer`가 store 구독해 렌더. 상담사 식별키 = **`cc_cti_id`**.

### 2-2. 실시간 상태 (2채널)
| 채널/이벤트 | 의미 | 핸들러 |
|---|---|---|
| Socket `agent-status-update` (룸 `agent-status`) | 상담사 상태(통화중/대기/이석/휴식/미접속) | `onAgentStatusUpdate` (`:218`) |
| Redis 채널 `dev:{tenant}:{cti}:call:events` | 통화 start/end → `isActive` 토글 | `parseRedisMessage` (ConsultantDrawer) |

- **초기 상태값**: 진입 시 Redis 스냅샷(`getAgentStatusFromRedis`, key `dev:global:call:status:active`)으로 1회 로드 후, 소켓으로 실시간 덮어씀(타임스탬프로 충돌 회피). (`:490~524`)
- ※ `dev:` 프리픽스 하드코딩은 인지된 사항(환경별 분리는 추후).

### 2-3. 상담사 선택 → 모니터링
- `handleConsultantSelect` (`:620`): 토글 방식. 이미 선택이면 제거, 아니면 추가. **4명 초과 시 모달(`showMaxSelectionModal`)로 차단**.
- 선택된 상담사마다 `Chat` 컴포넌트(`isAdmin`)가 렌더되어 **상담내용(통화 STT 대화 + AI 어시스트)을 실시간 모니터링**. 내용 캐시는 `chatDataStore.getChatContent(consultantId)`.
  - ⚠️ 컴포넌트 이름이 `Chat`이라 "채팅(메신저)"으로 오해하기 쉬우나, **양방향 채팅 기능은 아님**. 상담사 실무 화면(`chat/index.vue`)을 `isAdmin`으로 재사용한 **읽기 위주 모니터링 뷰**. 상담사용 입력/검색 UI는 `v-if="!isAdmin"`으로 숨겨짐. 관리자↔상담사 메시지 전달은 **코칭**이 담당.

---

## 3. 코칭 (핵심 기능)

### 3-0. ⭐ 가장 중요 — 3개념 구분
코칭은 별개 3개념이며, 같은 `coaching` 데이터라도 **`coaching_request_id` 유무로 성격이 갈린다.**

| 개념 | 방향 | 의미 | 식별 |
|---|---|---|---|
| **코칭요청** `coaching_request` | 상담사 → 관리자 | "이 통화 코칭해주세요" 요청 | `POST /coachings/requests` |
| **코칭(답변)** `coaching` | 관리자 → 상담사 | 요청에 대한 답변/지시 | `coaching_request_id` 채워짐 |
| **상담코칭(실시간)** `coaching` | 관리자 → 상담사 | 통화 중 즉석 코칭 | `coaching_request_id` **빈값**, `call_id`만 |

### 3-1. 전체 라이프사이클
```
상담사: 코칭요청 작성 → POST /coachings/requests
   ↓ (백엔드 broadcast) socket "coaching_request" (룸 coaching_{관리자id})
관리자: 토스트 + refreshCoachings(true) → AdminCoaching "미답변" 탭에 표시
   ↓ 답변 작성(AdminCoachingCard) → POST /coachings (coaching_request_id 포함)
   ↓ (백엔드 broadcast) socket "coaching"
상담사: 토스트 + refreshCoachings(false) → 답변(comment) 표시
   ↓ "확인" 클릭 → PATCH /coachings/{id}/read
관리자: 미답변 → 답변완료로 전환
```

### 3-2. 보내기 진입 (관리자 → 상담사 코칭요청 모달)
```
Chat "코칭 요청" 버튼 → emit("open-coaching-request")
  → admin: openCoachingRequestModal()
  → ContentLayout.handleOpenModalFromHeader("coaching")
  → AdminDrawerHost.handleMenuClick("coaching")
  → CoachingRequest 모달 → coachingStore.onCreateRequestCoaching() API
```

### 3-3. ⭐ 구조 포인트
- **프론트는 socket emit을 하지 않음.** 전부 REST API만 호출하고, **백엔드가 broadcast**. 프론트는 수신(`on`)만 한다.
- **store 방향 분기**: `refreshCoachings(isAdmin)` 하나로 처리 — 같은 두 배열(`requestCoachings`/`receiverCoachings`)을 관리자/상담사가 정반대로 채움.
  - 관리자: `getCoachingsBySender` + `getCoachingRequestsByReceiver`
  - 상담사: `getCoachingRequestsBySender` + `getCoachingsByReceiver`
- `priority_type`: 긴급=1 / 일반=0
- **★ 중요(favorite)**: 별도 `favorite-coaching` API로 관리 (코칭/코칭요청 각각 별 엔드포인트).

### 3-4. AdminCoaching 모달 탭 필터
| 탭 | 조건 |
|---|---|
| 전체콜 | 전체 |
| 긴급 | `priority_type === 1` |
| 일반 | `priority_type === 0` |
| 미답변 | 응답(response) 없음 |
| 중요 | ★ favorite 등록분 |

### 3-5. 응답 수신 (관리자측)
- Socket `coaching` 수신 → `refreshCoachings(true)` + 토스트(긴급=🚨/일반=💬) (`admin/index.vue:438~455`)

### 3-6. API 구성 (방대함, 실제 사용은 일부)
- `api/apis/coaching.api.ts` — 코칭 생성/조회/응답/읽음/중요·긴급·일반별 조회 등 **20+ 메서드**
- `api/apis/coaching-request.api.ts` — 코칭요청 생성/조회(sender·receiver)/읽음
- `api/apis/favorite-coaching.api.ts` — 중요 코칭/코칭요청 추가·삭제

### 3-7. ⚠️ 미완성으로 보이는 부분 (코드 기준 추정, 실동작 확인 필요)
- AdminCoaching **검색필터의 조회/초기화 버튼**이 실제 필터링에 미연결로 보임
- **정렬(최신/과거)** 옵션이 UI엔 있으나 `sortOption` 반영이 안 된 것으로 보임

---

## 4. 공지사항 등록

```
관리자 전용 "+" 버튼 → AddNotice 모달
  → NoticeAPI.createNotice({ name, is_urgent, content, target_key:"all_users",
                              creator_key, send_socket:true, remind_time? })
  → noticeStore.fetchPopoverNotices()로 목록 갱신 → NoticeCard 표시
```
- 컴포넌트: `Drawer/components/Notice/Notice.vue` + `AddNotice.vue`
- 필드: `is_urgent`(긴급), `remind_time`(예약 발송), `creator_key`(생성자)
- **실시간 전파: 정상 동작 확인됨** — `send_socket:true`로 보내면 상담사에게 **쪽지처럼 실시간 도착**.

---

## 5. 설정 ▸ 키워드 (금칙어/이슈어/비속어)

> 우측 상단 **설정** 메뉴(공지/코칭/설정 중) 클릭 → drawer 안에 **알림 / 키워드** 2개 탭. 본 절은 **키워드 탭** 분석.
> 진입: `HeaderActionBar`(설정 버튼) → emit `"adminSetting"` → `ContentLayout` → `AdminDrawerHost` → `AdminSetting.vue`.

### 5-0. 한 줄 요약
키워드 기능은 **3개 레이어**다. 백엔드로 가는 건 **키워드 "정의"(등록/삭제)** 뿐이고, **감지·카운트·마스킹은 전부 클라이언트 사이드**(STT 텍스트를 프론트가 직접 훑음).

```
[등록/관리]  AdminSetting.vue (설정▸키워드 탭)  ──CRUD──▶  /keyword-detects (백엔드 실연동)
                                                              │
[상태]       stores/modules/keywordDetect.ts  ◀──refresh──────┘
              · keywordList(전체) + keywordCategoryList(3종)
                                                              │
[소비/탐지]  STT 대화 텍스트를 프론트가 직접 탐지 ◀────────────┘
              ├ useTextRenderer.ts  → SpeechBubble: 대화 본문 마스킹
              ├ Keyword.vue         → "키워드" 드로어: 감지 키워드 카운트
              └ ChatAdminPanel.vue  → 관리자 모니터링 패널: 동일 카운트
```

### 5-1. 등록/관리 (CRUD) — `AdminSetting.vue` 키워드 탭
- **카테고리 3종**: 금칙어 `forbiddenWord` / 이슈어 `issueWord` / 비속어 `profanityWord` (store `:14~18`)
- **추가** `onAddKeyword`(`:340`) → `POST /keyword-detects` `{ keyword, type, creator_key }`, 201 시 목록 새로고침
- **삭제** `removeKeyword`(`:300`) → `DELETE /keyword-detects/{id}`, 200 시 새로고침
- drawer 열릴 때마다 `refreshKeywordDetect()`(`:196~201`)로 목록 재조회. 카테고리별 그룹핑해 `ECPTag` 표시.
- ⚠️ **이건 진짜 백엔드 연동임** (감정/VOC 하드코딩과 다름). 게이트웨이는 `path.ADVISOR` prefix.
- **수정(PATCH) 미사용**: `updateKeywordDetect` API는 있으나 UI 호출 없음 → 태그처럼 **등록/삭제만**. (의도된 단순화, 유지)

### 5-2. API / store
| 항목 | 위치 |
|---|---|
| API | `api/apis/keyword-detect.api.ts` — `getKeywordDetectList`/`create`/`update`/`delete` |
| 엔드포인트 | `{ADVISOR.API_PREFIX}/keyword-detects` (`path.ts`) |
| store | `stores/modules/keywordDetect.ts` |
- `refreshKeywordDetect`: 응답 `data[]` → `category = item.type`, **`isSystem = false` 고정**(`:32`).
- ⚠️ **`isSystem` 항상 false** → 태그의 시스템(primary/filled) 스타일은 절대 안 뜨고 전부 closable(삭제 가능). "시스템 키워드 보호" 개념은 사실상 죽어있음.
- 죽은 코드: `checkForForbiddenWords`/`checkForIssueWords`/`checkForProfanityWords`/`replaceKeywordsWithLabels` — 정의돼 있으나 **사용처 0**. 실제 탐지는 소비처가 자체 로직으로 함.

### 5-3. 소비/탐지 (STT 대화에 실제 적용)
**용도는 2가지** — 카테고리별로 적용 범위가 다름:

| 용도 | 어디서 | 금칙어 | 이슈어 | 비속어 |
|---|---|---|---|---|
| **(a) 본문 마스킹** (단어→카테고리 라벨 치환) | `useTextRenderer.ts` → `SpeechBubble` | ❌ **제외** | ✅ | ✅ |
| **(b) 감지 카운트** (모니터링 통계) | `Keyword.vue`, `ChatAdminPanel.vue` | ✅ | ✅ | ✅ |

- 둘 다 **`sender === "user"`(고객) 발화만** 대상.
- ⚠️ **금칙어는 본문 마스킹에서 제외됨** (`useTextRenderer:71~72`에서 패턴에서 빼버림) → SpeechBubble엔 **원문 그대로 노출**. `maskText`의 `forbiddenWord` 분기(`:142~143`)는 **도달 불가능한 죽은 코드**. → 의도(금칙어는 안 가림)인지 버그인지 **기획 확인 필요**.
- ⚠️ **DB에 안 쌓임**: 감지 카운트(`issueKeywords`)는 Vue `computed`로 **렌더 시마다 실시간 재계산**되는 일회성 통계. 저장 API 호출 없음. `assist-stream`(문서검색 RAG)과도 **무관**. → 누적 지표가 필요하면 **신규 구현 대상**.
- ⚠️ **비속어 시드 사전 없음**: 프론트에 대량 하드코딩/문서 없음 → 전부 설정탭 **수동 등록** 의존. (백엔드 시드 여부는 API 응답 확인 필요.)

### 5-4. 카운트 로직 공용화 (2026-06-29 리팩터 완료)
- 기존: `Keyword.vue`와 `ChatAdminPanel.vue`에 **동일한 `issueKeywords` 집계 로직이 복붙**돼 있었고, 한쪽(`ChatAdminPanel`)만 빈값가드가 있어 미묘하게 어긋남.
- 변경: store에 **공용 액션 `countIssueKeywords(chatContent): IssueKeywordCount[]`** 신설(빈값가드 포함 버전으로 통일). 두 컴포넌트의 computed를 이 액션 호출 한 줄로 교체. `Keyword.vue`의 디버깅 `console.log` 제거.
- `Keyword.vue`의 `props.chatContent || activeChatContent` 폴백은 컴포넌트단에 유지(결정된 배열만 액션에 전달).
- 동작 동일, 진단 에러 0. 이제 집계 규칙은 store 한 곳만 고치면 양쪽 일관.

### 5-5. 잔여 메모 (미수정, 추정 포함)
- `Keyword.vue` 제목은 "감지된 이슈어"인데 로직은 **금칙어/비속어/이슈어 전부** 카운트 → 제목 ↔ 내용 불일치.
- `Keyword.vue` 상단 위/아래 화살표 버튼은 `console.log('up'/'down')`만 — **미구현**.

---

## 6. 권한 체계

```
SYSTEM(5) > ADMIN(4) > NORMAL(3) > SUPERVISOR(2) > AGENT(1)
```
- 라우팅 가드(`router.beforeEach`) + 메뉴 권한(`authStore`)으로 접근 제어.
- 메뉴 정의는 현재 목업(`src/api/modules/menus/mockupMenuList.ts`) — 추후 타 시스템 연동 예정(인지됨).

---

## 7. 핵심 파일 맵

| 영역 | 파일 |
|---|---|
| 관리자 메인 | `src/view/advisor/admin/index.vue` |
| 진입점(역할분기) | `src/view/advisor/consultant/index.vue` |
| 상담사 목록 패널 | `src/view/advisor/components/ConsultantDrawer/index.vue` |
| 콜 이력 화면 | `src/view/advisor/components/CallHistoryView/index.vue` |
| 상담내용 모니터링 뷰(상담사 화면 재사용) | `src/view/advisor/components/chat/index.vue` |
| 코칭 모달(관리자) | `src/components/layout/Drawer/components/AdminCoaching/AdminCoaching.vue` |
| 코칭 요청 모달 | `src/components/layout/Drawer/components/CoachingRequest/CoachingRequest.vue` |
| 코칭 store | `src/stores/modules/coaching.ts` |
| 공지 | `src/components/layout/Drawer/components/Notice/{Notice,AddNotice}.vue` |
| 공지 store | `src/stores/modules/notice.ts` |
| 설정 drawer(알림/키워드 탭) | `src/components/layout/Drawer/components/AdminSetting/AdminSetting.vue` |
| 키워드 store(+공용 카운트 액션) | `src/stores/modules/keywordDetect.ts` |
| 키워드 API | `src/api/apis/keyword-detect.api.ts` |
| 키워드 마스킹(본문 렌더) | `src/view/advisor/components/composables/useTextRenderer.ts` |
| 키워드 감지 카운트(드로어/패널) | `src/components/layout/Drawer/components/Keyword/Keyword.vue`, `src/view/advisor/components/chat/ChatAdminPanel.vue` |
