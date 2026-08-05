# 콜 이벤트 → 상담사 상태 DB 기록 (`AgentStatusSyncService`)

> 목적: CTI 콜 이벤트를 백엔드가 직접 받아 `advisor.agents.status` 에 기록한다.
> 다른 레포(다른 서버 배포본)에 동일 작업을 이식하기 위한 문서.
> 기준 코드: `asst-service-portal` / NestJS. 아래 파일 경로·라인은 실제 소스 기준.

---

## 1. 배경 — 왜 필요한가

### 기존 흐름

상담사 상태는 `PUT /api/asst/v1/agents/status` 로만 DB 에 기록된다.
이 API 를 호출하는 주체가 **전부 브라우저**다.

```
CTI ──pub──▶ Redis `{env}:{tenant}:{cc_cti_id}:call:events`
                    │
                    ▼
        백엔드가 구독 → 소켓으로 중계만 함 (내용 해석 안 함)
                    │
                    ▼
        프론트가 수신 → type === 'start' 판정
                    │
                    ▼
        PUT /agents/status (ON_CALL)   ← 브라우저를 한 바퀴 돌고 되돌아옴
                    │
                    ▼
                  DB 기록
```

- 중계: `src/common/controllers/redis-monitor.controller.ts:413` `handleChannelMessage()`
- 프론트 해석: `asst-web-portal/src/view/advisor/components/chat/composables/useChatMessageParser.ts:185, 257`

### 문제

브라우저가 없으면 DB 에 아무것도 안 남는다. 브라우저 강제 종료·네트워크 단절·PC 셧다운이면
통화 상태가 유실된다. **백엔드는 이미 그 메시지를 손에 쥐고 있으면서 그냥 흘려보내고 있었다.**

### 변경 후

중계는 그대로 두고, 옵저버를 하나 붙여 **DB 기록만** 추가한다.

```
CTI ──pub──▶ Redis `:call:events`
                    │
                    ├─▶ 소켓 중계 (기존 그대로, 무변경)
                    │
                    └─▶ AgentStatusSyncService → advisor.agents.status UPDATE  ← 추가분
```

---

## 2. 변경 파일 (총 2개)

| 파일 | 변경 |
|---|---|
| `src/advisor/agent/services/agent-status-sync.service.ts` | **신규** |
| `src/advisor/advisor.module.ts` | +2줄 (import 1, providers 배열 1) |

**소켓 관련 파일은 한 줄도 건드리지 않는다.** (`socket.gateway.ts` 등)

---

## 3. 확장 지점 — 기존 옵저버 후크 재사용

새로 만들지 않았다. 이미 있는 후크에 등록만 한다.

```ts
// src/common/services/redis-monitor.service.ts:53
registerMessageObserver(observer: (channel: string, message: string) => void): void
```

```ts
// src/common/controllers/redis-monitor.controller.ts:440
// 중계(broadcast) '이후' 호출된다. 각 옵저버 예외는 개별 격리됨.
this.redisMonitorService.notifyMessageObservers(message.channel, message.message);
```

`RedisModule` 은 `@Global()` 이라(`src/common/redis.module.ts:8`) 어느 모듈에서든 주입 가능하고,
게이트웨이를 의존하지 않으므로 순환참조가 없다.

---

## 4. 입력 데이터 스펙

### 채널

```
{env}:{vendor_tenant_id}:{cc_cti_id}:call:events
예) dev:4609686:56356659:call:events
```

`:` 로 5조각. 2번째가 `vendor_tenant_id`, 3번째가 `cc_cti_id`.

### 페이로드 (JSON)

| 필드 | 설명 |
|---|---|
| `type` | `start` = 통화 시작, 그 외 = 통화 종료 |
| `agent_id` / `agentId` | **값은 cc_cti_id 다** (아래 함정 참고) |
| `call_id` / `callId` | 통화 ID |
| `customerNum` / `customer_num` | 고객 번호 |

### 상태 매핑

프론트(`useChatMessageParser.ts:185, 257`)와 동일 규칙을 쓴다.

| `type` | `AgentStatus` |
|---|---|
| `start` | `ON_CALL` |
| 그 외 | `AFTER_CALL` |

`AgentStatus` 전체 5종: `NOT_WORKING` / `WAITING` / `ON_CALL` / `AFTER_CALL` / `BREAK`
(`src/advisor/agent/enums/agent-status.enum.ts`)

---

## 5. 설계 판단 — 이식 시 그대로 지킬 것

### 5-1. 소켓 브로드캐스트를 하지 않는다

DB 기록만 하고 `broadcastToAgentStatusRoom()` 을 호출하지 않는다.

이유: **화면은 이미 같은 `:call:events` 를 직접 받아 갱신하고 있다.**

- 상담사 화면 / 관리자 화면 모두 `useChatMessageParser` 가 `:call:events` 를 파싱해 `_agentStatus` 갱신
- 관리자 화면은 `agent-status` 룸도 이미 구독 중
  (`asst-web-portal/src/view/advisor/admin/index.vue:228-231`)

