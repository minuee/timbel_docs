# Redis 재접속 데드락 장애 분석 및 수정 (`RedisService`)

> 목적: half-open 으로 끊긴 Redis 연결에서 **자동 복구가 영구히 멈추는 버그**를 제거한다.
> 다른 레포(다른 서버 배포본)에 동일 작업을 이식하기 위한 문서.
> 기준 코드: `asst-service-portal` / NestJS + `redis@4.7.1`.
> 대상 파일: `src/common/services/redis.service.ts` (이 파일 **하나만** 수정, 호출부 변경 없음)
> 발생 환경: 106 개발기 (2026-07-27 ~ 07-28)

---

## 1. 증상

- 코칭 요청 / 코칭하기를 눌러도 상담사·관리자 화면에 **아무것도 뜨지 않음**
- VOC 실시간 전달도 동일하게 안 됨
- 그 외 상담 화면(STT 스트림, 콜 이벤트 등)은 **정상 동작** → "코칭 서비스 문제"로 보이는 착시

로그상으로는 DB 저장까지는 정상이고 Redis 발행에서만 실패했다.

```
[CoachingService]      ✅ 코칭 요청 생성 완료: ID=coachrq_a4b5..., receiver=cd377897-...
[CoachingRedisService] 📤 REDIS PUB - 코칭 요청: ID=coachrq_a4b5...
[RedisService]         ERROR 채널 coaching:request 메시지 발행 실패:
                             Error: The client is closed
[CoachingRedisService] ❌ REDIS PUB FAILED - 코칭 요청: ID=coachrq_a4b5...
```

---

## 2. 왜 "코칭·VOC만" 안 되는 것처럼 보였나

이 서비스는 Redis 연결을 **두 개** 만든다.

| 클라이언트 | 용도 | 장애 시 상태 |
|---|---|---|
| `subscriber` (구독 전용) | `call:events`, `nlp`, STT 스트림 등 **구독** | **정상** |
| `client` (메인, 명령용) | `publish`, `HSET`, `ZRANGE` 등 **명령 전부** | **닫힘** |

메인 클라이언트만 죽었으므로, 실패한 것들의 공통점은 "기능"이 아니라 **"메인 클라이언트를 쓰는가"** 였다.

실제로 같은 시간대에 아래가 전부 `The client is closed` 로 죽고 있었다.

- `PUBLISH coaching:request` / `coaching:message` (코칭)
- `PUBLISH {env}:{tenant}:{cti}:call:voc` (VOC)
- `HSET {env}:{tenant}:{cti}:call:setting` (`AgentCallSettingService`)
- `ZRANGE {env}:call:{callId}:turn:data` (STT 이전 데이터 조회)

그리고 코칭·VOC 가 유독 눈에 띈 이유는, 이 둘이 **인스턴스 간 전달이 필요한 기능**이라 Redis pub/sub 이 유일한 통로이기 때문이다. 한 인스턴스 안에서 끝나는 소켓 동작은 Redis 없이도 잘 돈다.

> **이식 시 교훈**: `The client is closed` 가 특정 기능에서만 보여도 원인은 기능이 아니라 **연결 객체**다. 메인/구독 클라이언트를 분리해 쓰는 구조라면 반드시 양쪽 상태를 따로 확인할 것.

---

## 3. 근본 원인

### 3-1. 타임라인 (실제 로그)

```
07-27 07:26:43  🩺 Redis 자가 헬스체크 시작 (30000ms 주기)
07-27 07:26:44  [Redis] Subscribed: coaching:request / coaching:message   ← 정상 기동
07-27 14:59:53  🩺 Redis PING 무응답(half-open 의심) → 자동 재연결: PING timeout   ← 감지 성공
07-27 14:59:53  🔄 Redis 재접속 시도 시작...
                ↑ 이후 "✅ 재접속 성공" 도 "❌ 재접속 실패" 도 없음 (약 10시간 30분)
07-28 01:33:24  (컨테이너 수동 재시작으로만 복구)
```

**감지는 정상, 복구가 데드락.** 30초마다 도는 헬스체크가 10시간 동안 한 번도 복구를 재시도하지 못했다.

