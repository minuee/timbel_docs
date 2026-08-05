# 실시간 이벤트 중복 수신 방어 (socket.io redis-message)

> 출처: 백엔드(asst-service) 프론트엔드 전달문 — "코칭 실시간 알림 중복 수신 방어 요청" (2026-07-28)
> 구현 완료: `asst-web-portal`
> **redis-message 를 받아 토스트/알림음/카운터를 다루는 모든 프론트 레포에 동일 적용 필요.**

---

## 1. 왜 필요한가

socket.io 서버에 **`connectionStateRecovery`(최대 2분)** 가 켜져 있다.
짧은 연결 끊김 후 복원되는 과정에서 **이미 처리한 이벤트가 다시 전달될 수 있다.**
백엔드 다중화(파드 2개 이상) 시에도 중복 경로가 생긴다.

백엔드도 발행 단계 중복은 별도로 막지만, **재연결 복원 경로는 프론트에서 방어**해야 한다.

---

## 2. 무엇을 막고, 무엇을 막지 않나 — 이게 핵심

이 구분을 틀리면 중복은 막았는데 데이터가 안 맞거나, 반대로 알림이 겹쳐 보인다.

| 구분 | 예 | 중복 시 |
|---|---|---|
| **멱등한 처리** | 목록 재조회, 미확인 카운트 재조회 | ⭕ **그대로 수행** — 두 번 해도 결과가 같아 무해 |
| **1회성 부수효과** | 토스트, 알림음, 뱃지 애니메이션, **로컬 카운터 증가** | ❌ **반드시 차단** — 이벤트 수만큼 발생해 사용자 눈에 보인다 |

즉 코드 배치는 이 순서다.

```ts
refreshList();                     // 멱등 → dedupe 앞

if (dedupe.isDuplicate(key)) return;   // ← 경계선

incrementBadgeCounter();           // 1회성 → dedupe 뒤
showToast();
```

> ⚠️ **탭 알림 카운터를 쓴다면 반드시 dedupe 뒤에 두라.**
> (`advisor-tab-alert-implementation-guide.md` 의 `bgNewCount`)
> 중복 3건이면 타이틀이 `🚨 코칭 3건` 이 되어 그대로 노출된다.

---

## 3. 키 규격 (백엔드 지정)

```
`${message.type}:${message.coaching_id ?? message.coaching_request_id}`
```

- `coaching_created` 에는 **두 id 가 함께 올 수 있다** → `coaching_id` 우선
- **id 가 없는 메시지는 dedupe 하지 않고 그대로 처리한다** (방어적 케이스)
- `0` 은 유효한 id 다. `!id` 로 거르면 안 된다

### 페이로드 형태

```json
{
  "channel": "dev:4609686:<receiver_key>:coaching",
  "message": {
    "type": "coaching_created",          // 또는 "coaching_request_created"
    "receiver_key": "...",
    "sender_key": "...",
    "coaching_id": 123,                  // coaching_created 일 때
    "coaching_request_id": 456,          // 양쪽 모두 존재 가능
    "call_id": "...",
    "is_important": true,
    "priority_type": "...",
    "created_at": "2026-07-28T..."
  }
}
```

---

## 4. 유틸 전문 (`src/utils/eventDedupe.ts`) — 그대로 복사

프레임워크 비의존. TTL 5분 / 상한 200건.

