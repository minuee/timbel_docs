# asst-service-portal 백엔드 — Socket.IO ↔ Redis Pub/Sub 실시간 통신 아키텍처

> 목적: 프론트/백엔드 공용으로 실시간 통신(WebSocket + Redis Pub/Sub) 구조를 다이어그램(draw.io/PPT)으로 그리기 위한 백엔드 정리 문서.
> 기준 코드: NestJS (`socket.io` 서버 + `redis` 클라이언트). 아래 파일 경로/라인은 실제 소스 기준.

### 스택 버전
- `socket.io` `4.8.1`, `@nestjs/platform-socket.io` / `@nestjs/websockets` `11.1.6`
- `redis` `4.7.1` (**node-redis v4**, `ioredis` 아님)
- Redis는 **애플리케이션 pub/sub 버스 + KV 저장소**로만 사용. `@socket.io/redis-adapter`(소켓 수평확장 어댑터) **미사용** → 기본 in-memory 어댑터.
- 패턴 구독(`psubscribe`) 없음. 명시적 채널 `SUBSCRIBE`만 사용.

---

## 0. 한눈에 보는 전체 구조 (다이어그램 뼈대)

```
[외부 발행자]                 [asst-service 백엔드 (NestJS)]                    [프론트엔드 클라이언트]
                        ┌───────────────────────────────────────────┐
 STT/NLP 서비스 ──pub──▶│  RedisService (subscriber client)          │
 (call:nlp:complete 등) │    - redis 'subscriber' 커넥션 (구독 전용)   │
                        │    - redis 'client'   커넥션 (pub/기타 명령) │
 다른 asst 인스턴스 ─pub─▶│                                            │
                        │        │ (message 이벤트: channel, payload) │
                        │        ▼                                    │
                        │  채널별 콜백 라우팅                          │
                        │   ├ coaching:request → CoachingSocketHandler│
                        │   ├ coaching:message → CoachingSocketHandler│
                        │   └ (동적) *:call:voc, *:call:nlp:* 등       │
                        │        → RedisMonitorController              │
                        │        ▼                                    │
                        │  SocketGateway (socket.io Server)           │
                        │   - server.to(room).emit('redis-message')   │──ws──▶ room 구독 클라이언트
                        │   - 'redis-message' / 'notice' / ...         │
                        └───────────────────────────────────────────┘
                                    ▲                                          │
                                    │  @SubscribeMessage('join-room' 등)        │
                                    └──────────────ws(inbound)─────────────────┘
```

핵심 3줄 요약:
1. **수신(Redis→FE)**: 외부/내부가 Redis 채널에 `publish` → 백엔드 `RedisService.subscriber`가 수신 → 채널명과 동일한 이름의 **Socket.IO room**으로 `emit` → 그 room에 `join`한 프론트가 수신.
2. **room = Redis 채널명**: 프론트는 소켓 연결 후 `join-room`으로 자기 채널(room)에 입장, 백엔드는 해당 room에 브로드캐스트.
3. **표준 이벤트 = `redis-message`**, 표준 payload = `{ channel, message, timestamp }`.

---

## 1. Socket.IO 서버 설정 (Gateway)

파일: `src/common/gateways/socket.gateway.ts` — `@WebSocketGateway`

| 항목 | 값 |
|---|---|
| path | `/api/asst/v1/socket.io` (글로벌 prefix와 일치. 게이트웨이 경유 시 클라 path `/aicc/asst-service/socket.io` → StripPrefix=2 + PrefixPath `/api/asst/v1`) |
| transports | `['websocket', 'polling']` |
| CORS | 비프로덕션: 모두 허용(`true`) / 프로덕션: `CORS_ALLOWED_ORIGINS`(콤마구분) |
| credentials | `true`, methods `GET, POST` |
| secure(WSS) | `SOCKET_SECURE !== '0'` (기본 WSS, `=0`이면 WS) |
| allowEIO3 | `true` (구버전 클라 호환) |
| connectionStateRecovery | `maxDisconnectionDuration: 2분`, `skipMiddlewares: true` — 재연결 시 room/미수신 메시지 복원 |
| ping | `pingTimeout: 60000`, `pingInterval: 25000`, `upgradeTimeout: 30000` |
| 어댑터 | **기본 in-memory 어댑터** (Redis adapter 미사용) → 멀티 파드 배포 시 **sticky session 필수** (코드 내 K8s/ALB 경고 로직 있음) |

