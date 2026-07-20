# wav 테스트 통화 시뮬레이터 (시연용)

wav 2개(상담사/고객)를 실제 통화처럼 STT 서버로 흘려보내, 상담 화면에 발화가 실시간으로 뿌려지게 하는 **시연/테스트 전용** 기능.

기존에는 담당자가 5층 서버에 SSH 로 붙어 `run_wav_stt_nohsn.sh` 를 수동 실행해야만 시연이 가능했다. 담당자가 없어도 **상담 화면 버튼**으로 시연할 수 있도록 API 로 감쌌다.

> ⚠️ **임시 시연용이다.** 프로덕션 품질을 목표로 하지 않는다. `public/` 이하 스크립트는 손대지 말 것.

---

## 1. 전체 구조 (가장 중요)

```
[상담화면 버튼]
      ↓
[asst-service — 도커 컨테이너 /app]     ← 호스트 파일이 안 보인다. 스크립트를 직접 못 돌린다.
      ↓  Redis PUBLISH  localDev:wav_sim:cmd  {"cmd":"start"}
      ↓
[호스트 124.194.32.36]  wav_sim_listener.sh  ← 상시 대기 중인 "대기조". 이게 없으면 아무 일도 안 일어난다.
      ↓
  run_wav_stt_nohsn.sh  /  stop_wav_stt_nohsn.sh
      ↓
  wav → STT WebSocket(ws://124.194.32.36:17778) → Redis → 상담 화면
```

### 왜 이렇게 우회하나 — asst-service 는 도커 컨테이너다

`docker-compose.dev.5f.yml` 로 뜬 **컨테이너 안(`/app`)** 에서 돌기 때문에 호스트의 스크립트·python·venv·wav 파일이 **하나도 안 보인다**. (`.gitignore` 에 `public/*` 이 있어 이미지에도 안 들어간다.)

→ 컨테이너에서 `child_process.spawn` 으로 호스트 스크립트를 실행하는 것은 **원천적으로 불가능**하다. (처음에 이렇게 짰다가 무반응으로 삽질했다.)

그래서 **컨테이너는 Redis 에 명령만 던지고, 호스트의 리스너가 실제 실행을 맡는다.**

**이 방식의 결정적 장점**: 사람이 SSH 로 수동 실행하던 환경과 **100% 동일**하다(호스트 venv 그대로 사용). 볼륨 마운트 + Dockerfile 에 python3/redis-cli 설치 + venv 재생성 방식은 실행 환경이 달라져 새로운 디버깅을 부르므로 **기각**했다.

---

## 2. 파일 위치

| | 경로 |
|---|---|
| **서버(실제 동작)** | `/dataset/aicc/asst-service/public/call-bridge/tests/` |
| **로컬 레포** | `public/call/call-bridge/tests/` (한 단계 더 깊다. `public/*` 은 gitignore 라 배포엔 영향 없음) |

### 스크립트 3종 (모두 같은 폴더에 있어야 함)

| 파일 | 역할 |
|---|---|
| `run_wav_stt_nohsn.sh` | 실제 통화 시뮬레이션 본체. **딱 2줄만 수정**(파일명을 환경변수로 받도록) |
| `stop_wav_stt_nohsn.sh` | **신규.** 중지 + 정리 |
| `wav_sim_listener.sh` | **신규.** 호스트 상시 대기조. Redis 명령을 받아 위 둘을 실행 |

### wav 파일 (2세트가 나란히 공존한다)

| 세트 | 파일 | 용도 |
|---|---|---|
| **1** (기본) | `agent.wav` / `customer.wav` | 검증된 기존 파일 |
| **2** | `agent2.wav` / `customer2.wav` | 고객 제공 파일 |

`agent*` = 상담사(T1), `customer*` = 고객(R1). **짝을 바꿔 넣으면 화면에서 화자가 뒤바뀐다.**
파일명 자체엔 아무 의미가 없다(파이썬은 위치 인자로 받을 뿐). 화자 구분은 `--speaker T1/R1` 인자로 한다.
**세트 2가 이상하면 세트 1로 다시 호출하면 끝.** 파일을 덮어쓰지 않으므로 원복이 필요 없다.

---

## 3. 서버 세팅 (재부팅했으면 다시 해야 함)

```bash
cd /dataset/aicc/asst-service/public/call-bridge/tests

# ① 실행 권한 — 파일을 복사하면 +x 가 따라오지 않는다. 빼먹으면 "종료 코드 126" 으로 죽는다.
chmod +x run_wav_stt_nohsn.sh stop_wav_stt_nohsn.sh wav_sim_listener.sh

# ② 대기조 띄우기 (sudo 쓰지 말 것 — venv/파일 소유권이 꼬인다)
nohup ./wav_sim_listener.sh > wav_sim_listener.log 2>&1 &

# ③ 확인
pgrep -f wav_sim_listener.sh     # PID 가 나오면 성공
cat wav_sim_listener.log         # "=== wav 테스트 통화 리스너 시작 ===" 이 보이면 정상
```

