# Redis 클라이언트 구현 현황 및 성능 분석 문서

## 📋 문서 개요

- **작성일**: 2025-10-31
- **작성자**: Backend Development Team
- **목적**: Redis 클라이언트 구현 방식 및 성능 검토
- **대상**: Redis 인프라 담당자

---

## 1. 클라이언트 라이브러리 정보

### 사용 라이브러리
- **패키지명**: `redis`
- **버전**: `4.7.1`
- **공식 저장소**: https://github.com/redis/node-redis
- **설명**: Redis 공식 Node.js 클라이언트 (v4)

### 주요 특징
- Promise 기반 비동기 API
- TypeScript 완전 지원
- Pub/Sub 전용 연결 분리
- 자동 재연결 기능

---

## 2. 클라이언트 구현 구조

### 2.1 연결 구성

```typescript
// 파일: src/common/services/redis.service.ts

// 1. 메인 클라이언트 (일반 명령용)
this.client = createClient({
  socket: {
    host: redisConfig.host,
    port: redisConfig.port,
    // TCP 성능 최적화
    keepAlive: 5000,        // TCP KeepAlive (5초마다)
    noDelay: true,          // Nagle 알고리즘 비활성화
    connectTimeout: 10000,  // 연결 타임아웃 10초
    reconnectStrategy: (retries) => {
      if (retries > 10) {
        return new Error('최대 재시도 횟수 초과');
      }
      return Math.min(retries * 100, 3000); // 지수 백오프 (최대 3초)
    },
  },
  password: redisConfig.password,
  database: redisConfig.db,
  pingInterval: redisConfig.health_check_interval, // Health check interval (기본값: 30초)
});

// 2. 구독 전용 클라이언트 (Pub/Sub 전용)
this.subscriber = createClient({
  socket: {
    host: redisConfig.host,
    port: redisConfig.port,
    // TCP 성능 최적화 (Pub/Sub은 지연에 민감)
    keepAlive: 5000,        // TCP KeepAlive (5초마다)
    noDelay: true,          // Nagle 알고리즘 비활성화
    connectTimeout: 10000,  // 연결 타임아웃 10초
    reconnectStrategy: (retries) => {
      if (retries > 10) {
        return new Error('최대 재시도 횟수 초과');
      }
      return Math.min(retries * 50, 1000); // 빠른 재연결 (최대 1초)
    },
  },
  password: redisConfig.password,
  database: redisConfig.db,
  pingInterval: redisConfig.health_check_interval, // Health check interval (기본값: 30초)
});
```

**설계 이유**: Redis Pub/Sub은 블로킹 모드로 작동하므로 일반 명령과 분리 필요

### 2.2 연결 설정

```typescript
// 파일: src/config/redis.config.ts

{
  host: process.env.REDIS_HOST || 'localhost',
  port: parseInt(process.env.REDIS_PORT || '6379', 10),
  password: process.env.REDIS_PASSWORD || undefined,
  db: parseInt(process.env.REDIS_DB || '0', 10),
  health_check_interval: parseInt(process.env.REDIS_HEALTH_CHECK_INTERVAL || '30000', 10), // Health check interval (기본값: 30초)
  retryDelayOnFailover: 100,      // 재시도 간격: 100ms
  enableReadyCheck: false,         // Ready 체크 비활성화
  maxRetriesPerRequest: null,      // 무제한 재시도
  lazyConnect: true,               // 지연 연결
}
```

---

## 3. Pub/Sub 메시지 처리 흐름

### 3.1 구독 프로세스

```
1. API 호출: POST /redis-monitor/subscribe/{channel}
   ↓
2. RedisService.subscribe(channel, callback)
   ↓
3. subscriber.subscribe(channel, (message) => { ... })
   ↓
4. 구독 정보 저장: subscriptions.set(channel, {...})
```

### 3.2 메시지 수신 프로세스