여기서 또 브로드캐스트하면 **같은 정보가 두 경로로 들어가는 중복**만 생긴다.

### 5-2. INSERT 하지 않는다 (UPDATE 전용)

행이 없으면 그냥 스킵한다. 이유 두 가지.

**(1) 채울 정보가 없다.** 콜 이벤트로 알 수 있는 건 `cc_cti_id` 와 `status` 뿐이다.
`name`·`workspace_id`·`bot_id`·`email`·`extension` 전부 알 수 없어 null 행이 된다.

**(2) ⚠️ `agent_id` 함정.** 메시지의 `agent_id` 필드는 **이름만 그렇고 실제 값은 cc_cti_id** 다.
그대로 `agent_id` 컬럼에 넣으면 잘못된 값이 박힌다.

```
AWS 실제 데이터
  cc_cti_id = 56356659
  agent_id  = agent_1916296e_48ba_4408_9a39_78cf5d13d199   ← 완전히 다른 값
```

행은 상담사가 포털에 들어올 때 `PUT /agents/status` 가 온전한 정보로 만든다(upsert).
그 UPDATE 경로는 전달된 필드만 갱신하므로(`agent.service.ts:261~`) 빈 칸은 나중에 메워진다.

### 5-3. 절대 throw 하지 않는다

이 옵저버는 **STT/VOC 가 흐르는 Redis 중계 파이프라인 위에서 실행된다.**
여기서 예외가 새면 실시간 기능 전체가 영향을 받는다. 모든 경로에서 예외를 삼킨다.

### 5-4. ⚠️ 공용 Redis 주의 (전례 있음)

3개 서버(AWS/5F/106)가 **같은 Redis 를 본다.**
과거 `VocRealtimeService` 가 상시 옵저버를 걸었다가 남의 트래픽까지 받아 제거된 전례가 있다.

> `src/advisor/assist-stream/services/voc-realtime.service.ts:118`
> "과거의 상시 Redis nlp:complete 옵저버 등록(onModuleInit)은 제거됨 — 그 방식은 HTTP 경로와
> 무관하게 공용 Redis 의 모든 통화 발화를 받아 VOC 를 돌려서, 수동 검색 중에도 VOC 가 도는 문제가 있었다."

본 서비스가 안전한 이유:
1. 구독 자체가 클라이언트 요청 기반(`POST /redis-monitor/subscribe/:channel`)이라 자기 서버 클라이언트가 요청한 채널만 본다
2. **UPDATE 전용**이라 자기 DB 에 없는 상담사는 자연히 걸러진다

**이식할 때 2번을 INSERT 로 바꾸면 이 방어가 무너진다.**

### 5-5. ⚠️ `AgentStatus` enum 과 직접 비교하지 않는다 (pre-commit 훅에서 걸림)

`Agent` 엔티티의 `status` 는 **enum 이 아니라 `string`** 으로 선언돼 있다.

```ts
// src/advisor/agent/entities/agent.entity.ts:47
@Column({ type: 'varchar', length: 64, default: AgentStatus.NOT_WORKING })
status: string;
```

그래서 `AgentStatus` 와 직접 비교하면 eslint 에러가 난다. **husky pre-commit 훅에서 커밋이 막힌다.**

```
error  The two values in this comparison do not have a shared enum type
       @typescript-eslint/no-unsafe-enum-comparison
```

❌ 걸리는 코드
```ts
if (agent.status === status) { ... }   // string vs AgentStatus
agent.status = status;
```

✅ enum 값을 `string` 으로 한 번 받아서 쓴다
```ts
const nextStatus: string = status;
if (agent.status === nextStatus) { ... }
agent.status = nextStatus;
```

런타임 동작은 동일하다 — `AgentStatus.ON_CALL` 의 값이 문자열 `'ON_CALL'` 이라 비교 결과가 바뀌지 않는다.

> 다른 레포도 엔티티가 같은 형태(`status: string`)면 동일하게 걸린다.
> eslint 설정이 다르면 안 걸릴 수도 있으나, 위 방식이 어느 쪽에서도 안전하다.

---

## 6. DB 접근 — 토큰 없는 백그라운드 경로

옵저버 콜백에는 HTTP 토큰이 없다. `AgentService.getRepository(token)` 은 토큰 필수라 쓸 수 없다
(`src/advisor/agent/services/agent.service.ts:48` — 토큰 없으면 `NotFoundException`).

대신 토큰 없이 접속하는 전용 메서드를 쓴다.

```ts
// src/common/services/dynamic-database.service.ts:276
async getConnectionByVendor(vendorTenantId?: string): Promise<DataSource | null>
```

동작:
- `DB_DIRECT_CON=1` → 정적 연결 반환 (106 등 단일 테넌트 환경)
- 그 외 → `vendorMeta` 캐시의 연결문자열로 재접속. 캐시 미스면 `null` (그냥 스킵)