### 3-2. 원인 A — `quit()` 무한 대기

재접속의 첫 단계가 기존 연결 정리인데, 타임아웃이 없었다.

```ts
// 수정 전
if (this.client.isOpen) {
  await this.client.quit();   // ← 여기서 영원히 멈춤
}
```

- `quit()` 은 Redis 에 `QUIT` 명령을 보내고 **응답을 기다린다**
- half-open 상태에서는 응답이 영영 오지 않는다
- node-redis v4 에서 재연결 중인 클라이언트도 `isOpen === true` 라 이 분기를 통과한다
- 타임아웃이 없으므로 `await` 이 무기한 pending

### 3-3. 원인 B — 진행 중 플래그가 안 풀림

`checkHealthAndHeal()` 은 중복 실행 방지를 위해 아래처럼 되어 있다.

```ts
if (this.reconnectPromise) {
  return;   // 이미 재연결 진행 중이니 건너뜀
}
```

`reconnectPromise` 는 `performReconnect()` 가 **끝나야** 해제되는데(원인 A로 끝나지 않음), 그 결과 30초마다 돌던 헬스체크가 매번 "지금 복구 중"으로 판단하고 그냥 돌아갔다. **영구 고착**.

### 3-4. 원인 C — 연결 상태 플래그가 거짓 (부가)

```ts
// 수정 전
this.client.on('connect', () => { this.isConnected = true; });
```

node-redis v4 에서 `connect` 는 **소켓만 붙은 시점**이고, AUTH/SELECT 완료는 `ready` 다. 그래서 명령을 보낼 수 없는 상태에서도 `isConnected === true` 가 되어, `publish()` 의 사전 검사(`if (!this.isConnected) return false`)를 그대로 통과한 뒤 실제 호출에서 예외가 났다.

### 3-5. 왜 AWS 에서는 안 터졌나

끊기는 방식이 다르다.

| 환경 | 끊는 방식 | 결과 |
|---|---|---|
| AWS (NLB) | RST/FIN 신호를 보냄 | node-redis 가 즉시 에러 감지 → **라이브러리 자체 재연결** 동작 → 문제의 코드를 아예 안 탐 |
| 106 (방화벽/NAT) | 신호 없이 조용히 폐기 (half-open) | 소켓이 겉보기엔 살아있음 → 라이브러리는 모름 → **PING 타임아웃 경로만 감지 가능** → 그 경로가 데드락 |

**이 버그는 half-open 으로 끊기는 환경에서만 발현한다.** 사내망/온프레미스 배포본은 전부 점검 대상.

---

## 4. 수정 내용

`src/common/services/redis.service.ts` 한 파일만 수정. **공개 메서드 시그니처·반환값 전부 동일**하므로 호출부(코칭·VOC·STT·소켓) 코드는 변경 없음.

### 4-1. 추가된 상수

```ts
/** quit() 응답 대기 상한. half-open 소켓에서는 QUIT 응답이 영영 오지 않는다. */
private static readonly QUIT_TIMEOUT_MS = 3000;          // :42

/** 재접속 전체 상한(최후의 안전망). 정상 경로 상한: quit 3s×2 + connect 10s×2 ≈ 26s */
private static readonly RECONNECT_WATCHDOG_MS = 60000;   // :49
```

### 4-2. 추가된 헬퍼

| 위치 | 이름 | 역할 |
|---|---|---|
| `:54` | `describeError()` | 에러 메시지를 한 줄 문자열로 (로그 첫 줄에 원인 노출) |
| `:62` | `withTimeout()` | Promise 타임아웃. 기존 `pingWithTimeout` 의 중복 구현을 흡수 |
| `:79` | `closeClientSafely()` | `quit()` 타임아웃 → 초과 시 `disconnect()` 강제 종료 |
| `:114` | `ensureClientReady()` | 실제 소켓 상태(`isOpen`)까지 확인 + 닫혀 있으면 백그라운드 재접속 |

### 4-3. 원인 A 수정 — `quit()` 타임아웃 (핵심)

