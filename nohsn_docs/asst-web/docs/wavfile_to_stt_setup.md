# wav 파일 STT 재생 테스트 — 구성과 채널 규칙

wav 파일을 실제 통화처럼 흘려보내 **실시간 발화 → 상담요약**까지 전 구간을 테스트하는 도구.
2026-07-13 "5층 개발서버에서 STT 발화만 화면에 안 뜸" 이슈를 파헤치며 정리한 실측 기록이다.

## 파일

| 파일 | 역할 | git |
|---|---|---|
| `docs/run_wav_stt_nohsn.sh` | 오케스트레이션. 콜 start/end·persisted 를 Redis 에 직접 publish 하고, STT 결과를 요약 조회용 키로 변환 | ⚠️ **gitignore 대상** (추적 안 됨) |
| `docs/ wavfile_to_stt_nohsn.py` | wav 를 STT 서버(HAIV)로 WebSocket 전송 (파일명 앞에 **공백** 있음) | ⚠️ 동일 |

## 동작 구조 (누가 무엇을 발행하는가) — ★ 가장 중요

혼선의 90% 가 여기서 나온다. **발화(STT)는 스크립트가 발행하지 않는다.**

```
run_wav_stt_nohsn.sh
   ├─ [직접 publish] call:events (start/end),  call:orchestrator:persisted
   ├─ [직접 EVAL]    STT 스트림 → {env}:call:{callId}:turn:data  (상담요약 조회용)
   └─ python ─→ STT 서버(HAIV) ─→ [STT 가 publish] call:nlp:complete / nlp:partial
                                   [STT 가 XADD]    {env}:global:call:stt:events
```

즉 **실시간 발화가 화면에 안 뜨는 문제는 스크립트를 아무리 고쳐도 안 고쳐진다.**
STT 서버의 발행 채널과 프론트의 구독 채널이 일치하는지를 봐야 한다.

## 채널·키 prefix 규칙

프론트: `src/utils/redisKey.ts`

| 채널/키 | 발행 주체 | 프론트 구독 prefix |
|---|---|---|
| `{env}:{tenant}:{agent}:call:nlp:complete` / `:nlp:partial` | **STT 서버** | `STT_ENV` |
| `{env}:{tenant}:{agent}:call:events` | **STT 서버** (테스트에선 스크립트가 대신) | `STT_ENV` |
| `{env}:{tenant}:{agent}:call:orchestrator:persisted` | 오케스트레이터 (테스트에선 스크립트) | `CHANNEL_ENV` |
| `{env}:{tenant}:{agent}:call:voc` / `:coaching` / `:coaching_request` | asst-service | `CHANNEL_ENV` |

```ts
export const CHANNEL_ENV = process.env.VITE_REDIS_CHANNEL_ENV || "dev";
export const STT_ENV     = process.env.VITE_STT_CHANNEL_ENV   || "dev";
```

환경별 값:

| env | CHANNEL_ENV | STT_ENV |
|---|---|---|
| `.env.5f.dev` / `.env.5f.local` / `.env.192.dev` | localDev | **localDev** |
| `.env.dev` | dev | dev |
| `.env.prd` | prd | **dev** (운영 STT prefix 미확인 → 기존 동작 유지) |
| `.env.local` | localDev | dev |

⚠️ webpack `DefinePlugin` 은 **해당 `.env` 파일에 있는 키만** 주입한다(`webpack.config.js:14-15`).
새 `.env` 를 만들면 `VITE_STT_CHANNEL_ENV` 를 반드시 함께 넣을 것. 없으면 브라우저에 `process` 가 없어 런타임 에러가 난다.

## 5층(5f) 개발서버 설정값 — 실측

```bash
# 스크립트
CHANNEL_ENV=localDev            # events / persisted / stt 스트림 / turn:data 전부 이 prefix
REDIS_HOST=124.194.32.36        # port 32014, db 2, 비TLS
TENANT_ID=4609686               # vendor_tenant_id (tenant UUID 아님)
AGENT_ID=56356659               # cc_cti_id (agent UUID 아님)

# python (BASE 와 PRJ_ID 는 반드시 세트로 교체)
BASE   = "ws://124.194.32.36:17778"
PRJ_ID = "f46d3019-129b-48c2-9a8f-67dd29b80b42"
```

