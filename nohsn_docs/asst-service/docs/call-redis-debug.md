# 실시간 통화 STT 데이터 Redis 디버그 가이드

> **증상 예시:** 상담사 실시간 상담 화면에 STT(음성인식) 내용이 아무것도 안 보임.
> **결론 먼저:** asst-service는 STT 데이터를 Redis에서 **읽기만** 한다. **쓰는(쌓는) 주체는 외부 STT/NLP 서비스**다.
> 그래서 "데이터가 안 쌓인다"면 대부분 **상류(STT/NLP) 문제**이고, asst-service는 손댈 게 없는 경우가 많다.

---

## 0. 핵심 개념 (왜 이렇게 진단하나)

- asst-service는 **소비자(reader/subscriber)**다.
  - 화면이 읽는 키: **`dev:call:{callId}:turn:data`** (Redis **Sorted Set**, ZRANGE로 조회)
  - 코드 위치: `src/advisor/advisor.service.ts:803`(키 조립), `:809`(ZRANGE 읽기), 진입점 `getPrevSttDataFromRedis()`
  - **asst-service에는 이 키에 쓰는(ZADD) 코드가 없다.** (`RedisService`에 sorted-set 쓰기 메서드 자체가 없음)
- 따라서 `turn:data`를 채우는 건 **외부 STT/NLP 서비스**.
- 실시간 이벤트 채널(참고): `dev:{vendor}:{cc_cti}:call:nlp:complete` (pub/sub) — `voc-realtime.service.ts:75`

### 접속 정보 (dev)
```
호스트: dev-ecp-redis.langsa.ai
포트  : 6379
TLS   : 사용 (--tls)
비번  : timbel123!
DB    : 2      ← 중요! (기본 0번 아님. .env 의 REDIS_DB=2)
```
> ⚠️ GUI 툴(Medis 등)은 접속하면 기본 **DB 0번**을 보여준다. 반드시 **DB 2번**을 봐야 한다.
> Medis 무료버전은 콘솔/DB선택이 막혀있으니 그냥 터미널 `redis-cli`가 제일 빠르고 확실하다.

---

## 1. redis-cli 접속 (DB 2번)

```bash
redis-cli -h dev-ecp-redis.langsa.ai -p 6379 -a 'timbel123!' --tls -n 2
```
- `-n 2` 가 DB 2번 선택. 프롬프트가 `dev-ecp-redis.langsa.ai:6379[2]>` 로 뜨면 성공.
- `-a` 비번 경고("Using a password with '-a' ... may not be safe")는 무시해도 됨.
- `redis-cli` 없으면: `brew install redis`

---

## 2. STT 데이터가 쌓이는지 확인 (핵심 3단계)

### ① STT 저장 키가 있는지
```
KEYS dev:call:*:turn:data
```
- **키가 나온다** → 상류가 쌓는 중. → 3번(개수 확인)으로.
- **(empty array)** → 상류가 안 쌓는 것일 가능성 큼. → ②로 접속/prefix 검증.

### ② 접속/prefix 검증 (①이 비었을 때)
```
DBSIZE
SCAN 0 MATCH *call* COUNT 500
```
- `DBSIZE`가 0 → 엉뚱한 인스턴스/DB 보는 중 (DB 2번 맞는지 재확인).
- `*call*` 로 다른 call 키(`call:status`, `turn:idx`, `call:currents` 등)는 많은데 **`turn:data`만 없다**
  → **접속은 맞고, 상류가 `turn:data`(실제 발화)를 안 쌓는 것.** (이번 장애가 이 케이스였음)

### ③ 특정 통화의 STT 개수/내용 (①에서 키가 나왔을 때)
```
ZCARD dev:call:{callId}:turn:data
ZRANGE dev:call:{callId}:turn:data 0 -1
```
- 통화 진행 중인데 ZCARD가 안 늘면 → 그 통화는 STT가 안 들어오는 것.

---

## 3. 실시간 스트림 직접 보기 (상류가 지금 쏘는지)

