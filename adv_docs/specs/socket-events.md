# Socket.IO 이벤트 카탈로그

> Advisor 메인 Socket.IO(`/api/asst/v1/socket.io`) 의 전체 이벤트 명세.
> 어드바이저봇 소켓(CE 서비스 직결)은 [advisorbot.md](advisorbot.md) 참조.

---

## 1. 연결 경로

```
브라우저 path: /aicc/asst-service/socket.io
   ↓ Langsa 게이트웨이 (StripPrefix=2 + PrefixPath=/api/asst/v1)
asst-service: /api/asst/v1/socket.io
```

설정 위치: [socket.gateway.ts:29-53](../../asst-service/src/common/gateways/socket.gateway.ts#L29-L53)

### 옵션

| 옵션 | 값 |
|------|------|
| `transports` | `['websocket', 'polling']` |
| `pingTimeout` | 60000ms |
| `pingInterval` | 25000ms |
| `allowEIO3` | true (구버전 클라이언트 호환) |
| `secure` (WSS) | `SOCKET_SECURE=1` 기본 |

---

## 2. 이벤트 분류

```
┌─────────────────────────────────────────────────────────────┐
│ 시스템 이벤트 (Socket.IO 내장)                                  │
│   connect, disconnect, connect_error                       │
├─────────────────────────────────────────────────────────────┤
│ Room 관리 (Advisor 정의)                                       │
│   join-room, leave-room, join-room-success, ...            │
├─────────────────────────────────────────────────────────────┤
│ Redis 메시지 중계                                              │
│   redis-message                                            │
├─────────────────────────────────────────────────────────────┤
│ 도메인 이벤트                                                  │
│   coaching, coaching_request                               │
│   notice, notice-broadcast                                 │
│   agent-status-update                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 시스템 이벤트 (Socket.IO 내장)

### 3-1. `connect` (서버 → 클라이언트)

연결 수립 시 자동 발생.

```typescript
// 프론트
socket.on("connect", () => {
  console.log("[socket-IO-Plugin] connected:", socket.id);
});
```

### 3-2. `disconnect` (서버 → 클라이언트)

연결 해제 시. `reason` 인자에 사유.

```typescript
socket.on("disconnect", (reason) => {
  // reason: "transport close", "io server disconnect", "ping timeout" 등
});
```

### 3-3. `connect_error` (서버 → 클라이언트)

핸드셰이크 실패. CORS / 인증 / 게이트웨이 라우팅 문제.

---

## 4. Room 관리 이벤트

### 4-1. `join-room` (클라이언트 → 서버)

**페이로드**: `string` (room 이름)

```typescript
socket.emit('join-room', 'dev:tenant1:agent01:call:nlp:complete');
```

핸들러: [socket.gateway.ts:312-366](../../asst-service/src/common/gateways/socket.gateway.ts#L312-L366)

**서버 동작**:
1. room 명 유효성 검사 (빈 문자열 거부)
2. 클라이언트를 room 에 join
3. `createRedisMonitorRoom()` 호출 (room이 없으면 생성)
4. 응답 emit

### 4-2. `join-room-success` (서버 → 클라이언트)

```typescript
{
  room: 'dev:tenant1:agent01:call:nlp:complete',
  message: "Successfully joined room '...'",
  clientCount: 1
}
```

### 4-3. `join-room-error` (서버 → 클라이언트)

```typescript
{
  error: 'Invalid room name' | 'Internal server error',
  message: '...'
}
```

### 4-4. `leave-room` (클라이언트 → 서버)

**페이로드**: `string` (room 이름)

```typescript
socket.emit('leave-room', 'dev:tenant1:agent01:call:nlp:complete');
```

핸들러: [socket.gateway.ts:369-407](../../asst-service/src/common/gateways/socket.gateway.ts#L369-L407)

### 4-5. `leave-room-success` (서버 → 클라이언트)

```typescript
{
  room: '...',
  message: "Successfully left room '...'"
}
```

### 4-6. `room-member-left` (서버 → 같은 room의 다른 멤버들)

다른 사용자가 떠났을 때 알림 (현재 사용처 미확인).

---

## 5. Redis 메시지 중계

### 5-1. `redis-message` (서버 → 클라이언트)

가장 중요한 이벤트. Redis Pub/Sub 메시지를 Socket.IO 로 중계.

**페이로드**:

```typescript
{
  channel: string,           // Redis 채널명 (room명과 동일)
  message: string,           // 원본 JSON 문자열
  timestamp: string,         // ISO 8601
  source?: 'redis'
}
```

핸들러 발행: [socket.gateway.ts:594-600](../../asst-service/src/common/gateways/socket.gateway.ts#L594-L600)

**프론트 처리**:

```typescript
socket.on('redis-message', (raw) => {
  // raw.channel 로 분기
  if (raw.channel.includes(':call:events')) { /* ... */ }
  else if (raw.channel.includes(':call:nlp:partial')) { /* ... */ }
  // ... (useChatMessageParser.ts 참조)
});
```

→ Redis 채널 spec: [stt-nlp-contract.md](stt-nlp-contract.md)

---

## 6. 코칭 이벤트

### 6-1. `coaching` (서버 → 클라이언트)

코칭 메시지 도착. 특정 상담원의 `coaching_<receiver_key>` room으로만 전송.

**페이로드** ([coaching.types.ts](../../asst-service/src/common/types/coaching.types.ts)):

```typescript
{
  id: string,
  call_id?: string,
  callstats_id?: string,
  coaching_request_id?: string,
  sender_key: string,           // 발신자(관리자) 식별자
  receiver_key: string,         // 수신자(상담원) 식별자
  sender_name: string,
  customer_name?: string,
  content: string,              // 코칭 내용
  is_important: boolean,
  priority_type?: string,
  timestamp: string
}
```

발행: [coaching-socket.handler.ts:223](../../asst-service/src/common/gateways/handlers/coaching-socket.handler.ts#L223)

**상수**: `SOCKET_COACHING_EVENTS.COACHING = 'coaching'` ([coaching.constants.ts:14](../../asst-service/src/common/constants/coaching.constants.ts#L14))

### 6-2. `coaching_request` (서버 → 클라이언트)

코칭 요청 도착. 상담원에게 "관리자가 코칭하려 합니다" 알림.

발행: [coaching-socket.handler.ts:146](../../asst-service/src/common/gateways/handlers/coaching-socket.handler.ts#L146)

**상수**: `SOCKET_COACHING_EVENTS.COACHING_REQUEST = 'coaching_request'`

### 6-3. Room 명명 규칙

```
coaching_<receiver_key>
```

각 상담원은 본인의 `coaching_<key>` room 에 가입해야 코칭 수신 가능.

⚠️ **`receiver_key` 가 무엇인지(uuid? cc_cti_id?) 컨벤션 확인 필요**.

---

## 7. 공지 이벤트

### 7-1. `notice` (양방향)

#### 클라이언트 → 서버 (이전 패턴, 사용처 적음)

[socket.gateway.ts:410-425](../../asst-service/src/common/gateways/socket.gateway.ts#L410-L425):

```typescript
@SubscribeMessage('notice')
handleNoticeMessage(@MessageBody() data, @ConnectedSocket() client) {
  client.emit('notice-response', { type: 'NOTICE', message: 'received' });
}
```

#### 서버 → 클라이언트 (실제 사용)

발행: [notice-socket.handler.ts:58](../../asst-service/src/common/gateways/handlers/notice-socket.handler.ts#L58)

**페이로드** ([socket.types.ts](../../asst-service/src/common/types/socket.types.ts)):

```typescript
{
  id: string,
  name: string,           // 공지 제목
  is_urgent: boolean,
  content: string,
  remind_time: Date | null,
  creator_key: string,
  target_key: string,
  create_at: Date
}
```

### 7-2. `notice-broadcast` (서버 → 클라이언트)

`notice` 와 같은 페이로드. broadcast 용도 이중 emit ([notice-socket.handler.ts:57-58](../../asst-service/src/common/gateways/handlers/notice-socket.handler.ts#L57-L58)):

```typescript
this.server.to(roomName).emit('notice-broadcast', message);
this.server.to(roomName).emit('notice', message);
```

→ 두 이벤트가 동시에 발생. 프론트는 둘 중 하나만 listen 권장.

### 7-3. `notice-response` (서버 → 클라이언트)

클라이언트가 `notice` emit 했을 때의 ack 응답. 거의 사용 안 함.

---

## 8. 상담원 상태 이벤트

### 8-1. `agent-status-update` (서버 → 클라이언트)

상담원 상태 변경을 모든 관리자에게 broadcast.

**페이로드** ([agent-status-socket.handler.ts:5-10](../../asst-service/src/common/gateways/handlers/agent-status-socket.handler.ts#L5-L10)):

```typescript
{
  cc_cti_id: string,
  agent_id?: string | null,
  status: 'IDLE' | 'ON_CALL' | 'AFTER_CALL' | string,
  timestamp: string
}
```

발행: `server.to('agent-status').emit('agent-status-update', message)` ([line 53](../../asst-service/src/common/gateways/handlers/agent-status-socket.handler.ts#L53))

**Room 명**: `agent-status` (글로벌 단일 room)

---

## 9. 일반 메시지 이벤트

### 9-1. `message` (클라이언트 → 서버)

[socket.gateway.ts:428-](../../asst-service/src/common/gateways/socket.gateway.ts#L428):

```typescript
@SubscribeMessage('message')
handleMessage(@MessageBody() data, @ConnectedSocket() client) {
  // ... 메시지 타입별 분기
  if (unknown type) client.emit('error', { message: 'Unknown message type' });
}
```

→ 현재 거의 사용 안 함. 향후 확장용.

### 9-2. `personal-message` (서버 → 특정 사용자)

발행: `server.to(userId).emit('personal-message', data)` ([line 464](../../asst-service/src/common/gateways/socket.gateway.ts#L464))

→ 1:1 메시지 전송용. 사용처 확인 필요.

### 9-3. `error` (서버 → 클라이언트)

알 수 없는 메시지 타입 수신 시.

---

## 10. Room 명명 컨벤션 종합

| Room 패턴 | 가입 주체 | 용도 |
|----------|-----------|------|
| `{env}:{tenantId}:{agentId}:call:nlp:partial` | 본인 + 관리자 | STT 발화 스트리밍 |
| `{env}:{tenantId}:{agentId}:call:nlp:complete` | 본인 + 관리자 | STT 발화 확정 |
| `{env}:{tenantId}:{agentId}:call:events` | 본인만 | 통화 시작/종료 |
| `{env}:{tenantId}:{agentId}:call:orchestrator:persisted` | 본인 + 관리자 | DB 저장 완료 |
| `coaching_<receiver_key>` | 해당 상담원 본인 | 코칭 메시지 수신 |
| `agent-status` | 관리자 | 상담원 상태 broadcast |
| `notice` (또는 target_key) | 공지 대상자 | 공지 알림 |

→ Room 가입 권한이 서버에서 강제되지 않음 (보안 강화 시 검토).

---

## 11. 백엔드 → 프론트엔드 이벤트 전체 매트릭스

| 이벤트 | 발행 위치 | 페이로드 |
|--------|----------|---------|
| `connect` | Socket.IO 내장 | - |
| `disconnect` | Socket.IO 내장 | `reason: string` |
| `connect_error` | Socket.IO 내장 | `Error` |
| `join-room-success` | socket.gateway.ts:354 | `{ room, message, clientCount }` |
| `join-room-error` | socket.gateway.ts:319, 361 | `{ error, message }` |
| `leave-room-success` | socket.gateway.ts:388 | `{ room, message }` |
| `leave-room-error` | socket.gateway.ts:376, 402 | `{ error, message }` |
| `room-member-left` | socket.gateway.ts:395 | `{ room, clientId, totalClients }` |
| `redis-message` | socket.gateway.ts:600 | `{ channel, message, timestamp, source }` |
| `coaching` | coaching-socket.handler.ts:223 | `CoachingMessage.payload` |
| `coaching_request` | coaching-socket.handler.ts:146 | `CoachingRequestMessage.payload` |
| `notice` | notice-socket.handler.ts:58 | `NoticeSocketMessage` |
| `notice-broadcast` | notice-socket.handler.ts:57 | `NoticeSocketMessage` (동일) |
| `notice-response` | socket.gateway.ts:418 | `{ type, message }` |
| `agent-status-update` | agent-status-socket.handler.ts:53 | `AgentStatusMessage` |
| `personal-message` | socket.gateway.ts:464 | (data passthrough) |
| `error` | socket.gateway.ts:444 | `{ message }` |

---

## 12. 프론트엔드 → 백엔드 이벤트 매트릭스

| 이벤트 | 핸들러 | 페이로드 |
|--------|--------|---------|
| `join-room` | socket.gateway.ts:312 | `roomName: string` |
| `leave-room` | socket.gateway.ts:369 | `roomName: string` |
| `notice` | socket.gateway.ts:410 | `SocketMessage<NoticeSocketMessage>` |
| `message` | socket.gateway.ts:428 | (any, 타입 분기) |

---

## 13. 디버깅

| 도구 | 사용법 |
|------|--------|
| 현재 room 멤버 | `GET /redis-monitor/debug/rooms` |
| 활성 소켓 ID | `socket.id` (브라우저 콘솔) |
| 이벤트 캐치 (개발용) | `socket.onAny((event, data) => console.log(event, data))` |
| 백엔드 측 emit 로그 | `📡 BROADCAST START`, `✅ BROADCAST SUCCESS` 검색 |
| Room 0명 경고 | `⚠️ NO CLIENTS IN ROOM` (sticky session 문제) |

---

## 14. 인계 시 주의

1. **`notice` 이벤트가 양방향** — 한쪽 의미만 가정하지 말 것
2. **`notice` + `notice-broadcast` 동시 emit** — 중복 처리 주의
3. **Room 가입 권한 미검증** — 임의의 room 가입 가능 (보안 강화 시 처리)
4. **K8s sticky session 필수** — 같은 사용자가 다른 pod 라우팅 시 room 분실
5. **`SOCKET_COACHING_EVENTS` 상수** — 이벤트명 변경 시 [coaching.constants.ts](../../asst-service/src/common/constants/coaching.constants.ts) 한 곳에서 관리
6. **이벤트명 컨벤션 불일치** — `coaching` (snake_case 아님), `coaching_request` (snake_case), `notice-broadcast` (kebab-case), `agent-status-update` (kebab-case). 신규 추가 시 컨벤션 합의 후 진행.

---

## 15. 향후 확장 시

새 이벤트 추가 절차:

1. 이벤트명 + 페이로드 타입 정의 (예: `coaching.types.ts` 처럼)
2. 상수 파일에 이벤트명 등록 (예: `coaching.constants.ts`)
3. 핸들러 (`*-socket.handler.ts`) 또는 `socket.gateway.ts` 에 emit 로직
4. 프론트엔드 listener 추가
5. 이 문서에 추가

→ Room 가입 권한 검증이 필요하면 별도 가드 패턴 도입 검토.