> ⚠️ 아키텍처 상 중요: socket.io는 `@socket.io/redis-adapter`를 쓰지 않음. Redis는 "메시지 소스(pub/sub)"로만 쓰이고, 소켓 세션 공유용이 아님. 그래서 멀티 인스턴스에서 특정 유저 room은 그 유저가 붙은 파드에만 존재 → sticky session 전제.

---

## 2. Redis 연결 구조 (RedisService)

파일: `src/common/services/redis.service.ts`, 설정: `src/config/redis.config.ts`

- 라이브러리: `redis` (node-redis v4, `createClient`)
- **커넥션 2개 분리** (pub/sub 표준 패턴):
  - `client` — publish 및 일반 명령(HGETALL/ZRANGE/HSET/SET NX 등)
  - `subscriber` — 채널 구독 전용 (`subscriber.on('message', ...)`)
- 구독 관리: `subscriptions: Map<channel, {callback, isActive}>` — 채널→콜백 라우팅 테이블
- 자가 복원 기능:
  - 무한 `reconnectStrategy` (NLB idle drop 대비)
  - 주기적 헬스체크(`REDIS_HEALTH_CHECK_INTERVAL`, 기본 180초) — `PING`+타임아웃(5초)으로 half-open 감지 → 자동 `reconnect()` + **기존 구독 자동 복구**
- 연결 실패해도 앱은 계속 구동(Redis 기능만 비활성)

### Redis 접속 환경변수
| 변수 | 기본값 | 용도 |
|---|---|---|
| `REDIS_HOST` | `localhost` | 호스트 |
| `REDIS_PORT` | `6379` | 포트 |
| `REDIS_PASSWORD` | (없음) | 비밀번호 |
| `REDIS_DB` | `0` | DB 인덱스 |
| `REDIS_TLS` | `false` | TLS 사용(`true`/`1`) |
| `REDIS_HEALTH_CHECK_INTERVAL` | `180000`(ms) | 헬스체크/keepalive 주기 |

---

## 3. Gateway ↔ Redis 초기화 순서 (중요 타이밍)

`SocketGateway.afterInit()` (socket.gateway.ts:79) 흐름:
1. socket.io Server 초기화 로그
2. 각 핸들러에 `server` 인스턴스 주입 (`coaching/notice/agentStatus Handler.setServer`)
3. 주기적 통계 태스크 시작(5분마다 연결/room 통계 로그)
4. **`setTimeout(2000ms)` 후** `initializeRedisSubscription()` 실행 (RedisService 초기화 완료 대기)
   - `moduleRef.get(RedisService)` 지연 주입 (순환 의존성 회피)
   - Redis 연결될 때까지 최대 10초(500ms×20) 폴링
   - `redisService.setSocketGateway(this)` (역참조 연결)
   - `coachingHandler.subscribeToChannels()` 호출 → 코칭 채널 구독 시작

> 순환 의존성 회피: `SocketGateway` ↔ `RedisService`가 서로를 참조하므로, RedisService는 `any` 타입으로 gateway를 지연 보관(`setSocketGateway`).

---

## 4. 실시간 도메인별 흐름 (다이어그램에서 각각 하나의 플로우로)

### 4-A. 코칭 / 코칭요청 (Redis subscribe → Socket emit)

- **발행측(백엔드 내부)**: `src/advisor/coaching/services/coaching-redis.service.ts`
  - `publishCoachingRequest()` → Redis 채널 **`coaching:request`** 에 publish
  - `publishCoaching()` → Redis 채널 **`coaching:message`** 에 publish
  - payload(JSON): `{ type, payload: <엔티티>, vendor_tenant_id }`
