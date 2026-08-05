# 2026-08-04 DB 커넥션 고갈 (`sorry, too many clients already`)

## 증상

```
[DbCleanupInterceptor] GET /api/asst/v1/keyword-detects?limit=1000&withStats=true
  → sorry, too many clients already   (PostgreSQL 53300)
[DynamicDatabaseService] 정적 DB 연결 무효화됨, 재생성   ← 같은 초에 반복 출력
```

DB(124.194.32.36:62070)가 완전히 포화되어 psql 접속조차 불가능한 상태까지 갔다.

---

## 원인

`DynamicDatabaseService.getStaticConnection()` 에 잠복 버그가 **둘** 있었다.
둘 다 원래 있던 코드이며, 오늘 작업이 방아쇠였다.

### ① 캐시 저장 시점이 늦어 동시 요청이 각자 풀을 만듦

```ts
const ds = new DataSource(...);
await ds.initialize();            // 수백 ms
await runSchemaMigrations(ds);    // DDL 여러 개, 더 오래
connections.set('static', ds);    // ← 여기서야 저장
```

저장 전에 들어온 요청은 캐시가 비어 보이므로 각자 DataSource 를 생성한다.
하나당 풀 10개. **Map 에는 마지막 하나만 남고 나머지는 참조를 잃은 채 커넥션을 계속 붙잡는다**
(`destroy()` 호출 없음). 풀 설정이 `min: 2` 라 주인 잃은 풀 하나당 2개씩 영구 점유.

### ② 호출마다 `SELECT 1`, 실패하면 풀을 버리고 재생성 → 죽음의 나선

```
포화 → SELECT 1 실패 → "연결이 끊겼다"고 판단 → 멀쩡한 풀 destroy
     → 새 풀 10개 요구 → 또 실패 → 다음 요청이 반복
```

실패 원인이 **연결 단절이 아니라 서버 포화**인데 전자로 간주했다.
한 번 빠지면 요청이 들어올수록 더 요구해서 스스로 회복하지 못한다.

### 왜 하필 오늘 터졌나

두 버그 모두 `getStaticConnection` 호출이 드물 때(HTTP 요청당 1회)는 드러나지 않았다.
오늘 작업이 호출 빈도를 크게 올렸다.

- **감지어 탐지가 발화마다** `resolveDataSource()` 호출 (`REALTIME_VOC_INTERVAL=1` 이라 VOC 도 매 발화)
- `GET /keyword-detects?withStats=true` 는 리포지토리를 둘 잡아 **요청당 `getConnection` 2회**
- `GET /keyword-detect-logs` 신설 — 요청당 여러 회
- `runSchemaMigrations` 에 `keyword_detect_logs` 생성 블록(테이블 + 인덱스 3) 추가 → ①의 창이 넓어짐

---

## 조치 (2026-08-04 적용)

`src/common/services/dynamic-database.service.ts`

1. **single-flight** — `staticConnectionPromise` 를 두어 생성 중이면 그 Promise 를 공유.
   DataSource 가 한 번만 만들어진다.
2. **호출별 `SELECT 1` 유효성 검사 제거** — `isInitialized` 만 보고 재사용.
   끊어진 커넥션은 풀이 걸러내고, 진짜 실패면 그 쿼리가 예외를 낸다.
   부수 효과로 DB 접근마다 붙던 왕복 1회도 사라졌다.

> 두 수정이 함께 배포되어 어느 쪽이 결정적이었는지는 단정할 수 없다.
> 다만 나선을 끊은 것은 ② 제거로 보인다 — ②가 남아 있으면 재시작해도 다시 찼을 것이다.

---

## 사고 당시 커넥션 현황 (max_connections = 100)

```
idle 97 / active 1
```

| 출처 | 개수 | 비고 |
|---|---|---|
| **DBeaver (사람이 켜둔 GUI)** | 약 21 | `106.242.165.140` 14, `61.32.218.74` 7 |
| `128.1.4.13` | 17 | **oldest 09:19:01 — 나선 발생 시각과 일치.** asst-service 잔재로 추정 |
| `128.1.4.25` | 15 | oldest 17:52 |
| `128.1.4.4` | 11 | 07-31부터 상주 |
| 기타 컨테이너 | 8 | 07-31 ~ 08-03 |

**우리 서비스 누수만의 문제가 아니었다.** DBeaver 21개가 상시로 20%를 점유 중이고,
`max_connections=100` 은 이 환경(서비스 여럿 + 사람 접속 + 서비스당 풀 10)에 빠듯하다.

---

## 재발 시 대응 순서

1. 커넥션 점유자 확인
   ```sql
   show max_connections;
   select client_addr, application_name, count(*), min(backend_start) AS oldest
   from pg_stat_activity where state = 'idle'
   group by 1,2 order by 3 desc;
   ```
2. **DBeaver 창 닫기** — 즉시 20개 안팎 회수
3. **asst-service 재시작** — 주인 잃은 풀 회수 (반드시 수정본 배포 후에)
4. 재시작 후 우리 서비스 커넥션이 10개 안쪽인지 확인. 그래도 많으면 인스턴스가 여러 개 떠 있는지 점검

---

## 남은 과제

- **동일 패턴이 테넌트 연결 경로 2곳에 그대로 있다** — `getConnection(token)`(166→172),
  `getConnectionByVendor`(323→325). 현재 `DB_DIRECT_CON=1` 이라 타지 않지만
  **멀티테넌트 전환 시 동일 장애가 재현된다.**
- **`application_name` 미설정** — 어느 컨테이너인지 IP 로 추측해야 한다.
  DataSource `extra` 에 `application_name: 'asst-service'` 를 넣으면 즉시 식별된다.
- **`max_connections=100` 상향 또는 풀 크기 축소**(현재 `max: 10`, `min: 2`, `poolSize: 10`) 검토.
- **감지어의 연결 획득 횟수 축소** — 사전은 캐시하는데 연결은 발화마다 새로 잡는다.
- `128.1.4.13` / `128.1.4.25` 두 IP 의 정체 확인 — 구버전 인스턴스가 남아 있는지.