> ⚠️ **터미널 redis-cli에서만 됨.** GUI 툴은 구독(스트리밍) 명령 지원 안 함.

통화 하나 걸어둔 상태에서:
```
PSUBSCRIBE dev:*:call:nlp:complete
```
- 화면이 대기 상태로 멈춤. STT가 오면 메시지가 한 줄씩 뜬다.
- **메시지가 온다** → 상류 채널은 살아있음 → `turn:data` Sorted Set에만 안 넣는 건지 확인 필요.
- **조용하다** → 상류 STT/NLP가 안 쏘는 것.
- 빠져나오기: `Ctrl+C`

> **주의:** `PSUBSCRIBE` 실행 중(구독 모드)에는 SCAN/KEYS 등 다른 명령이 막힌다.
> `ERR ... only (P|S)SUBSCRIBE ... are allowed in this context` 에러가 나면 `Ctrl+C`로 빠져나온 뒤 다시 쳐라.

---

## 4. 키 종류별 조회 명령 (타입 확인 후)

키마다 타입이 달라서 조회 명령이 다르다. 먼저 타입 확인:
```
TYPE {키}
```
| 타입 | 조회 명령 |
|------|-----------|
| string | `GET {키}` |
| hash | `HGETALL {키}` |
| sorted set (zset) | `ZRANGE {키} 0 -1` (점수 포함: `ZRANGE {키} 0 -1 WITHSCORES`) |
| list | `LRANGE {키} 0 -1` |
| stream | `XREVRANGE {키} + - COUNT 5` |

참고 — dev DB2에서 보이는 통화 관련 키들:
- `dev:call:{callId}:turn:data` — **STT 발화(화면이 읽는 것)**. 이게 비면 문제.
- `dev:call:{callId}:turn:idx` — turn 인덱스/카운터
- `dev:call:{callId}:mapping` — 통화 매핑
- `dev:{vendor}:{cc_cti}:call:status` / `:currents` — 통화 상태/진행중
- `dev:{vendor}:{agentId}:call:setting` — 상담사 콜 설정
- `dev:global:call:stt:events` — 글로벌 STT 이벤트

---

## 5. 진단 흐름 요약 (플로우차트)

```
KEYS dev:call:*:turn:data
        │
   ┌────┴─────┐
 키 있음      비어있음(empty)
   │            │
 ZCARD로      DBSIZE / SCAN *call*
 개수 확인       │
   │       ┌────┴──────┐
 안 늘어남   DB 비었음    다른 call키는 많은데
   │       (엉뚱한 DB)    turn:data만 없음
   │          │              │
   ▼          ▼              ▼
프론트 소켓/  DB 2번 맞는지   ★ 상류(STT/NLP)가
구독 문제      재접속        turn:data 안 쌓는 것
(asst 로그)                 → 담당자 확인
```

---

## 6. 담당자(상류 STT/NLP 팀)에게 전달할 정보 템플릿

```
[실시간 STT 미표시 이슈]
- asst-service 화면이 읽는 키: dev:call:{callId}:turn:data (Redis Sorted Set)
- 확인 위치: dev-ecp-redis.langsa.ai:6379 DB 2
- 현상: turn:idx / call:status / call:currents 는 쌓이는데
        turn:data(실제 발화)만 비어있음 → STT 결과를 Sorted Set에 ZADD하는 단계가 멈춘 것으로 보임
- asst-service는 reader라 쓰기 코드 없음. 상류에서 turn:data 채워지면 화면 자동 복구됨.
```

---

## 참고: asst-service 쪽에서 볼 것 (상류가 정상인데도 화면이 비면)

상류가 `turn:data`를 정상적으로 쌓는데도 화면이 비면 그때 asst-service 쪽 확인:
- Redis 연결 상태 (self-healing 로그, 재연결 흔적) — `redis.service.ts`
- 소켓 중계 경로 — `socket.gateway.ts`, `redis-monitor.controller.ts`
- prefix 하드코딩 주의: `advisor.service.ts:802` 의 `const environment = 'dev';` (dev 고정)
```