```
1. Redis Server → Pub/Sub 메시지 발행
   ↓
2. subscriber.on('message', (channel, message) => { ... })
   ↓ (즉시 호출)
3. handleMessage(channel, message)
   ↓ (동기 실행)
4. subscription.callback(redisMessage)
   ↓ (동기 실행)
5. RedisMonitorController.handleChannelMessage()
   ↓ (동기 실행)
6. SocketGateway.broadcastToRedisMonitorRoom()
```

**처리 방식**: 완전 동기(Synchronous) 처리
- 비동기 큐 사용 없음
- Event Loop 지연 없음
- 메시지 수신 즉시 처리

### 3.3 메시지 핸들러 코드

```typescript
// 파일: src/common/services/redis.service.ts (라인 133-136)

this.subscriber.on('message', (channel: string, message: string) => {
  // 즉시 처리 - 비동기 큐 없음
  this.handleMessage(channel, message);
});
```

```typescript
// 파일: src/common/services/redis.service.ts (라인 160-190)

private handleMessage(channel: string, message: string) {
  const timestamp = new Date();
  
  // 간소화된 로깅 (debug 레벨)
  this.logger.debug(
    `[Redis] ${channel}: ${message.length}bytes @ ${timestamp.toISOString()}`,
  );
  
  const subscription = this.subscriptions.get(channel);
  if (subscription?.isActive) {
    const redisMessage: RedisMessage = {
      channel,
      message,
      timestamp,
    };
    
    try {
      // 동기 콜백 실행 (블로킹 없음)
      subscription.callback(redisMessage);
    } catch (error) {
      this.logger.error(
        `[Redis] Callback error on ${channel}:`,
        error instanceof Error ? error.message : String(error),
      );
    }
  }
}
```

---

## 4. 성능 관련 설정

### 4.1 클라이언트 레벨 설정

| 설정 | 값 | 성능 영향 |
|------|-----|-----------|
| `socket.keepAlive` | 5000ms | TCP 연결 유지 (네트워크 장비 타임아웃 방지) |
| `socket.noDelay` | true | **Nagle 알고리즘 비활성화 (지연 최소화)** |
| `socket.connectTimeout` | 10000ms | 연결 타임아웃 (무한 대기 방지) |
| `reconnectStrategy` | 지수 백오프 | 자동 재연결 (메인: 최대 3초, Pub/Sub: 최대 1초) |
| `pingInterval` | 30000ms (기본값) | Health check interval (연결 상태 주기적 확인) |

### 4.2 메시지 처리 최적화

#### ✅ 적용된 최적화
1. **TCP 성능 최적화**: 
   - `noDelay: true` - **Nagle 알고리즘 비활성화로 지연 최소화** (가장 중요!)
   - `keepAlive: 5000` - TCP 연결 유지 (네트워크 타임아웃 방지)
   - `connectTimeout: 10000` - 연결 타임아웃 설정
2. **자동 재연결**: 연결 끊김 시 자동 재연결 (지수 백오프)
3. **동기 처리**: setImmediate/setTimeout 미사용으로 이벤트 루프 지연 제거
4. **최소 로깅**: 메시지당 1개의 debug 로그만 출력
5. **JSON 직렬화 최소화**: 불필요한 JSON.stringify() 제거
6. **에러 격리**: try-catch로 개별 메시지 에러가 전체 구독에 영향 없도록 처리

#### ❌ 제거된 비효율적 코드
- 메시지당 7개 이상의 로그 출력
- JSON.stringify() 3회 호출
- setImmediate()를 통한 비동기 큐 사용 (10-50ms 지연 발생)
- 중복 Socket.IO 브로드캐스트

---

## 5. 현재 성능 특성

### 5.1 메시지 처리 지연 시간

| 구간 | 예상 지연 |
|------|----------|
| Redis → Node.js 클라이언트 | ~0.1-1ms (네트워크) |
| 클라이언트 내부 처리 | ~0.1-0.5ms (동기) |
| Socket.IO 브로드캐스트 | ~1-5ms |
| **총 지연** | **~1-7ms** |