```ts
private async closeClientSafely(client, label): Promise<void> {
  if (!client?.isOpen) return;
  try {
    await RedisService.withTimeout(client.quit(), QUIT_TIMEOUT_MS, `${label} quit`);
  } catch (error) {
    this.logger.warn(`${label} 정상 종료 실패 → 소켓 강제 종료: ...`);
    try {
      if (client.isOpen) await client.disconnect();   // 응답 안 기다리고 소켓 파기
    } catch (destroyError) { /* 무시 */ }
  }
}
```

`performReconnect()` (`:597`) 의 기존 연결 정리 블록을 이 헬퍼 호출 2줄로 교체.

### 4-4. 원인 B 수정 — 재접속 워치독 (`reconnect()` `:563`)

```ts
const attempt = this.performReconnect();
this.reconnectPromise = attempt;

// 재접속이 끝나지 않아도 반드시 진행 중 플래그를 푼다.
void attempt.finally(() => {
  if (this.reconnectPromise === attempt) this.reconnectPromise = null;
});

try {
  return await RedisService.withTimeout(attempt, RECONNECT_WATCHDOG_MS, 'Redis 재접속');
} catch (error) {
  this.logger.error(`❌ Redis 재접속 워치독 발동(다음 헬스체크에서 재시도): ...`);
  if (this.reconnectPromise === attempt) this.reconnectPromise = null;
  return false;
}
```

이제 어떤 이유로 재접속이 멈춰도 **최대 60초 뒤에는 헬스체크가 다시 시도**한다. 영구 고착이 구조적으로 불가능해진다.

### 4-5. 원인 C 수정 — 연결 판정을 `ready` 기준으로

```ts
this.client.on('connect', () => { /* 소켓만 붙음 — 로그만 */ });   // :241
this.client.on('ready',   () => { this.isConnected = true; });     // :247
this.client.on('reconnecting', () => { this.isConnected = false; });
this.client.on('end',     () => { this.isConnected = false; });    // :256
```

추가 안전망으로 `await this.client.connect()` 직후에도 `this.isConnected = true` 를 명시적으로 세팅한다. `ready` 이벤트가 유실돼도 연결로 잡히게 하기 위함.

### 4-6. 명령 실행 전 실제 소켓 상태 확인

```ts
private ensureClientReady(): boolean {
  if (this.isConnected && this.client?.isOpen) return true;
  // 초기화조차 안 된 상태(설정 없음)에서는 재접속을 시도하지 않는다.
  if (this.client && !this.client.isOpen) void this.reconnect();  // 중복 호출은 reconnect 가 합침
  return false;
}
```

`publish` / `hGetAll` / `zRange` / `zCard` / `hSet` / `hSetMultiple` 의 사전 검사를
`if (!this.isConnected)` → `if (!this.ensureClientReady())` 로 교체.
`subscribe()` 는 구독 클라이언트를 쓰므로 `!this.subscriber?.isOpen` 으로 별도 확인.

> 이 변경의 부수 효과로, 소켓이 닫혀 있으면 **다음 명령 호출이 곧바로 복구를 트리거**한다.
> 헬스체크 주기(30초)를 기다릴 필요가 없어진다.

### 4-7. 로그 개선

- 에러 메시지를 **로그 첫 줄에** 포함 (`... 실패: The client is closed`)
  - 기존에는 스택이 다음 줄로 이어져 `grep` 한 번에 원인이 안 보였다
- 스택은 2번째 인자로 계속 전달 → 상세 추적은 그대로 가능

---

## 5. 이식 체크리스트 (다른 레포 작업용)

대상 레포의 Redis 서비스에서 아래를 확인한다.

- [ ] **연결 정리에 `await client.quit()` 이 타임아웃 없이 있는가** → 있으면 필수 수정 (원인 A)
- [ ] **"재접속 진행 중" 가드가 있는가** (`if (reconnectPromise) return`) → 있으면 워치독 필수 (원인 B)
- [ ] **`isConnected` 를 `connect` 이벤트로 잡는가** → `ready` 로 변경 (원인 C)
- [ ] 명령 사전 검사가 플래그만 보는가 → `client.isOpen` 도 확인
- [ ] 헬스체크(PING + 타임아웃)가 있는가 → 없으면 half-open 감지 자체가 안 되므로 먼저 추가
- [ ] 메인/구독 클라이언트를 분리해 쓰는가 → 양쪽 모두 위 항목 점검