- **수신/중계**: `src/common/gateways/handlers/coaching-socket.handler.ts`
  - `subscribeToChannels()`가 위 2개 채널 구독
  - 수신 시 프론트 구독용 **room 이름을 재조립**:
    - 코칭요청: `${env}:${vendor_tenant_id}:${receiver_key}:coaching_request`
    - 코칭: `${env}:${vendor_tenant_id}:${receiver_key}:coaching`
    - `env` = `VOC_CHANNEL_ENV ?? 'dev'` (모든 실시간 채널 공통 prefix)
    - ⚠️ tenant 세그먼트는 회사 UUID가 아니라 **`vendor_tenant_id`**(예: 4609686) — 프론트/VOC와 반드시 일치해야 수신됨
  - `server.to(room).emit('redis-message', { channel, message, timestamp })`
  - `message.type`: `coaching_request_created` / `coaching_created` (프론트가 이 타입으로 미확인 카운트 재조회)

```
[코칭 서비스] --publish 'coaching:message'--> [Redis]
   --subscriber--> [CoachingSocketHandler]
   --emit 'redis-message' to room "dev:{vendor}:{receiver_key}:coaching"--> [프론트]
```

상수 정의: `src/common/constants/coaching.constants.ts`
- 채널: `coaching:request`, `coaching:message`
- 이벤트: `redis-message`
- message.type: `coaching_created`, `coaching_request_created`

> ⚠️ **현재 상태(코드 주석 기준)**: 과거 상시 `nlp:complete` 옵저버 등록은 **제거됨**. `handleNlpComplete`는 남아있으나 미사용이며, 실시간 VOC는 현재 HTTP `/assist-stream` 경로(`handleUtterance`)에서만 동작. `RedisMonitorService`의 옵저버 훅은 존재하나 활성 등록자 없음. (다이어그램에는 "설계상 경로"와 "현재 실동작 경로"를 구분해 표기하면 좋음)

### 4-B. 실시간 VOC (감정/민원위험/이탈징후) — 가장 복잡

파일: `src/advisor/assist-stream/services/voc-realtime.service.ts`

- **이벤트 소스**: STT/NLP 서비스가 발화 확정 시 Redis 채널 `${env}:${vendor}:${cc_cti}:call:nlp:complete` 에 발행
- 백엔드는 그 nlp 채널을 이미 구독(소켓 중계 중) → `RedisMonitorService` 옵저버로 **무간섭 훅킹**하여 VOC 서비스가 발화 누적
- 게이트(2턴째 첫 발동 + 이후 N턴마다, `REALTIME_VOC_INTERVAL`)를 통과할 때만 LLM 분석(비용 억제)
- 분석 결과를 nlp 채널명에서 도출한 **`...:call:voc`** 채널로 다시 `publish`
  - 예: `dev:4609686:56356659:call:nlp:complete` → `dev:4609686:56356659:call:voc`
  - payload: `{ agent_id(=cc_cti_id), call_id, turn_idx, emotion, complaintRisk, churnRisk }`
- 그 voc 채널을 다시 소켓 브리지가 room으로 emit → 프론트 수신
- 분산 중복방지: `SET NX EX 60` 락(`voc:dedupe:{env}:{callId}:{turnIdx}`)으로 다중 인스턴스 중 1대만 분석/발행
- 결과는 `callstat_voc` 테이블에 best-effort upsert(토큰 만료에 견고한 다단계 연결 폴백)

```
[STT/NLP] --pub :call:nlp:complete--> [Redis] --sub--> [RedisMonitorController.handleChannelMessage]
   --(관찰)--> [VocRealtimeService: 누적→게이트→LLM분석]
   --pub :call:voc--> [Redis] --sub--> [소켓 브리지] --emit 'redis-message' to room--> [프론트]
```

### 4-C. 범용 Redis 모니터 브리지 (동적 채널)

파일: `src/common/controllers/redis-monitor.controller.ts`

- REST로 임의 채널 구독/해제 제어:
  - `POST /redis-monitor/subscribe/:channel` → `RedisService.subscribe` + 동명 Socket room 생성
  - `DELETE /redis-monitor/unsubscribe/:channel`, `DELETE /redis-monitor/unsubscribe-all`
  - `GET /redis-monitor/channels`, `GET /redis-monitor/status`
- 수신 콜백 `handleChannelMessage()`:
  - `socketGateway.broadcastToRedisMonitorRoom(channel, { channel, message, timestamp, source:'redis' })`
  - → `server.to(channel).emit('redis-message', ...)`
  - 이후 `redisMonitorService.notifyMessageObservers()`로 VOC 등 옵저버 통지
