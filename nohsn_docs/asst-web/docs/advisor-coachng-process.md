# 코칭 / 코칭요청 — 작업 핸드오프 (2026-06-30 업데이트)

> 이 문서만 주면 바로 이어서 작업. 코칭/코칭요청 관련만.
> **상태: 프론트 수정안 확정 직전(아래 6개 파일). 아직 코드 미반영 — 사용자가 급한 다른 일 처리하러 감. OK 받으면 바로 6개 작업 들어가면 됨.**

---

## 0. 가장 중요한 깨달음
- **코칭 리스트는 "관리자"와 "상담사" 둘 다 본다.** 화면이 각각 별도(여러 탭).
- 관리자 화면: `AdminCoaching.vue` / `AdminCoachingCard.vue` (상단 메뉴 배지)
- 상담사 화면: `CoachingRequest.vue` / `CoachingRequestCard.vue` (우측 LNB 배지)
- **두 흐름은 완전 대칭** — 채널 접미사 · `message.type` · 테이블만 다름.

---

## 1. 데이터 모델 — entity 2개 (방향 반대)

|  | ① 코칭 (coaching) | ② 코칭요청 (coaching_request) |
|---|---|---|
| 테이블 | `advisor.coachings` | `advisor.coaching_requests` |
| 누가 받나 | **상담사** (LNB 배지) | **관리자** (상단 메뉴 배지) |
| 누가 보내나 | 관리자/상담사 → 상담사 | 상담사 → 관리자 |
| `receiver_key` | 상담사 agent.id | 관리자 agent.id |
| `is_read` 의미 | 상담사가 읽었나 | 관리자가 읽었나 |
| `is_read` 타입 | ⚠️ **문자열** `"false"`/`"true"` | **boolean** `false`/`true` |

> ⚠️ is_read 타입 불일치 → 프론트 헬퍼로 흡수: `isRead(v) = v===true || String(v).toLowerCase()==="true"`

---

## 2. 백엔드 contract (확정 — 가이드 원문 기준)

### 생성 (보낼 때)
- 코칭/코칭요청 **생성 API만 호출**하면, 백엔드가 자동으로 수신자 채널에 실시간 트리거 발행.
- `receiver_key` = 받는 사람의 `agent.id`.

### 미확인 카운트 (배지)
| 대상 | 경로 | 응답 |
|---|---|---|
| 상담사(코칭) | `GET /coachings/receiver/{key}/unread-count` | `{ receiver_key, unread }` |
| 관리자(코칭요청) | `GET /coachings/requests/receiver/{key}/unread-count` ⭐신설 | `{ receiver_key, unread }` |

### 실시간 (소켓) — 표준 통일
- 구독 룸(채널 문자열 그대로 join):
  - 코칭: `${env}:${vendor_tenant_id}:${agentId}:coaching`
  - 코칭요청: `${env}:${vendor_tenant_id}:${agentId}:coaching_request`
- 이벤트는 **둘 다 `redis-message`**, `message.type`으로 분기:
  - `type==='coaching_created'`  → 상담사: 코칭 unread-count 재조회 → LNB 배지 (+토스트)
  - `type==='coaching_request_created'` → 관리자: 코칭요청 unread-count 재조회 → 상단 배지 (+토스트)
- 백엔드는 **트리거만**(카운트 숫자 안 실음) → 받으면 unread-count API 호출해서 갱신.
- `env` = dev(AWS개발)/localDev(로컬·사내5층), `vendor_tenant_id` = 회사 숫자값(예 4609686, ⚠️ company UUID 아님), `agentId` = 로그인 본인 agent.id.

### 읽음 처리 (단건만 지원)
| 대상 | 경로 |
|---|---|
| 상담사 | `PATCH /coachings/{coachId}/read` |
| 관리자 | `PATCH /coachings/requests/{coachrqId}/read` |
- 읽음 후 unread-count 재조회 → 배지 즉시 감소. (일괄 읽음 필요하면 백엔드에 별도 요청)

---

## 3. 현재 프론트 상태 (분석 결과)

### 상담사쪽 = 거의 완성 ✅
- `agent/index.vue setCoachingMessageListener`: 룸 `getRedisKey(tenant, agent.id,'coaching')` 직접 join + `on("redis-message")` + `type==='coaching_created'` 필터 → `refreshCoachings(false)`.
- 카운트: `coaching.ts refreshUnreadCount()`(`/coachings/receiver/{id}/unread-count`).
- `redisKey.ts`에 `coaching` 케이스 있음.

### 관리자쪽 = 틀렸거나 빠짐 ⛔ (이번에 고칠 대상)
- **(a) 카운트 의미 오류**: `AdminCoaching.vue:463`에서 `unReadCount = unansweredCount`(미답변 수) — "안 읽음"이 아님. 전용 API 안 씀.
- **(b) 전용 카운트 API 부재**: `coaching-request.api.ts`에 unread-count 없음.
- **(c) 소켓 패턴 불일치(아마 미수신)**: `admin/index.vue:409` 룸 `coaching_${id}`(포맷 다름) + 이벤트 `on("coaching_request")`/`on("coaching")` — 상담사 표준(redis-message + 채널 룸)과 다름.
- **(d) 읽음 처리 미연결**: `AdminCoaching.vue:587 handleConfirmed`는 로컬값만 바꾸고 API 호출 없음. emit 출처도 `종료된 콜` 버튼(`v-if="isCallEnded"` 항상 false)이라 사실상 호출 불가. 스토어 `onReadRequestCoaching`(`PATCH /coachings/requests/{id}/read`)는 정의만 되고 미사용.