- `nohup` 이라 **로그아웃엔 살아남지만 서버 재부팅엔 못 버틴다.** 재부팅 후엔 ②를 다시 실행할 것.
- 부하는 사실상 없다. `redis-cli SUBSCRIBE` 는 폴링이 아니라 **블로킹 대기**라 CPU 0%, 메모리 몇 MB.
- 종료: `pkill -f wav_sim_listener.sh`

### 리스너 코드를 고쳤으면 — 반드시 재시작

파일만 덮어써도 안 바뀐다. 떠 있는 프로세스가 옛 코드를 메모리에 물고 있다.

```bash
# (통화가 도는 중이면 GET /test/wav_call/stop 을 먼저 눌러 유령 프로세스를 막는다)
pkill -f wav_sim_listener.sh
# (새 파일 복사)
chmod +x wav_sim_listener.sh          # 복사하면 +x 가 또 날아간다
nohup ./wav_sim_listener.sh > wav_sim_listener.log 2>&1 &
```

> **`pgrep` 이 PID 를 3개 뱉는 건 정상이다.** 리스너가 3번 뜬 게 아니다. 스크립트 끝의 파이프(`redis SUBSCRIBE | while read`)를 bash 가 서브셸 2개로 fork 하는데, 서브셸이 부모의 커맨드라인을 그대로 물려받아 `pgrep -f` 에 같이 잡힌다(메인 1 + 서브셸 2 = 3).
> 진짜 중복 여부는 `GET /test/wav_call/status` 의 `listeners`(= Redis 구독자 수)로 본다. **1 이면 리스너는 하나다.**

---

## 4. API (Swagger: `http://124.194.32.36:32025/api/asst/v1/doc`)

| 엔드포인트 | 동작 |
|---|---|
| `GET /test/wav_call` | 통화 **시작** — 세트 1(기본 파일) |
| `GET /test/wav_call?set=2` | 통화 **시작** — 세트 2(고객 제공 파일) |
| `GET /test/wav_call/stop` | **중지 + 정리** |
| `GET /test/wav_call/status` | 리스너 생존 + 통화 진행 여부 |
| `GET /test/wav_call/log` | 스크립트 실행 로그 |

`set` 에 `1`/`2` 외의 값이 오면 조용히 기본(1)으로 처리한다(시연 중 오타로 죽지 않게).

```json
// GET /test/wav_call?set=2
{ "status": "started", "set": 2, "files": "agent2.wav / customer2.wav", "listeners": 1 }

// GET /test/wav_call/status
{ "status": "idle",        // 통화 진행 여부 (running / idle)
  "listeners": 1,          // 0 이면 대기조가 죽은 것 → 3번 세팅 다시
  "listenerAlive": true,
  "channel": "localDev:wav_sim:cmd" }
```

- 대기조가 없으면 `start` 는 `status: "no_listener"` 를 반환한다. **성공한 척하지 않는다.**
- 통화는 wav 를 실시간 속도로 흘리므로 **수 분간** 이어진다. 시작 API 는 기다리지 않고 즉시 응답한다.
- 컨테이너는 호스트 파일을 못 읽으므로, 실행 로그는 리스너가 Redis 에 올려주고 `/log` 가 그걸 읽는다.

### 프론트가 성공/실패를 판정하는 법

`start` 는 Redis 에 명령만 던지고 즉시 응답하므로, **응답이 `started` 라고 해서 실제로 시작된 건 아니다**
(예: `set=2` 인데 `agent2.wav` 가 업로드 안 됐으면 리스너가 즉시 포기한다).

```
1. GET /test/wav_call?set=2
2. 2~3초 대기
3. GET /test/wav_call/status
     status: "running"  → 정상 시작 (수 분간 유지된다)
     status: "idle"     → 실패. 원인은 GET /test/wav_call/log 에 있다
                          (파일 없으면 "✖ wav 파일 없음 (set=2): ./agent2.wav / ./customer2.wav")
```

구현: `src/common/controllers/wav-sim.controller.ts` (`CommonModule` 에 등록)

---

## 5. 트러블슈팅 (겪은 순서대로)

### 증상: `started` 라고 나오는데 화면 무반응

`wav_sim_listener.log` 를 먼저 본다. **`▶ 테스트 통화 시작` 이 찍혀 있으면 명령은 정상 수신된 것이다.** 그럼 스크립트 자체가 죽은 것이므로 **종료 코드**를 본다.

| 종료 코드 | 원인 | 해결 |
|---|---|---|
| **126** | **실행 권한 없음** ← **실제로 이거였다** | `chmod +x run_wav_stt_nohsn.sh` |
| 127 | 파일을 못 찾음 | 스크립트 3종이 같은 폴더에 있는지 확인 |
| 그 외 | 스크립트 내부 오류 | `tail wav_sim_run.log` 또는 `GET /test/wav_call/log` |