- 즉, **채널명 == room명**으로 그대로 흘려보내는 범용 통로. VOC의 `:call:voc`, `:call:nlp:*` 등이 이 경로로 프론트에 전달됨.

### 4-D. 상담사 상태 (agent-status) — Socket 직접 emit (Redis 미경유)

파일: `src/advisor/agent/services/agent.service.ts:292` → `src/common/gateways/handlers/agent-status-socket.handler.ts`

- 트리거: 상담사 상태 변경 서비스 로직에서 `socketGateway.broadcastToAgentStatusRoom(msg)` 직접 호출
- 고정 room: **`agent-status`**
- 이벤트: `agent-status-update`
- payload: `{ cc_cti_id, agent_id?, status, timestamp }`

### 4-E. 공지사항 (notice) — Socket 직접 emit (Redis 미경유)

파일: `src/advisor/notice/services/notice.service.ts:55` → `src/common/gateways/handlers/notice-socket.handler.ts`

- 트리거: 공지 저장 시 `socketGateway.broadcastNotice(notice)` 직접 호출
- 고정 room: **`notices`**
- 이벤트: `notice-broadcast` **및** `notice` (호환성 위해 2개 동시 emit)
- payload: `{ type: NOTICE, message: <NoticeSocketMessage> }`

---

## 5. Socket 이벤트 카탈로그

### 5-1. Inbound (클라이언트 → 서버, `@SubscribeMessage`)
| 이벤트 | 본문 | 처리 |
|---|---|---|
| `join-room` | `roomName: string` | 해당 room 입장 + Redis 모니터 room 생성, `join-room-success`/`join-room-error` 응답 |
| `leave-room` | `roomName: string` | room 퇴장, `leave-room-success`, 다른 참여자에 `room-member-left` |
| `notice` | `SocketMessage<NoticeSocketMessage>` | `notice-response` 응답 |
| `message` | `SocketMessage` | `type`별 분기(현재 NOTICE만), 미지원 시 `error` |

### 5-2. Outbound (서버 → 클라이언트, `emit`)
| 이벤트 | 대상 | payload | 발생 위치 |
|---|---|---|---|
| `connection-confirmed` | 접속 소켓 | `{ message, clientId, timestamp }` | handleConnection |
| `redis-message` | room | `{ channel, message, timestamp }` | 코칭/VOC/범용 브리지 (**핵심 표준 이벤트**) |
| `agent-status-update` | `agent-status` room | `{ cc_cti_id, agent_id, status, timestamp }` | agent-status handler |
| `notice-broadcast` / `notice` | `notices` room | `{ type, message }` | notice handler |
| `join-room-success` / `join-room-error` | 요청 소켓 | 상태 객체 | join-room |
| `leave-room-success` / `leave-room-error` / `room-member-left` | 소켓/room | 상태 객체 | leave-room |
| `notice-response` | 요청 소켓 | `{ type, message }` | notice 핸들러 |
| `personal-message` | userId room | `SocketMessage` | sendToUser(확장용) |
| `error` | 소켓 | `{ message }` | 알 수 없는 메시지 |

---

## 6. Redis 채널 카탈로그

| 채널(패턴) | 방향 | 발행자 | 구독자/처리 | → Socket room / event |
|---|---|---|---|---|
| `coaching:request` | in | CoachingRedisService | CoachingSocketHandler | `{env}:{vendor}:{receiver}:coaching_request` / `redis-message` |
| `coaching:message` | in | CoachingRedisService | CoachingSocketHandler | `{env}:{vendor}:{receiver}:coaching` / `redis-message` |
| `{env}:{vendor}:{cc_cti}:call:nlp:complete` | in | 외부 STT/NLP | RedisMonitor + VocRealtime 관찰 | 동명 room / `redis-message` |
| `{env}:{vendor}:{cc_cti}:call:voc` | out→in | VocRealtimeService | RedisMonitor 브리지 | 동명 room / `redis-message` |
| (동적 임의 채널) | in | 외부/운영 | `POST /redis-monitor/subscribe/:channel`로 구독 | 동명 room / `redis-message` |
| `{env}:wav_sim:cmd` | out | WavSimController | 외부 호스트 스크립트(리포 밖) | (pub/sub, 소켓 미경유) |
| `voc:dedupe:{env}:{callId}:{turnIdx}` | — | VocRealtime (SET NX) | (락 전용, pub/sub 아님) | — |

