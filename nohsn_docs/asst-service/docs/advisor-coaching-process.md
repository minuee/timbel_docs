# 상담 코칭(Coaching) 프로세스 정리

> 작성: 2026-06-30 (오늘 작업 기준). 내일 이어서 작업할 때 이 문서를 먼저 읽고 시작한다.
> 관련 히스토리: `CLAUDE-history.md` #76(초기 구현, tenant_id로 만들었다가 틀림) / #77(vendor_tenant_id 정정 + 미확인 카운트 API).

## 0. 한눈에 — 오늘 한 것 / 안 끝난 것

**오늘 완료(코드 반영, tsc·eslint 통과, develop 기준):**
- 코칭 생성 시 **받는 상담사 소켓 채널로 실시간 "코칭 생성" 이벤트 발행** (프론트 미확인 카운트 갱신 트리거)
- **미확인 코칭 카운트 전용 API 신설**: `GET /coachings/receiver/:receiverKey/unread-count`
- 실배포(개발실 `ecpad.etaas.co.kr`)에서 실시간 emit "1명 전송" 검증 + unread-count 동작 확인

**안 끝난 것(내일):**
1. **키 매칭** — 코칭 `receiver_key`(`agent_0c814a0e_...`)와 프론트 조회 `agent.id`(`agent_349727fe_...`)가 다름. 같은 상담사인지 확인하고 키 정렬.
2. **`is_read` 컬럼 타입** — 응답이 boolean이 아니라 문자열 `"false"`. 실 DB 컬럼이 varchar 의심. 정규화/transformer 검토.
3. **`created_at` 타임존**(별개, 보류) — KST 벽시계가 `...Z`(UTC)로 라벨링돼 나가 프론트 표시 어긋남.

---

## 1. 코칭이란 / 두 종류

관리자(또는 상담사)가 **다른 상담사에게** 통화에 대한 코칭 메시지를 보내는 기능. 두 종류:
- **코칭 요청(coaching_request)** — `advisor.coaching_requests` 테이블 / `coaching:request` 채널 / 이벤트 `coaching_request`
- **코칭(coaching)** — `advisor.coachings` 테이블 / `coaching:message` 채널 / **오늘 실시간·미확인카운트 작업 대상**

> 이번 작업은 **coaching(받은 코칭)** 쪽만 손댔다. coaching_request는 무수정.

## 2. 데이터 모델 (`advisor.coachings`)

엔티티: `src/advisor/coaching/entities/coaching.entity.ts`

| 컬럼 | 타입(엔티티) | 비고 |
|------|------------|------|
| `id` | varchar PK | `coach_{uuid}` |
| `call_id` | varchar | |
| `coaching_request_id` | varchar nullable | 빈 문자열로 오기도 함 |
| `sender_key` | varchar | 보낸 사람 agent id |
| `receiver_key` | varchar | **받는 상담사 agent.id — 채널/조회의 핵심 키** |
| `is_read` | **boolean**(엔티티) | ⚠️ 실 DB는 varchar 의심(응답이 `"false"` 문자열) |
| `is_important` | boolean | |
| `priority_type` | int | 0 일반 / 1 긴급 |
| `content` | text | |
| `sender_name`, `customer_name` | varchar nullable | |
| `created_at`, `updated_at` | timestamp(no tz) | ⚠️ 타임존 이슈(아래 6.3) |

## 3. 주요 파일 맵

| 역할 | 파일 |
|------|------|
| 컨트롤러(라우트) | `src/advisor/coaching/controllers/coaching.controller.ts` |
| 서비스(비즈니스) | `src/advisor/coaching/services/coaching.service.ts` |
| Redis 발행 | `src/advisor/coaching/services/coaching-redis.service.ts` |
| 소켓 핸들러(구독→emit) | `src/common/gateways/handlers/coaching-socket.handler.ts` |
| 상수(채널/이벤트명) | `src/common/constants/coaching.constants.ts` |
| 메시지 타입 | `src/common/types/coaching.types.ts` |
| query DTO(is_read 필터) | `src/advisor/coaching/dto/query-coaching.dto.ts` |

## 4. API 목록 (base: `/api/asst/v1`, 게이트웨이: `/aicc/asst-service`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/coachings` | 코칭 생성 (+실시간 발행 트리거) |
| POST | `/coachings/requests` | 코칭 요청 생성 |
| GET | `/coachings/call/:callId` | 통화별 코칭+요청 |
| GET | `/coachings/sender/:senderKey` | 발신자별 코칭 목록 |
| GET | `/coachings/receiver/:receiverKey` | **수신자별 코칭 목록** (`?is_read=false&page&limit`) |
| **GET** | **`/coachings/receiver/:receiverKey/unread-count`** | **★오늘 신설 — 미확인 개수** `{receiver_key, unread}` |
| GET | `/coachings/requests/sender/:senderKey` | 코칭요청 발신자별 |
| GET | `/coachings/requests/receiver/:receiverKey` | 코칭요청 수신자별 |
| PATCH | `/coachings/:id` , `/coachings/:id/read` | 수정 / 읽음처리 |
| DELETE | `/coachings/:id` | 삭제 |

> ⚠️ 라우트 순서: `unread-count`는 `receiver/:receiverKey`보다 **위에** 등록돼 있어야 가로채기 안 됨(현재 그렇게 돼 있음).