> ⚠️ **오진 주의**: `listeners: 1` 인데 무반응이길래 `redis-cli SUBSCRIBE` 출력 버퍼링을 의심했으나 **틀렸다.** pub/sub 은 멀쩡히 작동했고 범인은 실행 권한이었다. 리스너 로그를 먼저 볼 것.

### 증상: `listeners: 0`

대기조가 안 떠 있다. 3번 세팅을 다시 하거나, 채널 prefix 가 어긋난 것이다(`/status` 의 `channel` vs `wav_sim_listener.log` 의 "구독 채널" 비교).

### 증상: `status` 가 계속 `running` 에 갇힘

`stop` 을 호출하면 정리된다. 상태 키에 30분 TTL 이 있어 최악의 경우에도 자동 해제된다.

---

## 6. Redis 채널/키 (prefix = `localDev`)

`.env.5f.development` 의 `VOC_CHANNEL_ENV=localDev` 와 스크립트들의 `CHANNEL_ENV` 기본값이 일치해야 한다. Redis 접속 정보도 양쪽이 동일하다 (`124.194.32.36:32014`, db=2).

| 키/채널 | 용도 |
|---|---|
| `localDev:wav_sim:cmd` | 컨테이너 → 리스너 명령 (`{"cmd":"start"\|"stop"}`) |
| `localDev:wav_sim:state` | 통화 진행 중 여부 (TTL 30분) |
| `localDev:wav_sim:log` | 스크립트 실행 로그 (컨테이너가 읽어감) |

---

## 7. 스크립트 내부 동작 (참고)

### `run_wav_stt_nohsn.sh` (기존 파일 — 2줄만 수정)

수정한 2줄. 파일명을 환경변수로 받되 **기본값은 기존 그대로**라, 수동 실행 `./run_wav_stt_nohsn.sh` 는 지금까지와 100% 동일하게 동작한다.

```bash
T1_FILE="${T1_FILE:-./agent.wav}"
R1_FILE="${R1_FILE:-./customer.wav}"
```

이 덕분에 리스너가 `T1_FILE=./agent2.wav R1_FILE=./customer2.wav ./run_wav_stt_nohsn.sh` 로 세트 2를 태울 수 있다.
(파일을 덮어쓰는 방식은 원본이 날아갈 수 있어 채택하지 않았다.)

하는 일:
1. `call:events` **start** publish — 없으면 프론트가 "상담한 콜이 없습니다" 에 머문다
2. wav 2개를 `wavfile_to_stt_nohsn.py` 로 STT WebSocket 에 **실시간 페이싱** 전송 (T1=상담사 / R1=고객 병렬, 1초 시차)
3. Lua `EVAL` 로 STT 스트림 → asst-service 조회용 정렬셋(`{env}:call:{callId}:turn:data`) 변환
4. `call:events` **end** publish
5. `orchestrator:persisted` publish (상담요약 팝업 트리거)

즉 **단순 Redis publish 가 아니라 실제 STT 파이프라인을 태운다.** (그래서 NestJS 로 포팅하는 안은 폐기했다.)

### `stop_wav_stt_nohsn.sh` (신규)
`run` 스크립트는 `CALL_ID` 를 실행 시점에 생성하고 어디에도 남기지 않는다. 그래서 **살아있는 파이썬 프로세스의 커맨드라인(`--call-id/--tenant-id/--agent-id`)에서 역추출**한다. (덕분에 `run` 스크립트를 수정할 필요가 없었다.)

1. 프로세스 종료 (TERM → 2초 → KILL)
2. `call:events` **end** publish — **이걸 안 쏘면 프론트가 "콜 집계 중..." 에 갇힌다.** (중간에 끊은 통화라 `persisted` 는 의도적으로 생략)
3. `{env}:call:{callId}*` Redis 키 삭제
4. 잔여 로그(`t1_*.log` / `r1_*.log`) 정리

옵션: `--all` (남은 모든 `test-call-id-*` 키 청소) / `--no-purge` (프로세스만 종료)

---

## 8. 알아둘 제약

- **하드코딩된 ID**: `run_wav_stt_nohsn.sh` 에 `TENANT_ID=4609686`, `AGENT_ID=56356659`, `COMPANY_ID=60` 이 박혀 있다. → **그 상담사 계정으로 로그인해야 화면에 뜬다.** 다른 계정으로 보면 안 뜬다. (개선하려면 API 가 로그인 상담사의 실제 `cc_cti_id`/`vendor_tenant_id` 를 스크립트 인자로 넘기면 된다.)
- **`public/` 은 gitignore** 다. 스크립트는 git 으로 배포되지 않으므로 **서버에 직접 복사**해야 한다.