- 구독 방식 2가지 공존: **정적**(코칭 2채널, gateway init 시) + **동적 HTTP 구동**(`/redis-monitor/subscribe/:channel`)

- `env` = `VOC_CHANNEL_ENV ?? 'dev'` — **모든 실시간 채널 공통 prefix** (NODE_ENV와 무관, 기본 `dev`)
- tenant 세그먼트 = **`vendor_tenant_id`** (회사 UUID 아님)

---

## 7. Room 키 규칙 (프론트 join 대상)

| 도메인 | room 이름 | 비고 |
|---|---|---|
| 코칭 | `{env}:{vendor_tenant_id}:{receiver_key}:coaching` | 수신자별 |
| 코칭요청 | `{env}:{vendor_tenant_id}:{receiver_key}:coaching_request` | 수신자별 |
| VOC | `{env}:{vendor_tenant_id}:{cc_cti_id}:call:voc` | 상담사(cc_cti)별 |
| 상담사 상태 | `agent-status` | 전역 고정 |
| 공지 | `notices` | 전역 고정 |

프론트 절차: 소켓 연결 → `connection-confirmed` 수신 → 필요한 room마다 `emit('join-room', roomName)` → `redis-message`(또는 도메인 이벤트) 수신 → payload의 `message.type`으로 분기.

---

## 7-1. 인증/인가 (다이어그램 주석 필수)

- **소켓 계층에 인증 없음**: `handleConnection`에 JWT/토큰 검증 없음. 소켓용 `@UseGuards`·미들웨어(`server.use`)·핸드셰이크 auth 파싱 **전무**.
- 결과적으로 엔드포인트에 도달 가능한 클라이언트는 누구나 연결 후 임의 room(`join-room`)에 입장 가능. 사실상 "**room 이름(=`env:vendor_tenant_id:receiver_key:type`)을 아는 것**"이 접근 통제.
- 참고: `AuthMiddleware`/`AdminGuard`는 존재하지만 **HTTP 전용**이며 소켓에 적용 안 됨.

## 7-2. Redis의 또 다른 용도 — 순수 데이터 저장소 (pub/sub 아님)

동일 Redis가 pub/sub 외에 KV/Hash/SortedSet 저장소로도 사용됨. 다이어그램에서 "Redis" 박스의 역할을 나눠 표기하면 정확함.

| 용도 | 키/명령 | 위치 |
|---|---|---|
| 오디오 스트림 티켓(단명) | `audio:ticket:{uuid}` `SET EX 300` / `GET` | audio-proxy.controller.ts |
| 상담사 콜 설정 | `{env}:{vendor}:{agent}:call:setting` `HSET`/`HGETALL` | agent-call-setting.service.ts |
| STT 턴 데이터 | `dev:call:{callId}:turn:data` `ZRANGE` (turn_idx 정렬) | advisor.service.ts:810 |
| VOC dedupe 락 | `voc:dedupe:{env}:{callId}:{turnIdx}` `SET NX EX 60` | voc-realtime.service.ts:450 |
| WAV 시뮬레이터 제어 | `{env}:wav_sim:cmd`(pub) / `{env}:wav_sim:state` / `{env}:wav_sim:log` | wav-sim.controller.ts (테스트 도구) |

## 8. 배포/운영 상 주의 (다이어그램 주석용)

- **Sticky Session 필수**: socket.io Redis adapter 미사용(in-memory) → 유저 room은 접속 파드에만 존재. K8s/ALB에서 `stickiness.enabled=true` 필요(코드에 경고 로그 존재).
- **Redis 단일 소스**: 여러 환경/인스턴스가 같은 Redis 공유 가능 → `env` prefix와 dedupe 락 키로 환경 격리.
- **자가 치유**: Redis 끊김 감지 시 자동 재연결 + 구독 자동 복구(헬스체크 180초).
- **재연결 복원**: `connectionStateRecovery`(2분) — 같은 파드 재연결 시 room/미수신 복원.

