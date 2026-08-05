# 어드바이저 백엔드 캐시 / 검색엔진 도입 검토

- 작성일: 2026-07-24
- 대상: `asst-service-portal` (branch: develop)
- 배경: "이 백엔드에 캐시 시스템·검색엔진이 있는가, 없다면 도입이 필요한가" 검토

---

## 1. 결론 요약

| 항목 | 결론 |
|---|---|
| 검색엔진(ES 등) 도입 | **불필요.** 지식검색은 이미 AICM 뒤 ES가 담당, 이 백엔드는 프록시. 자체 도입 시 인덱스 이중화 |
| 전용 캐시 서버(Redis 캐시) | **현 시점 불필요.** 사용자 수십 명 + `replicas: 1` 단일 인스턴스 |
| 부분 캐시 | **필요한 곳만.** 규모가 아니라 "요청마다 반복되는 외부 왕복"을 없애는 목적 |

한 줄로: **검색엔진은 도입하지 않음, 캐시는 필요한 지점만 얇게.**

---

## 2. 현재 실태 (조사 결과)

### 2.1 범용 캐시 계층 — 없음

- `@nestjs/cache-manager` / `CacheModule` / `CACHE_MANAGER` — 의존성·코드 모두 0건
- TypeORM 쿼리 캐시(`cache: true`) — 0건

### 2.2 Redis는 있으나 캐시 용도가 아님

`redis: ^4.7.1` 의존성은 있지만 용도가 다릅니다.

- `src/common/services/redis.service.ts` — Pub/Sub 메시징 + 자가 헬스체크/자동 재연결
- `hGetAll` / `zRange` / `zCard` / `hSet` — 다른 서비스(코칭·NLP)가 써 둔 데이터를 **읽는** 용도
- `coaching-redis.service.ts` — publish 전용
- `redis-monitor.service.ts` — 모니터링용

→ 이 서비스가 자기 응답을 저장했다 재사용하는 read-through 캐시는 **없음**.

### 2.3 실제 캐시 = 프로세스 인메모리 Map 3곳

| 위치 | 대상 | 정리 시점 |
|---|---|---|
| `dynamic-database.service.ts:77` `connections` | 테넌트별 DataSource | 헬스체크 실패/종료 시 delete |
| `dynamic-database.service.ts:87` `vendorMeta` | `vendor_tenant_id` → 연결문자열 | **정리 경로 없음** |
| `voc-realtime.service.ts:86,92,100` | 통화 상태·토큰·업체 UUID | 통화 종료 시 states/callTokens만 delete |

특성: TTL·용량 제한 없음 / 인스턴스 간 공유 불가 / 재시작 시 소실.

### 2.4 검색

- `search.service.ts:67` → `${AICM_HOST}/api/aicm/v1/search/rag_assist` **HTTP 프록시**
- ES 접속정보 흔적은 있음: `src/common/dto/tenant-config.dto.ts:17` `EsConfigDto` (endpoint / index_name / username / password) — user-service가 테넌트별로 내려주는 값
- 실제 ES 클라이언트는 상류에: `aicm-service/requirements.txt` → `elasticsearch==8.19.0`
- 이 레포의 어떤 compose 파일에도 ES 인프라 없음

### 2.5 참고 — 상류 서비스(aicm-service)

- `redis==5.0.0` 은 **Celery 브로커/결과 백엔드** 용도 (`core/celery.py`)
- 캐시는 프로세스 내 `cachetools.TTLCache` (`managers/database_manager.py:35,88` — DB 커넥션 캐시, maxsize 500 / ttl 600s)

→ 시스템 전반에 Redis가 떠 있지만 **어디서도 캐시 스토어로 쓰지 않음.** 메시지 버스(asst) + 작업 큐(aicm) 역할.

---

## 3. 중요 정정 — 멀티테넌트 전제

검토 초반에 "요청마다 user-service 왕복이 발생한다"고 판단했으나, **현재 배포 기준으로는 틀렸습니다.**

```
.env.106.development:89   DB_DIRECT_CON=1   # 106: 테넌트 DB 미연동 → postgres 직결
.env.106.local:99         DB_DIRECT_CON=1
.env.prod:66              DB_DIRECT_CON=0   # 동적 DB 경로 (프로덕션 설정에만 존재)
```

`dynamic-database.service.ts:107-109` 에서 `DB_DIRECT_CON=1` 이면 즉시 `getStaticConnection()` 으로 빠지므로,
**106 환경에서는 `getTenantConfig()` (user-service HTTP) 자체를 호출하지 않습니다.**