```ts
const DEFAULT_TTL_MS = 5 * 60 * 1000; // 5분
const DEFAULT_MAX_SIZE = 200;

export interface EventDedupe {
  /** 이미 처리한 키면 true. 처음 보는 키면 등록하고 false. 키가 없으면(null/빈값) 항상 false. */
  isDuplicate(key: string | null | undefined): boolean;
  reset(): void;
  size(): number;
}

export function createEventDedupe(options?: { ttlMs?: number; maxSize?: number }): EventDedupe {
  const ttlMs = options?.ttlMs ?? DEFAULT_TTL_MS;
  const maxSize = options?.maxSize ?? DEFAULT_MAX_SIZE;

  /** key → 만료시각(ms). 삽입 순서 = 만료 순서. */
  const seen = new Map<string, number>();

  const prune = (now: number) => {
    for (const [key, expiresAt] of seen) {
      if (expiresAt > now) break; // 가장 오래된 것부터 도는데 안 만료됐으면 뒤도 전부 유효
      seen.delete(key);
    }
    while (seen.size > maxSize) {
      const oldest = seen.keys().next();
      if (oldest.done) break;
      seen.delete(oldest.value);
    }
  };

  return {
    isDuplicate(key) {
      // id 가 없는 메시지(방어적 케이스)는 dedupe 하지 않고 그대로 처리한다.
      if (!key) return false;

      const now = Date.now();
      prune(now);

      if (seen.has(key)) return true;

      seen.set(key, now + ttlMs);
      prune(now);
      return false;
    },
    reset() {
      seen.clear();
    },
    size() {
      return seen.size;
    }
  };
}

/** 백엔드 지정 키 규격. coaching_created 는 두 id 가 함께 올 수 있어 coaching_id 우선. */
export function coachingEventKey(msg: any): string | null {
  const type = msg?.type;
  if (!type) return null;

  const id = msg?.coaching_id ?? msg?.coaching_request_id;
  if (id === undefined || id === null || id === "") return null;

  return `${type}:${id}`;
}

/**
 * 코칭 이벤트 전용 **공유 싱글턴**.
 * 컴포넌트 안에서 만들면 화면 재진입마다 기록이 비어 복원 이벤트를 새 것으로 오인한다.
 * 키에 type 과 id 가 모두 들어가 화면끼리 섞여도 안전하다.
 */
export const coachingEventDedupe = createEventDedupe();
```

### 자료구조 메모
`Map` 은 삽입 순서를 보존하고 TTL 이 고정이라 **삽입 순서 = 만료 순서**가 성립한다.
그래서 앞에서부터 돌다가 **안 만료된 첫 항목에서 `break`** 하면 된다(전체 순회 아님).
TTL 로도 안 줄면 오래된 순으로 잘라 상한을 지킨다 → 메모리 누수 방지.

---

## 5. 적용 방법

수신 핸들러에서 두 줄이면 끝난다.

```ts
import { coachingEventDedupe, coachingEventKey } from "@/utils/eventDedupe";

const handleCoachingRedisMessage = (data: any) => {
  try {
    // ...기존 채널/타입/수신자 필터 그대로...

    // 목록/카운트 재조회는 멱등이라 중복 수신이어도 그대로 수행한다.
    coachingStore.refreshCoachings(false);

    // 재연결 복원 등으로 같은 이벤트가 다시 오면 여기서 끊는다.
    if (coachingEventDedupe.isDuplicate(coachingEventKey(msg))) {
      console.log("중복 코칭 이벤트 → 알림 생략", msg?.coaching_id ?? msg?.coaching_request_id);
      return;
    }

    notifyTabAlert();          // 1회성: 백그라운드 탭 알림 카운터
    showCustomMessage({ ... }); // 1회성: 토스트
  } catch (error) { /* ... */ }
};
```

**적용 대상은 "코칭 토스트를 띄우는 수신 지점 전부"** 다.
`asst-web-portal` 기준 3곳이었다 — 관리자 화면 / 상담사 화면 / 리뉴얼 모니터링 화면.
같은 이벤트를 여러 화면이 각자 듣고 있는 구조라면 **한 곳만 고치면 다른 화면에서 중복이 그대로 보인다.** 먼저 전수 조사할 것.

```bash
grep -rn "redis-message" src --include="*.vue" --include="*.ts"
grep -rn "coaching_created\|coaching_request_created" src
```

> 채팅·상담사 상태 등 **다른 `redis-message` 소비처는 이번 범위가 아니다**(코칭 이벤트만 필터되어 들어옴).
> 필요해지면 같은 유틸에 키 함수만 새로 만들면 된다.

---

## 6. 검증

### 자동 (로직만 떼어내 노드로)
`asst-web-portal` 에서 16케이스 통과 확인. 이식 후에도 같은 항목을 확인하면 된다.

- 키: `coaching_id` 우선 / `coaching_id: 0` 도 유효 / id 없으면 `null`
- 중복 차단, 같은 id 라도 **type 다르면 통과**
- **id 없는 메시지는 몇 번이 와도 미차단**
- **TTL 만료 후 재알림** (같은 코칭이 5분 뒤 또 오면 정상 알림)
- 상한 유지 + 오래된 키가 밀려나 다시 처리됨

### 수동
1. 코칭/코칭요청 전송 → 토스트 **1회**
2. 개발자도구 Network → **Offline 잠깐 켰다 끄기** (connectionStateRecovery 경로 유발)
3. 복원 직후 **토스트가 다시 뜨지 않는지**, 탭 알림 카운트가 안 늘어나는지
4. 목록/미확인 배지는 정상 최신화되는지 (재조회는 막지 않았으므로 유지되어야 정상)