---

### 관련 환경변수 (이름만)
- 소켓/CORS: `SOCKET_SECURE`, `CORS_ALLOWED_ORIGINS`, `HTTPS_ENABLED`, `PORT`, `HOST`, `KUBERNETES_SERVICE_HOST`
- Redis 접속: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`, `REDIS_TLS`, `REDIS_HEALTH_CHECK_INTERVAL`
- 채널/VOC: `VOC_CHANNEL_ENV`(모든 실시간 채널 prefix, 기본 `dev`), `REALTIME_VOC_INTERVAL`(VOC 게이트 간격, 기본 3)
- env 파일들: `.env`, `.env.development`, `.env.106.local`, `.env.106.development`, `.env.192.development`, `.env.5f.development`, `.env.prod`

## 9. 다이어그램 작성 제안 (그리는 Claude에게)

권장 다이어그램 2~3장:
1. **컴포넌트/배포도**: 외부 STT/NLP · Redis · asst-service(RedisService·SocketGateway·핸들러들) · 프론트 · (게이트웨이/ALB sticky) 관계.
2. **시퀀스 다이어그램 ×2**:
   - (a) 코칭 발행→수신: 코칭서비스 → Redis(`coaching:message`) → CoachingSocketHandler → room emit → 프론트
   - (b) 실시간 VOC: STT/NLP → Redis(`nlp:complete`) → RedisMonitor/VocRealtime(게이트+LLM) → Redis(`call:voc`) → 브리지 → 프론트
3. **데이터 흐름 범례**: `publish`(빨강) / `subscribe`(파랑) / `socket emit`(초록) / REST 제어(회색) 로 색 구분. room=채널명 매핑 강조.

---

## 10. 다이어그램 검증 노트 (기존 draw.io 흐름도 대비 정정 사항)

`advisor_socket_architecture-Realtime Socket 구독-배포 흐름도.drawio` 를 실제 코드와 대조해 발견한 **틀린 항목**만 정리한다. (2026-07-23 검토)

1. **"재연결 시 서버가 room 자동복구 안 함" → 틀림.**
   - 코드에 `connectionStateRecovery`(`maxDisconnectionDuration: 2분`, `socket.gateway.ts:55`)가 켜져 있어 **재연결 시 참여 room + 미수신 메시지를 서버가 자동복원**한다.
   - 단 기본 in-memory 어댑터라 **①같은 파드 ②2분 이내** 재연결일 때만 복원. 멀티파드(sticky 미보장)거나 2분 초과 시에만 재join 필요.
   - 정정 문구: "같은 파드·2분 이내 재연결은 서버가 자동복원, 그 외에는 재join 필요".

2. **"① 소켓 연결 (쿠키 인증)" → asst-service는 소켓 인증을 하지 않음.**
   - `handleConnection`에 JWT/쿠키 검증·guard·소켓 미들웨어 전무. CORS `credentials:true`로 쿠키가 전송될 뿐 asst-service가 검증하지 않는다.
   - 실제 인증은 **게이트웨이(106 user-service)** 담당. 다이어그램은 "게이트웨이에서 쿠키 인증" 또는 "쿠키 전달(credentials)"로 표기해야 정확.

3. **⑦ "자체 분석/처리(asst-service)"에 `orchestrator:persisted` 포함 → 발행 주체 오류.**
   - `call:voc`(`voc-realtime.service.ts:764`), `coaching:*`(`coaching-redis.service.ts`)는 asst-service 발행이 맞다.
   - 그러나 `orchestrator:persisted`는 **백엔드에 발행 코드 없음** → 외부 Call-Orchestrator가 발행하는 채널. asst-service 자체 발행 박스에서 분리 표기해야 함.

> 참고(틀린 건 아니나 보완하면 정확): join-room은 소켓 room 입장만 하며 Redis 채널 구독을 자동 트리거하지 않는다(코칭만 기동 시 정적 구독, 그 외는 `POST /redis-monitor/subscribe/:channel` 필요). room 키의 tenant 세그먼트는 회사 UUID가 아니라 `vendor_tenant_id`.