### 5.2 처리량

- **이론적 최대**: 초당 10,000+ 메시지
- **실제 처리량**: Socket.IO 브로드캐스트 성능에 의존

### 5.3 리소스 사용

- **연결 수**: 2개 (메인 + Pub/Sub)
- **메모리**: 채널당 ~1KB (구독 정보)
- **CPU**: 메시지 처리 시 최소 사용 (동기 처리)

---

## 6. 잠재적 성능 병목 지점

### 6.1 클라이언트 레벨

#### ✅ 문제 없음 (2025-10-31 최적화 완료)
- [x] 적절한 연결 분리 (메인/Pub/Sub)
- [x] **TCP Nagle 알고리즘 비활성화** (`noDelay: true`) - 지연 최소화
- [x] **TCP KeepAlive 활성화** (`keepAlive: 5000`) - 연결 유지
- [x] **자동 재연결 전략** - 지수 백오프 (Pub/Sub은 빠른 재연결)
- [x] 동기 메시지 처리 (즉시 실행)
- [x] 최소한의 로깅
- [x] 에러 핸들링

#### 📝 최근 수정 (2025-10-31)
**발견된 문제:**
1. ❌ TCP Nagle 알고리즘 활성화 상태 → 작은 패킷 모아서 전송 (최대 200ms 지연)
2. ❌ TCP KeepAlive 미설정 → 네트워크 장비에서 유휴 연결 종료 가능
3. ❌ 재연결 전략 없음 → 연결 끊김 시 복구 불가

**적용된 수정:**
1. ✅ `noDelay: true` 추가 → **즉시 전송 (지연 제거)**
2. ✅ `keepAlive: 5000` 추가 → 5초마다 keepalive 패킷 전송
3. ✅ `reconnectStrategy` 추가 → 자동 재연결 (메인: 최대 3초, Pub/Sub: 최대 1초)

### 6.2 서버 인프라 레벨

#### 검토 요청 사항

1. **네트워크 지연**
   ```
   질문: Redis 서버와 애플리케이션 서버 간 네트워크 레이턴시는?
   - 같은 VPC/서브넷인가?
   - 평균 RTT(Round Trip Time)는?
   ```

2. **Redis 서버 성능**
   ```
   질문: Redis 서버 메트릭 확인 필요
   - CPU 사용률
   - 메모리 사용률
   - 연결 수 (maxclients 설정)
   - slowlog 분석
   ```

3. **Pub/Sub 설정**
   ```
   질문: Redis Pub/Sub 관련 설정
   - client-output-buffer-limit pubsub 설정값
   - 현재 Pub/Sub 클라이언트 수
   - 채널당 메시지 크기 및 빈도
   ```

---

## 7. 모니터링 및 진단

### 7.1 클라이언트 로그 예시

```log
# 정상 동작
[Redis] test-channel: 1234bytes @ 2025-10-31T00:00:00.000Z

# 연결 오류
Redis 구독 클라이언트 오류: [에러 상세]

# 콜백 오류
[Redis] Callback error on test-channel: [에러 메시지]
```

### 7.2 성능 측정을 위한 메트릭

#### 클라이언트 측 (애플리케이션)
- 메시지 수신 시간 (timestamp 기록)
- 콜백 실행 시간
- 에러 발생 빈도

#### 서버 측 (Redis) - 확인 필요
```bash
# Redis CLI 명령어
INFO stats
INFO clients
CLIENT LIST TYPE pubsub
SLOWLOG GET 10
CONFIG GET client-output-buffer-limit
```

---

## 8. 성능 이슈 진단 체크리스트

### 8.1 클라이언트 레벨 (애플리케이션) ✅
- [x] 적절한 클라이언트 라이브러리 사용 (redis@4.7.1)
- [x] Pub/Sub 전용 연결 분리
- [x] 동기 메시지 처리 (지연 최소화)
- [x] 최소 로깅 (성능 영향 최소화)
- [x] 에러 처리 및 격리