### 관련 설정 (참고)

```
REDIS_HEALTH_CHECK_INTERVAL=30000   # PING 주기. NLB idle timeout(약 350초)보다 짧게
```

`redisConfig.health_check_interval` 은 헬스체크 주기와 node-redis `pingInterval` 양쪽에 쓰인다.

---

## 6. 검증 방법

### 6-1. 정적 검증

```bash
npx tsc --noEmit -p tsconfig.json     # 타입 에러 0
npx eslint src/common/services/redis.service.ts
```

### 6-2. 기동 로그 (정상)

```
✅ Redis 메인 클라이언트 연결됨 (ready)
✅ Redis 구독 클라이언트 연결됨 (ready)
🩺 Redis 자가 헬스체크 시작 (30000ms 주기)
[Redis] Subscribed: coaching:request (total: N)
```

`(ready)` 표기가 붙어야 수정본이 적용된 것이다.

### 6-3. 연결 끊김 시 자가 복구 로그 (수정 후 기대값)

```
🩺 Redis PING 무응답(half-open 의심) → 자동 재연결: PING timeout
🔄 Redis 재접속 시도 시작...
기존 메인 클라이언트 정상 종료 실패 → 소켓 강제 종료: 기존 메인 클라이언트 quit timeout   ← 버그가 잡히는 지점
✅ Redis 재접속 성공
✅ 구독 복구 성공: coaching:request
```

3번째 줄이 **기존에 10시간 30분 멈춰 있던 자리**다. 이제 3초 후 강제 종료하고 진행한다.

### 6-4. 장애 진단용 명령 (재발 시)

```bash
# 실제 에러 메시지 확인
docker logs <container> 2>&1 | grep -iE "redis" | tail -60

# 재접속이 시작만 하고 안 끝났는지 확인 (핵심 판정)
docker logs <container> 2>&1 | grep -E "🩺|재접속|Subscribed" | tail -20
#   "🔄 재접속 시도 시작" 뒤에 "✅ 성공" / "❌ 실패" 가 없으면 데드락

# 컨테이너 안에서 직접 발행 테스트 (원인 문자열이 그대로 출력됨)
docker exec <container> node -e "
const {createClient}=require('redis');
const c=createClient({socket:{host:process.env.REDIS_HOST,port:+process.env.REDIS_PORT,tls:process.env.REDIS_TLS==='true',rejectUnauthorized:false},password:process.env.REDIS_PASSWORD,database:+process.env.REDIS_DB});
c.on('error',e=>console.log('ERR:',e.message));
c.connect().then(()=>c.publish('coaching:request','{\"test\":1}'))
 .then(r=>console.log('PUBLISH OK, subscribers =',r))
 .catch(e=>console.log('PUBLISH FAIL:',e.message))
 .finally(()=>process.exit(0));"
```

마지막 명령이 `subscribers = 0` 으로 **성공**하면 발행은 되는데 구독자가 없는 것이고,
`PUBLISH FAIL: The client is closed` 면 이 문서의 장애다.

---

## 7. 요약

| 항목 | 내용 |
|---|---|
| 표면 증상 | 코칭·VOC 만 전달 안 됨 |
| 실제 원인 | Redis **메인 클라이언트** 연결 끊김 + **자동 복구 데드락** |
| 데드락 지점 | `performReconnect()` 의 `await client.quit()` (타임아웃 없음) |
| 고착 이유 | 끝나지 않는 `reconnectPromise` 때문에 헬스체크가 영구 스킵 |
| 발현 조건 | half-open 으로 끊기는 환경 (사내망/NAT). AWS NLB 환경에서는 미발현 |
| 수정 범위 | `src/common/services/redis.service.ts` 1개 파일, 호출부 변경 없음 |
| 복구(응급) | 컨테이너 재시작 |
