# [이식 요청] Redis failover 대응 3건

- **작성일**: 2026-07-28
- **원본 레포**: asst-service (어드바이저 백엔드)
- **대상 파일**: `src/common/services/redis.service.ts`, `src/config/redis.config.ts` — **이 2개뿐**
- **건드리지 않는 것**: 소켓, 코칭, VOC, 그 외 모든 비즈니스 로직

---

## 0. 먼저 이것부터 실행해 주세요 (적용 여부 판별)

**"이미 다 한 작업"으로 오해되는 사례가 있었습니다.** 아래 3개는 **2026-07-28에 새로 만든 것**이라 그 이전에 존재할 수 없습니다. 아래 명령으로 객관적으로 확인해 주세요.

```bash
grep -c "checkWritablePrimary"     src/common/services/redis.service.ts   # 0 이면 미적용 → 수정 1 필요
grep -c "PUBLISH_RETRY_DELAYS_MS"  src/common/services/redis.service.ts   # 0 이면 미적용 → 수정 2 필요
grep -c "180000"                   src/config/redis.config.ts             # 1 이상이면 미적용 → 수정 3 필요
```

### ⚠️ 이 요청과 혼동하기 쉬운 것 (= 이번 요청이 **아님**)

아래는 **예전에 이미 이식된** 항목들입니다. 이게 있다고 해서 이번 3건이 된 것이 아닙니다.

| 이미 되어 있을 항목 | 식별자 |
|---|---|
| 무한 재연결 (10회 포기 버그 수정) | `reconnectStrategy` |
| 연결 판정을 `ready` 기준으로 | `.on('ready'` |
| half-open 감지 (PING + 타임아웃) | `pingWithTimeout`, `PING_TIMEOUT_MS` |
| 재연결 후 구독 자동 복구 | `savedSubscriptions` |
| `quit()` 무한대기 데드락 수정 | `closeClientSafely`, `QUIT_TIMEOUT_MS` |
| 재접속 워치독 | `RECONNECT_WATCHDOG_MS` |

이번 요청은 **위 목록에 없는 3건**입니다.

---

## 수정 1. 헬스체크에 ROLE 검사 추가 (replica 고착 감지)

### 왜 필요한가

sentinel failover 후 DNS가 구 마스터(승격되어 이제 replica)를 계속 가리키는 동안 재연결이 성공하면, **소켓·handshake·PING·SUBSCRIBE가 전부 정상으로 보입니다.** replica도 PONG을 응답하고 pub/sub도 동작하기 때문입니다. 그런데 **쓰기만 READONLY로 실패**합니다.

기존 헬스체크는 PING만 하므로 이 상태를 정상으로 오판하고, **자가복구가 영원히 발동하지 않습니다.** "반쯤 살아있는" 상태로 고착됩니다.

**실제 영향:**
- VOC 중복 방지 락(`SET NX`)이 실패 → fail-open 통과 → **중복 발행이 계속됨**
- VOC 발행(`publish`), 상담사 상태(`HSET`) 실패

### 코드

**파일**: `src/common/services/redis.service.ts`

**① 클래스 필드 추가** — `healthCheckTimer` 선언 아래

```ts
  /**
   * 연속으로 replica 접속이 감지된 횟수와, 다음 재연결을 시도할 회차.
   * failover 후 DNS 가 아직 새 마스터로 갱신되지 않았다면 재연결해도 다시
   * 같은 replica 에 붙는다. 그런데 재연결은 구독을 끊었다 다시 맺으므로, 매 헬스체크마다
   * 재연결하면 그 간격마다 pub/sub 메시지 유실이 반복된다(고착보다 나쁨).
   * 그래서 1·2·4·8... 회차에서만 재시도하도록 백오프한다. 마스터 복귀 시 초기화.
   */
  private replicaDetectStreak = 0;
  private nextReplicaReconnectAt = 1;

  /** ROLE 응답 대기 상한(마스터 접속 여부 확인용) */
  private static readonly ROLE_TIMEOUT_MS = 3000;
```

**② `checkHealthAndHeal()` 수정** — PING 실패 분기에 `return` 추가하고, 끝에 3단계 호출 추가

```ts
    // 2) half-open 감지: PING에 타임아웃을 걸어 무응답이면 죽은 연결로 판단
    try {
      await this.pingWithTimeout();
    } catch (error) {
      this.logger.warn(
        `🩺 Redis PING 무응답(half-open 의심) → 자동 재연결: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      await this.reconnect();
      return;                              // ★ 추가
    }

    // 3) 쓰기 가능 여부(마스터 접속) 확인 — PING 만으로는 절대 감지되지 않는 구간
    await this.checkWritablePrimary();     // ★ 추가
  }