### ⚠️ 공유 state 충돌
- `coachingStore.unReadCount` 하나를 상담사(미확인 코칭)/관리자(미답변 요청)가 다른 의미로 채움. 관리자쪽을 전용 API로 바꾸면 정리됨(한 세션 = 한 역할이라 OK).

---

## 4. 최종 수정 계획 (프론트 6개 파일) — 확정, 미반영

1. **`src/api/apis/coaching-request.api.ts`** — `getUnreadCoachingRequestCount(receiverKey)` 추가
   → `GET ${COACHING_REQUESTS}/receiver/{key}/unread-count` (= `/coachings/requests/receiver/{key}/unread-count`). 응답 `{ receiver_key, unread }`.
   - 참고: `COACHINGS=/coachings`, `COACHING_REQUESTS=/coachings/requests` (`src/api/config/path.ts:30-31`).
2. **`src/stores/modules/coaching.ts`**
   - `refreshRequestUnreadCount()` 액션 추가(위 API로 `unReadCount` 세팅) — 상담사 `refreshUnreadCount()`의 관리자판.
   - `refreshCoachings(isAdmin)`: 현재 `if(!isAdmin) await refreshUnreadCount()` → **`else await refreshRequestUnreadCount()`** 추가.
3. **`src/utils/redisKey.ts`** — `coaching_request` 케이스 추가
   `case "coaching_request": return `${CHANNEL_ENV}:${tenantId}:${agentId}:coaching_request`;`
4. **`src/view/advisor/admin/index.vue`** — `setCoachingMessageListener` 상담사 표준으로 교체
   - 룸: `coaching_${id}` ❌ → `getRedisKey(company.vendor_tenant_id, agent.id, "coaching_request")` ✅
   - 이벤트: `on("coaching_request")`/`on("coaching")` ❌ → `on("redis-message")` + 필터(채널 `:coaching_request` & `type==='coaching_request_created'` & `receiver_key===agent.id`)
   - 재연결 재참가(`on("connect")`), 수신 시 `refreshCoachings(true)`(배지 갱신 포함) + 기존 토스트 유지.
   - cleanup의 `off("coaching"...)/off("coaching_request"...)`도 정리.
5. **`src/components/.../AdminCoaching/AdminCoaching.vue`**
   - `coachingStore.unReadCount = unansweredCount`(463줄) **제거**(API 카운트 안 덮어쓰게).
   - `isRead()` 헬퍼 추가.
   - `handleConfirmed`를 **`await onReadRequestCoaching(id)` → `refreshCoachings(true)`** 로 변경.
   - 받은 요청 카드 데이터에 읽음용 값 추가(예: `isReadConfirmed: isRead(item.is_read)`). ⚠️ 기존 `isConfirmed`(="답변했나", "미답변" 탭이 씀)와 **분리**할 것.
6. **`src/components/.../AdminCoaching/AdminCoachingCard.vue`**
   - 상담사 카드(`CoachingRequestCard.vue:46-59`)처럼 하단에 **미확인/확인완료 버튼** 추가(받은 요청 한정 = `!isOnlyCoaching`). `@click.stop`(카드 클릭=editMode 토글이라 전파 막기). `isReadConfirmed` prop 신설로 구동.

### 대응표 (대칭)
| | 상담사(됨) | 관리자(추가) |
|---|---|---|
| 대상 | 받은 코칭(coach_) | 받은 코칭요청(coachrq_) |
| 읽음 API | `readCoaching` PATCH `/coachings/{id}/read` | `readCoachingRequest` PATCH `/coachings/requests/{id}/read` |
| 스토어 | `onReadCoaching` | `onReadRequestCoaching` (이미 있음) |
| 카운트 | `/coachings/receiver/{id}/unread-count` | `/coachings/requests/receiver/{id}/unread-count` (신설) |

---

## 5. ⚠️ 코드와 별개 — 동작 안 하면 의심할 것 (백엔드 가이드 경고)
1. **`receiver_key` == 그 사람 `agent.id` (동일 문자열)** — 제일 중요. 보낼 때 body의 `receiver_key`와, 그 사람이 화면에서 unread-count·실시간 구독에 쓰는 `agent.id`가 같아야 함. 다르면 `unread:0` + 실시간 미수신.
   - 현재 개발실 데이터 `receiver_key=agent_0c814a0e…` 인데 조회는 `agent_349727fe…` 로 들어와 `total:0` 나는 상태 → 같은 상담사인지부터 확인 필요.
2. **`vendor_tenant_id` 출처** = 프론트 `userProfileStore.company.vendor_tenant_id` (UUID 아님, 숫자). 실시간 채널·백엔드 둘 다 이 값.
3. **백엔드 재배포** 전엔 신규 API/채널 안 뜸.

---

## 6. 미해결 별건 (참고)
- **상담사 (3)**: "코칭요청" 리스트에서 미확인/확인완료가 여전히 확인완료로만 보인다는 리포트. 프론트 로직(`isRead()`)은 맞아 보여서 **백엔드 is_read 실제값(필드/기본값) 의심**. 위 데이터 키 불일치(5-1)와 연관일 수 있음. 데이터 정합 맞춘 뒤 재확인 필요.

> 작업 규칙: **소스 수정 전 항상 사용자 확정 받고 진행**(자동수정 금지). 분석은 asst-web 프로젝트 코드만(외부 docs repo 보지 말 것).