## 5. 실시간 알림 구조 (오늘 작업 핵심)

### 흐름
```
관리자 → POST /coachings (createCoaching)
  ├ DB 저장
  └ publishCoaching(coaching, vendorTenantId)               [coaching-redis.service.ts]
       → Redis publish 채널 'coaching:message'
            → CoachingSocketHandler.handleCoachingMessage (구독)   [coaching-socket.handler.ts]
                 → Socket.IO room 으로 emit
상담사 프론트 → 그 room 구독 + 'redis-message' 수신 → 미확인 카운트 API 재조회 → 화면 갱신
```

### 채널(room) 포맷 — ★가장 중요
```
${env}:${vendor_tenant_id}:${receiver_key}:coaching
예) dev:4609686:agent_0c814a0e_6fb4_44e1_92fd_b109a7cedd76:coaching
```
- `env` = `process.env.VOC_CHANNEL_ENV ?? 'dev'` (VOC 등 다른 채널과 **동일 소스**, NODE_ENV 의존 금지)
  - AWS개발=미설정→`dev`, 로컬/사내개발(5f)=`localDev`
- `vendor_tenant_id` = **`UserInfoService.getCurrentUser(token).company.vendor_tenant_id`** (예 `4609686`)
  - ⚠️ `tenant_id`(company UUID, `company_71900448_...`)가 **아님**. TenantConfig엔 vendor_tenant_id 없음 → UserInfo로만 얻음.
- `receiver_key` = 받는 상담사 `agent.id`

### 이벤트/페이로드 — 프론트 표준 `redis-message` 패턴
```js
socket.on('redis-message', (data) => {
  // data = { channel, message, timestamp }
  // data.message = {
  //   type: 'coaching_created',   // ← 이걸로 분기 (data.message.type)
  //   receiver_key, sender_key, coaching_id, call_id,
  //   coaching_request_id, is_important, priority_type, created_at
  // }
});
```
- 이벤트명 `redis-message`, 식별자 `message.type === 'coaching_created'`. (상수: `coaching.constants.ts`)
- 백엔드는 **트리거만** 보냄 — 카운트 숫자는 안 실음(프론트가 unread-count API 재조회).

## 6. 미해결 이슈 (내일 작업 대상)

### 6.1 키 매칭 (1순위)
- 코칭 48건 전부 `receiver_key = agent_0c814a0e_6fb4_44e1_92fd_b109a7cedd76`로 저장됨(개발실 DB 확인).
- 프론트 화면은 `receiver/agent_349727fe_659c_4c61_9669_40ad00a90067`로 조회 → `total:0`.
- 실시간도 채널이 `...:agent_0c814a0e_...:coaching`라, 상담사 화면이 `349727fe`로 구독했다면 미수신.
- **할 일**: 두 키가 같은 상담사인지 확인 →
  - 같으면: "관리자가 코칭 보낼 때 `POST /coachings` body의 `receiver_key`에 넣는 값" vs "상담사 화면 `agent.id`"를 일치시킨다. (백엔드가 키 정규화로 흡수할지, 프론트가 맞출지 결정)
  - 다르면: 단순 테스트 대상 착오(관리자가 `349727fe`에게 보내고 그 화면 보면 동작).
- 백엔드 조회/발행 로직 자체는 정상(양쪽 다 프론트가 보낸 값 그대로 사용).

### 6.2 `is_read` 컬럼 타입
- 응답에서 `is_read`가 boolean이 아닌 문자열 `"false"`. 엔티티는 `@Column({type:'boolean'})`인데 실 DB 컬럼이 varchar로 생성된 정황(배포 환경 `synchronize` off라 안 고쳐짐).
- 현재 `unread-count`는 `LOWER(c.is_read::text) IN ('false','f')`로 **타입 무관 카운트**(우회 완료).
- ⚠️ 단 목록 API `?is_read=false` 필터(`buildFilter` → `where.is_read = false` boolean)는 varchar 컬럼이면 깨질 수 있음 → **점검 필요**.
- **할 일**: `information_schema.columns`로 실타입 확인 →
  - varchar면: boolean 마이그레이션(`migrations/*.sql`, destructive라 수동) 또는 엔티티 `transformer`로 응답 boolean화 + 필터 보정.

### 6.3 `created_at` 타임존 (별개, 보류)
- `timestamp`(no tz) + 서버 `TZ=UTC` → DB의 KST 벽시계 값이 `...Z`(UTC 라벨) 붙어 나감 → 프론트 표시 어긋남(+9 해도 안 맞음).
- `started_at`(통화일시) 선례와 동일 패턴. 해결책: A) 백엔드가 `+09:00` offset으로 직렬화, B) 프론트가 Z 무시. (택1, 미결)

## 7. 배포/정책 메모
- 배포 브랜치 `develop` (NODE_ENV=development). **재배포(이미지 재빌드+롤아웃) 안 하면 옛 코드/캐시된 DataSource·소켓 그대로** → 코칭 코드 변경 후 반드시 재배포.
- 커밋/푸시는 사용자가 직접.
- 외부 호출(토큰 들고 curl)·DB 쿼리는 사용자가 직접 실행(클로드는 명령만 제공).