대상 테이블: `advisor.agents` (`src/advisor/agent/entities/agent.entity.ts:16`)

---

## 7. 이식 절차 (다른 레포)

### 7-1. 사전 확인 — 아래가 없으면 먼저 준비해야 한다

| 확인 항목 | 위치 |
|---|---|
| `RedisMonitorService.registerMessageObserver` 존재 | `src/common/services/redis-monitor.service.ts` |
| `notifyMessageObservers` 가 중계 시 호출됨 | `src/common/controllers/redis-monitor.controller.ts` |
| `DynamicDatabaseService.getConnectionByVendor` 존재 | `src/common/services/dynamic-database.service.ts` |
| `Agent` 엔티티 / `advisor.agents` 테이블 | `src/advisor/agent/entities/agent.entity.ts` |
| `AgentStatus` enum | `src/advisor/agent/enums/agent-status.enum.ts` |
| 채널 네이밍이 `{env}:{vendor}:{cc_cti_id}:call:events` 인지 | 운영 Redis 확인 |

**채널 형식이 다르면 `parseChannel()` 의 `CHANNEL_SEGMENTS`(5)와 인덱스를 반드시 조정할 것.**

### 7-2. 적용

1. `src/advisor/agent/services/agent-status-sync.service.ts` 복사
2. `advisor.module.ts` 에 2줄 추가
   ```ts
   import { AgentStatusSyncService } from '@app/advisor/agent/services/agent-status-sync.service';
   // providers 배열에
   AgentStatusSyncService,
   ```
3. 커밋 전 아래 둘 다 통과 확인 (pre-commit 훅이 eslint 를 돌린다)
   ```bash
   npx tsc --noEmit -p tsconfig.json
   npx eslint src/advisor/agent/services/agent-status-sync.service.ts
   ```
   eslint 에서 `no-unsafe-enum-comparison` 이 나면 **5-5** 참고.

---

## 8. 검증

### 기동 로그

```
[AgentStatusSyncService] 콜 이벤트 → 상담사 상태 기록 옵저버 등록 완료
```

### 통화 시작/종료 시

```
📞 [콜 이벤트] 상담사 상태 기록: cc_cti_id=56356659, status=ON_CALL
📞 [콜 이벤트] 상담사 상태 기록: cc_cti_id=56356659, status=AFTER_CALL
```

### DB 직접 확인

```sql
SELECT cc_cti_id, status, updated_at FROM advisor.agents WHERE cc_cti_id = '56356659';
```

### 로그가 안 찍힐 때 (전부 `debug` 레벨)

| 로그 | 원인 |
|---|---|
| `채널 형식 불일치 → 스킵` | 채널 세그먼트가 5개가 아님 → `CHANNEL_SEGMENTS` 조정 필요 |
| `미등록 상담사 → 스킵(INSERT 안 함)` | 그 `cc_cti_id` 행이 DB 에 없음 (정상 동작) |
| `DB 연결 없음 → 스킵` | `getConnectionByVendor` 가 null — vendor 캐시 미스 or `DB_DIRECT_CON` 미설정 |
| 아무것도 없음 | 해당 채널을 애초에 구독하지 않은 상태 |

---

## 9. 롤백

```
1. src/advisor/agent/services/agent-status-sync.service.ts 삭제
2. advisor.module.ts 에서 추가한 2줄 제거
```

순수 추가분이라 이걸로 완전히 원상 복구된다. 다른 파일에 흔적이 없다.

---

## 10. 알려진 한계 (이 작업 범위 밖)

| 항목 | 내용 |
|---|---|
| 담당 상태 | `ON_CALL` / `AFTER_CALL` 만 기록. `WAITING`·`BREAK` 는 상담사 수동 조작(`PUT /status`), `NOT_WORKING` 은 브라우저 종료 시 beacon 에 의존 |
| beacon 유실 | `navigator.sendBeacon` 은 fire-and-forget 이라 강제 종료 시 `NOT_WORKING` 이 유실될 수 있음 → DB 에 `BREAK` 등이 영구히 남을 수 있음 |
| 만료 개념 없음 | `advisor.agents` 에 TTL 이 없다. 화면에서 읽을 때 `updated_at` 기준으로 stale 판정 필요 |
| 서버 간 미공유 | 3개 서버가 각자 DB 를 쓰므로 같은 `cc_cti_id` 라도 서버별 상태가 다르다 (Redis 로 공유되는 STT 와 다름) |

---

## 부록 — 상태 기록 주체 정리

현재 시점 기준.

| 상태 | 기록 주체 | 경로 |
|---|---|---|
| `ON_CALL` / `AFTER_CALL` | **백엔드 (본 작업)** | `:call:events` → `AgentStatusSyncService` |
| `WAITING` / `BREAK` | 상담사 조작 | 프론트 → `PUT /agents/status` |
| `NOT_WORKING` | 브라우저 종료 | 프론트 beacon → `POST /agents/status/beacon` |