참고: 백엔드 asst-service 는 별도로 `dev-ecp-redis.langsa.ai:6379`(TLS, db 2)도 쓴다.
**5층 프론트가 보는 Redis 는 `124.194.32.36:32014`** 다 — 헷갈리지 말 것.

## 2026-07-13 이슈: "STT 발화만 화면에 안 뜸"

**원인**: 5층 백엔드·STT 가 `localDev` prefix 로 배포됐는데, 프론트 `redisKey.ts` 는
`STT_ENV = "dev"` 로 **하드코딩**되어 있어 STT 채널을 못 들었다.
(이전 주석: *"STT 서버가 dev prefix 로 고정 발행(변경 불가)"* → **이 전제가 깨진 것**)

`events`/`persisted` 는 스크립트가 직접 `dev:` 로 쏘고 있어 우연히 동작 → **STT 만** 안 뜨는 것처럼 보였다.

**해결**: `STT_ENV` 를 `VITE_STT_CHANNEL_ENV` 환경변수로 분리, 5층 계열 env 만 `localDev` 지정.
`CHANNEL_ENV` 와 합치지 않은 이유는 운영 STT 의 prefix 가 확인되지 않아, 합치면 운영 구독이
`dev:` → `prd:` 로 바뀌며 실시간 화면이 죽을 수 있기 때문. (운영 확인되면 `.env.prd` 한 줄만 수정)

### 삽질하며 배운 것 (같은 함정 반복 금지)

- **에러가 조용히 삼켜진다.** 스크립트의 redis 호출이 `2>/dev/null` 이라, 엉뚱한 Redis 를 보고 있어도
  "수신(구독)자 수: 0" 으로만 보인다. 접속 실패와 구독자 없음을 구분하지 못한다.
- **스트림이 MAXLEN(약 1000) 으로 잘린다.** "가장 오래된 항목이 오늘"이라고 해서 그 키가 새로 생긴 건 아니다.
- **`PUBSUB CHANNELS` 는 패턴 구독(PSUBSCRIBE)을 보여주지 않는다.** 비어 보여도 구독자가 있을 수 있으니
  `PUBSUB NUMSUB <채널>` 로 채널을 직접 지정해 확인할 것.

## 진단 레시피 (추측하지 말고 Redis 에 직접 물어볼 것)

```bash
export REDISCLI_AUTH='<password>'      # -a 는 '!' 포함 비번에서 셸이 깨뜨림
R="redis-cli -h 124.194.32.36 -p 32014 -n 2 --no-auth-warning"

# 1) 프론트가 실제로 구독 중인 채널은? (0 이면 아무도 안 들음)
$R PUBSUB NUMSUB \
   dev:4609686:56356659:call:nlp:complete \
   localDev:4609686:56356659:call:nlp:complete

# 2) STT 가 실제로 어느 채널로 쏘는지 라이브로 확인 (돌리면서 스크립트 실행)
$R PSUBSCRIBE 'dev:4609686:56356659:*' 'localDev:4609686:56356659:*'

# 3) STT 가 발화를 쌓고 있는 스트림은? (살아있는 쪽에만 최근 ts 가 찍힌다)
$R XREVRANGE localDev:global:call:stt:events + - COUNT 1
$R XREVRANGE dev:global:call:stt:events + - COUNT 1
```

**1번과 2번의 prefix 가 다르면 그게 원인이다.**

## 트러블슈팅

| 증상 | 원인 |
|---|---|
| 화면에 STT 발화만 안 뜸 | STT 발행 prefix ↔ 프론트 `STT_ENV` 불일치 (위 진단 1·2번) |
| "복사된 발화(turn) 수: 0" | `STT_STREAM_KEY` prefix 가 STT 가 쓰는 스트림과 다름 |
| 콜 시작 상태로 안 바뀜 | `EVENTS_CHANNEL` prefix 가 프론트 `STT_ENV` 와 불일치 |
| 상담요약 팝업 안 뜸 | `PERSISTED_CHANNEL` prefix 가 프론트 `CHANNEL_ENV` 와 불일치 |
| 상담요약 API 가 NotFound | 스크립트는 turn 을 Redis 에만 넣는다. DB(`callstats_call`) 행은 없음 |
| `syntax error near unexpected token` | 붙여넣기 사고로 셔뱅(1번 줄)이 깨진 경우가 많다. `bash -n` 으로 확인 |