```

**③ 메서드 신규 추가**

```ts
  /**
   * 메인 클라이언트가 마스터에 붙어 있는지 ROLE 로 확인하고, replica 면 재연결한다.
   * ROLE 확인 자체가 실패하면 재연결하지 않는다(일시 오류로 멀쩡한 연결을 끊지 않기 위함).
   */
  private async checkWritablePrimary(): Promise<void> {
    let role: string;
    try {
      const result = await RedisService.withTimeout(
        this.client.sendCommand(['ROLE']),
        RedisService.ROLE_TIMEOUT_MS,
        'ROLE',
      );
      // ROLE 응답의 첫 요소가 'master' | 'slave' | 'sentinel'
      role = Array.isArray(result) ? String(result[0]) : '';
    } catch (error) {
      this.logger.warn(
        `🩺 Redis ROLE 확인 실패(연결은 유지): ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      return;
    }

    if (role === 'master') {
      if (this.replicaDetectStreak > 0) {
        this.logger.log(
          `✅ Redis 마스터 접속 복구됨 (replica 감지 ${this.replicaDetectStreak}회 후)`,
        );
      }
      this.replicaDetectStreak = 0;
      this.nextReplicaReconnectAt = 1;
      return;
    }

    this.replicaDetectStreak++;
    this.logger.error(
      `🩺 Redis 쓰기 불가 상태 감지: ROLE=${role || 'unknown'} (replica 접속). ` +
        `failover 후 DNS 미갱신 의심 — 연속 ${this.replicaDetectStreak}회`,
    );

    if (this.replicaDetectStreak < this.nextReplicaReconnectAt) {
      return; // 백오프 구간 — 재연결로 구독을 반복해서 끊지 않는다
    }

    this.nextReplicaReconnectAt = this.replicaDetectStreak * 2;
    this.logger.warn('🔄 replica 고착 해소를 위해 재연결 시도');
    await this.reconnect();
  }
```

> **백오프가 왜 필요한가**: DNS가 갱신되지 않은 동안 매 주기마다 재연결하면, 재연결할 때마다 구독이 끊겼다 붙으면서 **오히려 메시지 유실이 반복됩니다.** 고착 상태보다 나쁩니다. 이 백오프를 빼고 이식하지 마세요.

> **의존**: `RedisService.withTimeout` 헬퍼가 이미 있어야 합니다(기존 코드에 존재). 없다면 먼저 확인해 주세요.

---

## 수정 2. `publish()` 재시도 추가 (단, 중복은 절대 만들지 않음)

### 왜 필요한가

failover 순간 `publish()`가 실패하면 기존 코드는 로그만 남기고 메시지를 버렸습니다. pub/sub은 재전송이 없어 **영구 소실**됩니다. (예: 슈퍼바이저가 보낸 코칭이 상담사에게 영영 안 감)

### ★ 핵심 설계 — 이 부분을 반드시 그대로 지켜주세요

재시도는 **"아직 명령을 보낸 적이 없음이 확실한 경우"에만** 합니다.

전송 후 응답만 못 받은 상황에서 재시도하면 구독자가 같은 메시지를 **두 번** 받습니다. 코칭 알림은 프론트에서 토스트·알림음 같은 1회성 부수효과를 유발하므로 중복이 사용자에게 그대로 보입니다. **유실 방지보다 중복 방지를 우선해 at-most-once를 유지합니다.**

`catch` 블록에서 재시도하도록 바꾸면 이 설계가 깨집니다.

### 코드

**파일**: `src/common/services/redis.service.ts`

**① 상수 추가**

```ts
  /**
   * 발행 재시도 간 대기(ms). 길이 + 1 이 총 시도 횟수가 된다(= 3회).
   * publish 는 HTTP 요청 경로에서 호출되므로 총 추가 지연을 700ms 로 묶는다.
   * ★ 재시도는 "아직 명령을 보낸 적이 없음이 확실한 경우"에만 한다(아래 publish 구현 참고).
   *   전송 후 응답만 못 받은 상황에서 재시도하면 구독자가 같은 메시지를 두 번 받는다.
   */
  private static readonly PUBLISH_RETRY_DELAYS_MS = [200, 500];
```

**② `publish()` 전체 교체**

```ts
  async publish(channel: string, message: string): Promise<boolean> {
    const maxAttempts = RedisService.PUBLISH_RETRY_DELAYS_MS.length + 1;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      // 재시도는 여기(미연결 확인)에서만 일어난다.
      // ensureClientReady()가 false 라는 것은 명령을 아직 보낸 적이 없다는 뜻이므로,
      // 대기 후 다시 시도해도 구독자가 메시지를 두 번 받을 일이 없다.
      // (ensureClientReady 는 끊긴 상태면 내부에서 재접속을 걸어두므로, 대기 중 복구되면 성공한다)
      if (this.ensureClientReady()) {
        try {
          const result = await this.client.publish(channel, message);
          if (attempt > 1) {
            this.logger.log(
              `✅ 채널 ${channel} 발행 성공 (${attempt}번째 시도)`,
            );
          }
          this.logger.debug(
            `채널 ${channel}에 메시지 발행 완료 (수신자: ${result}명)`,
          );
          return true;
        } catch (error) {
          // 여기서 실패했다면 명령이 Redis 에 도달했는지 알 수 없다(전달은 됐고 응답만 유실됐을 수 있음).
          // 재시도하면 중복 발행이 되므로 재시도하지 않고 즉시 실패로 끝낸다.
          this.logger.error(
            `채널 ${channel} 메시지 발행 실패 (전송 여부 불명 — 중복 방지를 위해 재시도 안 함): ${RedisService.describeError(
              error,
            )}`,
            error instanceof Error ? error.stack : undefined,
          );
          return false;
        }
      }

      const delayMs = RedisService.PUBLISH_RETRY_DELAYS_MS[attempt - 1];
      if (delayMs === undefined) {
        break; // 마지막 시도까지 미연결
      }
      this.logger.warn(
        `채널 ${channel} 발행 보류 — Redis 미연결(재접속 시도 중). ${delayMs}ms 후 재시도 (${attempt}/${maxAttempts})`,
      );
      await RedisService.delay(delayMs);
    }

    this.logger.error(
      `채널 ${channel} 메시지 발행 최종 실패 (${maxAttempts}회 시도): Redis 미연결`,
    );
    return false;
  }

  /** 재시도 간 대기 */
  private static delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
```

### 동작 정리

| 상황 | 동작 | 중복 가능성 |
|---|---|---|
| 평상시 | 1회 성공 → 재시도 코드 미실행 | — |
| Redis 미연결 (끊긴 걸 인지한 상태) | 200ms → 500ms, 최대 3회 | **0** (전송한 적 없음이 확실) |
| `publish()` 중 예외 (전송 여부 불명) | 즉시 실패, 재시도 안 함 | **0** |

> **의존**: 기존 `ensureClientReady()`, `RedisService.describeError()` 를 그대로 사용합니다.

---

## 수정 3. 헬스체크 주기 180초 → 30초

### 왜 필요한가

`REDIS_HEALTH_CHECK_INTERVAL` 기본값 180초는 sentinel failover(보통 10~30초)보다 훨씬 길어, 마스터가 바뀌어도 **최대 3분간** 그 사실을 모른 채 half-open / replica 고착 상태로 남습니다. 수정 1의 ROLE 검사도 이 주기로 돌기 때문에, 이 값을 안 바꾸면 수정 1의 효과가 3분 지연됩니다.

### 코드

**파일**: `src/config/redis.config.ts`

```ts
  health_check_interval: parseInt(
    process.env.REDIS_HEALTH_CHECK_INTERVAL || '30000',   // ★ 180000 → 30000
    10,
  ),
  // 기본값: 30초.
  // - NLB idle timeout(약 350초)보다 짧아 keepalive 역할은 그대로 유지된다.
  // - 이전 값 180초는 failover(10~30초)보다 훨씬 길어 최대 3분간 장애를 인지하지 못했다.
  // - 비용은 주기당 PING 2회(client/subscriber)로 무시 가능하다.
```

`.env`에 명시적으로 넣어도 됩니다. **변수명 오타(`EDIS_...`)에 주의하세요.**

```
REDIS_HEALTH_CHECK_INTERVAL=30000
```

---

## 적용 후 확인

```bash
npx tsc --noEmit -p tsconfig.json
npx eslint src/common/services/redis.service.ts src/config/redis.config.ts
```

원본 레포 기준 타입체크·린트 통과했습니다.

### 평상시 동작 영향

| 수정 | 평상시 |
|---|---|
| ROLE 검사 | 30초마다 명령 1회 추가. 결과가 `master`면 아무 동작 없음 |
| 주기 30초 | PING이 6배 잦아짐 |
| publish 재시도 | **완전히 동일** — 첫 시도 성공 시 재시도 코드를 타지 않음 |

파드당 하루 추가 명령 약 7,680회로 전체 처리량 대비 **0.3%**. 기존 기능 동작은 바뀌지 않습니다.

### 미검증 항목

**실제 failover 동작은 검증하지 못했습니다.** `REDIS_HOST`를 replica로 직접 지정하면 ROLE 검사가 걸리는지 로그로 확인할 수 있습니다.

---

## 문의

상세 배경(Redis 인프라 현황, 이중화 진단, 남은 과제)은 아래 문서를 참고하세요.

`docs/2026-0728_redis-이중화-대비-점검-및-조치.md`

단, 그 문서의 **3장은 "이미 되어 있던 것" 정리**이므로 이식 대상이 아닙니다. 이식 대상은 그 문서의 4장 = 이 문서의 수정 1·2·3입니다.