즉 현재는 멀티테넌트/동적 DB 구조가 아니며, 소스만 멀티테넌트를 전제로 작성돼 있는 상태입니다.
→ 소스와 실제 구조를 맞추는 정합성 작업이 별도로 필요합니다. (본 문서 범위 밖)

### 정정 후 남는 오버헤드

멀티테넌트가 아니어도 **여전히 유효한** 항목만 추리면:

1. **`getCurrentUser(token)` — user-service HTTP 왕복**
   `DB_DIRECT_CON` 과 무관하게 그대로 발생. 호출 지점이 실시간 경로에 포함됨:
   - `voc-realtime.service.ts:730`
   - `coaching.service.ts:130`, `:184`
   - `summary.service.ts:468`, `postcall-llm.service.ts:256`, `todo.service.ts:499`, `agent.service.ts:375`

   통화 중 STT 턴마다 호출되는 경로가 있어 **호출 빈도가 가장 높음**.

2. **매 요청 `SELECT 1` 유효성 검사**
   - `dynamic-database.service.ts:374` (정적 연결 경로 — 현재 106이 타는 경로)
   - `dynamic-database.service.ts:125` (동적 경로)

   TypeORM 풀이 이미 유휴 커넥션을 관리하므로 매번 찌를 필요가 없음.

---

## 4. 권고안

### 1단계 — 지금 해도 되는 것 (인메모리 TTL)

**대상: `getCurrentUser(token)` 결과 캐시** (`user-info.service.ts`)

```
key   : 토큰 해시 (수십 명 규모면 엔트리 수십 개로 충분)
value : { user, expiresAt }
TTL   : 1~5분  (권한·소속 변경 반영 창구 확보)
필수  : in-flight 중복 제거 — 동시 요청 시 Promise 를 Map 에 공유
        (없으면 캐시 미스 순간 user-service 로 동시 N발)
주의  : 재로그인 시 토큰이 바뀌므로 이전 엔트리는 TTL 로 자연 소멸
```

**구현 방식**: 직접 `Map` 보다 `@nestjs/cache-manager` + memory store 권장.
지금은 프로세스 메모리로 동작하고, 파드를 늘릴 때 **store만 Redis로 교체**하면 되므로
캐시 사용 코드는 그대로 두고 인프라만 갈아끼울 수 있음.

**부수 작업**: `SELECT 1` 을 매 요청 → "마지막 확인 후 N초 경과 시에만" 으로 변경.

### 2단계 — 파드를 2개 이상 띄울 때만

현재 `k8s-debug-config.yaml:29` 이 `replicas: 1` 이므로 해당 없음. 스케일아웃 시 옮길 것:

| 대상 | 이유 |
|---|---|
| socket.io 어댑터 → Redis adapter | `socket.gateway.ts:53` 주석대로 현재는 sticky session 필수. 어댑터 도입 시 제약 해소 |
| `vendorMeta` (동적 DB 부활 시) | 통화 시작을 처리한 파드에만 존재 → 다른 파드에서 토큰 만료 폴백 실패 |
| 1단계 캐시 store | cache-manager 로 짜뒀다면 설정 교체만 |

### 캐시하면 안 되는 것

실시간 VOC/코칭 스트림, 통화 진행 상태, 검색 결과.
신선도가 곧 제품 가치라 캐시가 오히려 버그가 됨.

---

## 5. 검색엔진 — 도입하지 않는 이유

1. 지식검색은 이미 AICM 뒤에 ES 8.19가 붙어 있고 이 백엔드는 프록시(`search.service.ts:67`).
   여기에 ES를 또 두면 인덱스가 두 벌이 되고 동기화 부담 발생
2. 이 백엔드가 자체 검색하는 대상은 북마크·공지·투두·문서목록 수준.
   수십 명 규모에서는 **Postgres 인덱스로 충분**
3. 한글 부분일치가 느려지면 `pg_trgm` GIN 인덱스 → 그래도 부족하면 `tsvector`.
   ES 임계점(수백만 건 + 랭킹/패싯 요구)까지는 여유 있음

→ 검색은 지금도 앞으로도 **AICM 쪽 책임**으로 유지.

---

## 6. 남은 결정사항

- [ ] 멀티테넌트/동적 DB 코드를 실제 구조(단일 테넌트)에 맞춰 정리할지, 유지할지
- [ ] 1단계(`getCurrentUser` 캐시) 적용 여부 및 TTL 값
- [ ] `SELECT 1` 검증 주기 완화 적용 여부