### 8.2 서버 레벨 (Redis) - 확인 필요 ⚠️
- [ ] Redis 서버 CPU/메모리 상태
- [ ] 네트워크 레이턴시 (애플리케이션 ↔ Redis)
- [ ] client-output-buffer-limit 설정 적절성
- [ ] Pub/Sub 클라이언트 수 확인
- [ ] slowlog 분석
- [ ] maxclients 설정 확인

### 8.3 네트워크 레벨 - 확인 필요 ⚠️
- [ ] 같은 VPC/서브넷 배치 여부
- [ ] 방화벽/보안그룹 설정
- [ ] 대역폭 제한 여부
- [ ] 로드밸런서 설정 (해당 시)

---

## 9. 추가 정보 요청

### 9.1 Redis 서버 정보 필요
```bash
# 다음 명령어 실행 결과 공유 요청
redis-cli INFO
redis-cli INFO stats
redis-cli INFO clients
redis-cli CLIENT LIST TYPE pubsub
redis-cli CONFIG GET client-output-buffer-limit
redis-cli SLOWLOG GET 10
```

### 9.2 성능 이슈 재현 정보
- **발생 빈도**: 항상 / 간헐적 / 특정 시간대
- **메시지 크기**: 평균/최대 메시지 크기
- **메시지 빈도**: 초당 메시지 수
- **구독 채널 수**: 동시 구독 중인 채널 수
- **지연 시간**: 발행 → 수신까지 측정된 시간

### 9.3 환경 정보
- **배포 환경**: K8s / VM / 온프레미스
- **Redis 버전**: ?
- **Redis 배포 방식**: Standalone / Sentinel / Cluster
- **네트워크 구성**: VPC 내부 / 외부 / 크로스 리전

---

## 10. 결론 및 제안

### 10.1 현재 클라이언트 구현 평가
✅ **적절한 구현**
- Redis 공식 클라이언트 사용
- Pub/Sub 전용 연결 분리
- 동기 처리로 지연 최소화
- 적절한 에러 핸들링

### 10.2 클라이언트 레벨 개선 불필요
현재 구현은 **베스트 프랙티스**를 따르고 있으며, 클라이언트 레벨에서 추가 최적화는 미미할 것으로 판단됩니다.

### 10.3 성능 이슈 원인 추정
성능 이슈가 있다면 다음 가능성이 높습니다:
1. **네트워크 레이턴시**: 애플리케이션 ↔ Redis 서버 간 거리
2. **Redis 서버 부하**: CPU/메모리 과부하
3. **Buffer 오버플로우**: client-output-buffer-limit 초과
4. **느린 구독자**: 다른 클라이언트의 느린 처리로 인한 전체 지연

---

## 11. 연락처

**개발팀 담당자**
- 이메일: [개발팀 이메일]
- Slack: [채널명]

**추가 정보 제공 가능**
- 애플리케이션 로그
- 성능 측정 데이터
- 코드 상세 설명

---

## 부록: 코드 참조

### A. 주요 파일 위치
```
src/
├── common/
│   ├── services/
│   │   └── redis.service.ts          # Redis 클라이언트 구현
│   └── controllers/
│       └── redis-monitor.controller.ts # Pub/Sub 구독 관리
├── config/
│   └── redis.config.ts                # Redis 설정
└── common/
    └── constants/
        └── coaching.constants.ts       # 채널 상수
```

### B. 환경 변수
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
REDIS_HEALTH_CHECK_INTERVAL=30000  # Health check interval (밀리초, 기본값: 30000ms = 30초)
```

### C. 사용 중인 Redis 명령어
- `SUBSCRIBE <channel>`: 채널 구독
- `UNSUBSCRIBE <channel>`: 구독 해제
- `PUBLISH <channel> <message>`: 메시지 발행 (다른 서비스에서)

