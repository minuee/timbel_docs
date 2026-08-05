# CLAUDE.todo.md — 나중에 실제 적용할 작업

> 2026-07-21 작성. 106 개발기(`asst-service-dev`) API 게이트웨이 연동 작업 기준.
>
> **관련 문서**
> - `docs/api-gateway-integration-guide.md` — 타 서비스 적용용 가이드 & 체크리스트
> - `docs/auth-ppt-게이트웨이-반영.md` — `auth_architecture_0721_확정.pptx` 8·9p 교체안

---

## ✅ 완료 — API 게이트웨이 인바운드 전환 (106)

### 게이트웨이 규칙 (담당 부서 회신)

- Base URL: `http://106.242.165.142:32099`, 경로 `/aicc/asst-service/**`
- **라벨(`/aicc/asst-service`)만 제거하고 원래 컨텍스트 경로(`/api/asst/v1`)를 다시 붙여서** 전달
  → asst-service가 받는 경로는 전환 전과 완전히 동일
- socket.io도 동일: `/aicc/asst-service/socket.io/` → `/api/asst/v1/socket.io/`
- 인증: `x-auth-token` 그대로 도착 (추가로 `x-auth-sub`/`x-auth-role`/`x-auth-company`/`x-auth-account`도 오지만 안 씀)

```
기존: http://106.242.165.142:32025/api/asst/v1/assist-stream
신규: http://106.242.165.142:32099/aicc/asst-service/assist-stream
```

### 코드 수정이 불필요했던 근거

- `src/main.ts:98-99` — `setGlobalPrefix('/api/asst/v1')` (`API_BASE_PATH`)
- `src/common/gateways/socket.gateway.ts:32-35` — `path: '/api/asst/v1/socket.io'`
  (주석에 이미 `StripPrefix=2 + PrefixPath=/api/asst/v1` 시나리오가 명시돼 있었음)
- `x-auth-token`은 `@Headers('x-auth-token')`로 수신, HTTP 헤더는 대소문자 무시

### 실제 변경 — `docker-compose.dev.106.yml` 1개 파일

- `CORS_ALLOWED_ORIGINS` 주석 처리 (24행)
  - CORS는 게이트웨이가 **단일 처리**한다. 백엔드가 같이 켜면 `Access-Control-Allow-Origin`이
    중복되어 브라우저가 차단한다 (`src/main.ts:71` `corsEnabled` 주석 참고).
  - **32025 직결을 브라우저에서 다시 써야 하면 이 줄 주석을 해제**하면 된다.
- 포트 `32025:3000`(13행)은 게이트웨이 우회/헬스체크용으로 유지
- 아웃바운드 설정(`.env.106.development`)은 손대지 않음

### 배포 후 확인 항목 (2026-07-22 검증 완료 — 게이트웨이 자체는 정상)

- 직결 `curl :32025/api/asst/v1/health/check` → **200** (Redis 장애 해소, 기동 정상)
- 게이트웨이 `:32099/aicc/asst-service/health/check` → **401** = 라우팅은 정상이고
  게이트웨이 `cookie-jwt` 정책이 막은 것. **인증 없는 curl 로는 200 을 볼 수 없다.**
  → 5장 검증 절차의 "헬스체크 200 기대"는 이제 맞지 않는다. 헬스체크를 게이트웨이
  인증 예외로 빼달라고 요청하거나, 판정 기준을 "404 가 아니면 라우팅 정상"으로 볼 것.
- 게이트웨이가 만드는 에러 본문은 `{"error":..., "message":..., "correlationId":...}` 형식.
  백엔드(NestJS)는 `{"statusCode":..., "message":...}`, AICM(FastAPI)은 `{"detail":...}`.
  **본문 형식만 봐도 누가 낸 에러인지 즉시 구분된다.** (아래 AICM 항목에서 실제로 사용)

| 확인 | 실패 시 원인 |
|---|---|
| `http://106.242.165.142:32099/aicc/asst-service/...` 응답 | 404면 게이트웨이 라우팅 |
| socket.io (클라이언트 `path=/aicc/asst-service/socket.io`) | handshake 실패면 게이트웨이 WebSocket Upgrade 설정 |
| assist-stream(SSE) 첫 토큰 | 지연/멈춤이면 게이트웨이 버퍼링 → `proxy_buffering off` 요청 |
| CORS 에러 | 게이트웨이가 CORS를 안 붙이는 상태 → 위 주석 해제로 백엔드 CORS 복귀 |

---

## ☐ 아웃바운드(asst-service → USER/CE/AICM) 게이트웨이 전환 — 문의 회신 대기

**현재 결정: 전환하지 않고 106 내부 직결 유지.**

### 왜 보류했나

게이트웨이가 컨텍스트 경로를 **재부여**하는 방식이라, 호출자는 컨텍스트 경로를 빼고 보내야 한다.
그런데 이 서비스는 컨텍스트 경로를 하드코딩하고 있다.

```
src/common/services/user-info.service.ts:113    ${USER_HOST}/api/user/get_user
src/common/proxy/user-proxy.controller.ts:48    ${USER_HOST}/api/organization/affiliation
src/common/services/tenant-config.service.ts:16 ${USER_HOST}/api/configs/get_configs
```

`USER_HOST=http://106.242.165.142:32099/aicc/user-host` 로 두면:

```
/aicc/user-host/api/user/get_user → StripPrefix=2 → /api/user/get_user
                                  → PrefixPath 재부여 → /api/user/api/user/get_user  ❌ 이중 prefix
```

게다가 user 호출은 prefix가 **3종류**(`/api/user` 13곳, `/api/organization` 1곳, `/api/configs` 1곳)라
PrefixPath 하나로는 커버 불가.

### 담당 부서에 문의한 내용 (회신 대기)

> `/aicc/user-host/**` 라우트가 컨텍스트 경로를 **재부여**하는지, 라벨만 떼고 흘리는 **passthrough**인지?

- **passthrough** → `.env.106.development`의 `USER_HOST` 한 줄 교체로 끝
- **재부여** → 호출 코드의 고정 path 수정 필요, 또는 passthrough 라우트를 별도로 요청

> 참고: user 서비스 라우트 라벨은 `user-service`가 아니라 `/aicc/user-host/**`.

---

## ☐ Redis 접속 정보 불일치 — 담당자 문의 중 🔴 **106 기동 불가의 직접 원인**

### 증상

- `docker ps` → `Up`인데 `curl :32025/api/asst/v1/health/check` → **즉시** connection refused (타임아웃 아님)
- 외부·게이트웨이·호스트 어디서 호출해도 동일

### 원인 — 없는 포트로 무한 재연결하며 부팅이 멈춤

`.env.106.development:70-74`가 **호스트만 106으로 바꾸고 포트/비밀번호는 222 서버 것을 그대로** 두고 있다.

```
60: # REDIS_HOST=222.99.52.67      ← 32014 / nMzwaa7!U3Z! 는 원래 이 서버 것
61: # REDIS_PORT=32014
62: # REDIS_PASSWORD=nMzwaa7!U3Z!

70: REDIS_HOST=106.242.165.142     ← 호스트만 106으로 변경
72: REDIS_PORT=32014               ← ❌ 106에는 32014가 없음
73: REDIS_PASSWORD=nMzwaa7!U3Z!    ← ❌ 222 서버 비밀번호
```

106에 실제로 떠 있는 Redis는 **`callbot-redis` (redis:7-alpine, `0.0.0.0:6379`) 하나뿐**이다.

### 왜 컨테이너는 Up인데 포트가 안 열리나 (구조)

```
src/common/services/redis.service.ts:39-41   onModuleInit() → await initializeClients()
src/common/services/redis.service.ts:112-121 reconnectStrategy: 항상 delay(숫자) 반환 = 무한 재시도
src/common/services/redis.service.ts:175     await this.client.connect()  ← resolve도 reject도 안 됨
```

`reconnectStrategy`가 Error를 반환하지 않으므로 `connect()`가 영원히 대기하고,
182행 `catch`도 걸리지 않는다. NestJS는 모든 `onModuleInit`이 끝나야 `app.listen()`
(`src/main.ts:155`)을 호출하므로 **3000 포트가 영원히 바인딩되지 않는다.**

크래시가 아니라 행(hang)이므로 `restart: unless-stopped`가 발동하지 않아 STATUS가 `Up`으로 보인다.

### 담당자 회신 후 넣을 값

`src/config/redis.config.ts:5`가 `process.env.REDIS_PASSWORD || undefined`라,
비밀번호가 없으면 `REDIS_PASSWORD=`(빈값)으로 두면 AUTH를 아예 보내지 않는다.

```bash
# 확인 명령
ss -lntp | grep 32014                                    # 비어 있어야 정상 판정
docker exec callbot-redis redis-cli config get requirepass   # 비밀번호 유무
docker inspect callbot-redis -f '{{json .NetworkSettings.Networks}}'  # timbel_network 여부
```

| 확인 결과 | `.env.106.development` 수정 |
|---|---|
| requirepass 빈값 + `timbel_network` 동일 | `REDIS_HOST=callbot-redis` / `PORT=6379` / `PASSWORD=`(빈값) |
| requirepass 빈값 + 네트워크 다름 | `REDIS_HOST=106.242.165.142` / `PORT=6379` / `PASSWORD=`(빈값) |
| requirepass 값 있음 | 위 + 실제 비밀번호 |

---

## ☐ Redis 연결 실패가 서비스 전체 기동을 막는 구조 개선 (권고)

**포트를 고쳐도 남는 문제.** 다음에 Redis가 잠깐만 내려가도 서비스 전체가 기동 불가가 된다.
Redis는 pub/sub 용 부가 기능인데 헬스체크 엔드포인트까지 같이 죽는다.

### 원래 설계는 graceful degradation 이었다 — 지금은 무력화된 상태

`redis.service.ts:182-193`의 `catch`는 명시적으로 fallback을 의도하고 있다.

```
188:  this.logger.warn('Redis 서버에 연결할 수 없습니다. Redis 기능이 비활성화됩니다.');
191:  // Redis 연결 실패해도 애플리케이션은 계속 실행
192:  this.isConnected = false;
```

그런데 이후 `reconnectStrategy`를 무한 재시도로 바꾸면서(112-121행) `connect()`가
**reject 하지 않게 되어 이 `catch`가 도달 불가능한 죽은 코드가 됐다.**
의도한 fallback이 살아있는 줄 알았지만 실제로는 동작하지 않는다.

또한 크래시가 아니라 행(hang)이라 더 나쁘다:

| | 감지 | 복구 |
|---|---|---|
| 크래시였다면 | `docker ps`에 `Restarting` | `restart: unless-stopped`가 재시작 |
| 지금(행) | `Up`으로 보임, 헬스체크 불가 | 자동 복구 없음 — 정상처럼 보이는데 전면 불통 |

### 방향

`redis.service.ts:41`의 `await this.initializeClients()`에 **타임아웃**을 걸어,
연결 실패해도 부팅은 진행하고 Redis는 백그라운드에서 계속 재연결하도록 한다.

- 기존 무한 재연결 동작(과거 "10회 초과 시 영구 포기 → `redisConnected=false` 고착" 버그 수정분)은 **그대로 유지**
- `onModuleInit`만 블로킹에서 해제하는 것이 핵심

### 결정 필요

- 타임아웃 값 (예: 5~10초)
- Redis 미연결 상태에서 pub/sub 의존 기능의 동작 정의 (degrade 허용 범위)

---

## ⚠️ 주의 — `callbot-redis` 공유 시 pub/sub 채널 충돌 가능성

`callbot-redis`는 이름대로 **callbot이 쓰던 Redis**다. `REDIS_DB=2`로 DB는 분리되지만,
**Redis pub/sub은 DB 구분이 없어 전 DB 공통**이다. asst-service는 subscriber 클라이언트를
쓰므로(`redis.service.ts`) 채널명이 겹치면 callbot과 메시지가 섞인다.

- 현재 106은 `VOC_CHANNEL_ENV=localDev`라 prefix가 달라 당장 충돌 가능성은 낮음
- callbot 쪽 채널명을 한 번 확인해 둘 것. **별도 Redis 인스턴스를 띄우는 것이 정석.**

---

## 🔴 AICM·CE 가 106에 미배포 — AICM 담당자 회신 대기 ⬅️ **내일 여기부터**

> 2026-07-22 확인. 수동 문서검색(`/stream`)이 실패하는 원인. **게이트웨이와 무관하다.**

### 한 줄 요약

106 개발기에는 **AICM(aicm-service)도 CE(ce-service)도 배포되어 있지 않다.**
`.env.106.development` 가 두 서비스가 106에 있다고 가정하고 192/5F 설정을 **IP만 바꿔 복사**한 상태였다.
게이트웨이 전환 시점과 겹쳐 게이트웨이 장애로 오인했으나 무관함이 확인됐다.

### 오진 → 원인 확정 경위

```
증상: 프론트 POST :32099/aicc/asst-service/stream → 503, 게이트웨이 로그 durationMs 10505
  ↓ 게이트웨이를 의심했으나
32025 직결도 동일 재현 → {"statusCode":503,"message":"검색 서비스에 연결할 수 없습니다."}
  ↓ 이 문구는 search.service.ts:93 (AICM fetch 실패 경로) 에서만 나온다
AICM_HOST=http://106.242.165.142:8173 에 TCP 연결이 안 됨 (거부 아닌 드롭)
  ↓ docker ps 확인
106에 aicm 컨테이너 자체가 없음. 8173 을 여는 것도 없음
```

**판별 포인트 2가지 (다음에 재사용할 것):**

- **직결 포트에서도 실패하면 게이트웨이 문제가 아니다** — 가이드 6장 그대로 통했다. 32025 한 방이면 몇 시간을 아낀다.
- **10.5초는 undici(Node fetch) 기본 connect timeout 10초**다. 게이트웨이 자체 타임아웃이었다면
  `durationMs` 가 설정값 근처(10000 등)에 고정된다. `10505` 같은 어중간한 값 = 업스트림 응답을 그대로 중계했다는 신호.

### 왜 8173 이었나

`8173` 은 **192 서버의 nginx 프록시 포트**다 (`docs/callbot_advisor_api.md:286` — nginx가 `/api/aicm/`를 aicm-service로 프록시). 106에는 그 nginx가 없다.
git 이력상 `AICM_HOST` 는 first commit 부터 이 값이었고 **한 번도 바뀐 적이 없다** → 106에서 수동 문서검색이 성공한 적이 없을 가능성이 높다.

### 현재 임시 조치 — 5F AICM 공용, 그러나 401 로 막힘

```
.env.106.development:46  AICM_HOST=http://124.194.32.36:8173  # 5F AICM
```

연결은 뚫렸다(503 → 401). 하지만:

```
[SearchService] RAG 업스트림 에러: 401 {"detail":"user-service 인증 실패(401): 유효하지 않은 토큰"}
```

**이 401은 우리 코드가 만든 것이 아니라 AICM 이 보낸 것을 그대로 중계한 것이다.**

- `search.service.ts:103-104` 가 `upstream` 의 status/body 를 그대로 되던진다.
  101행 `logger.warn` 은 **기록만 할 뿐 원인이 아니다.**
- `grep -rn "유효하지 않은 토큰\|user-service 인증 실패" src` → **0건.** 우리 코드에 없는 문구.
- 본문이 `{"detail":...}` = FastAPI 형식 = AICM 원문. (게이트웨이면 `correlationId`, 우리면 `statusCode`)
- `/stream` 은 `AuthMiddleware` 제외 대상이 **아니다**(`app.module.ts:38-40`). 게이트웨이가 토큰을 안 넘겼다면
  AICM 까지 가지도 못하고 `{"statusCode":401,"message":"토큰이 없습니다..."}` 로 잘렸을 것이다.
  → **토큰은 게이트웨이를 통과해 AICM 까지 정상 전달됐다.** 거절한 쪽은 5F.

### ★ 여기서 드러난 구조 — AICM 은 단독 서비스가 아니다

```
asst-service → AICM → (AICM 이 설정해둔) user-service
                        └─ 여기서 401
```

5F AICM 은 **5F 의 user-service** 에 토큰을 물어본다. 지금 토큰은 106의 `portal-aicc-user-service-1` 이 발급한 것이라 인증 도메인이 다르다.
**따라서 106에 AICM 을 띄우는 것만으로는 부족하고, 그 AICM 이 106 user-service 를 바라보도록 설정돼야 한다.**

### ☐ 회신 대기 — AICM 담당자에게 문의한 내용

> **5F AICM 은 현재 어느 user-service 를 바라보고 있습니까?**

| 회신 | 의미 | 조치 |
|---|---|---|
| 5F 로컬 user-service | 예상대로. 106 토큰은 영원히 안 통함 | 106 전용 AICM 배포가 유일한 해법 |
| 공용/중앙 user-service (예: langsa.ai) | **배포 없이 풀릴 수 있음** | 106 프론트가 그 공용 user-service 로 로그인하도록 전환 |

### 배포 요청 시 반드시 명시할 것

- `timbel_network` 에 올려줄 것 → user-service 처럼 **컨테이너명 DNS**로 붙인다
  (106은 32020번대만 방화벽 개방. 공인 IP + 임의 포트 조합은 컨테이너에서 도달 못 함)
- AICM 이 토큰 검증에 쓸 **user-service 를 106의 `portal-aicc-user-service-1` 로 설정**할 것

### ☐ CE 도 동일한 문제 (별건, 같은 원인)

```
[HttpClientService] ← GET http://106.242.165.142:32021/api/ce/v1/nlu-catalog/intents/all
                       network error: timeout of 10000ms exceeded
```

- `docker ps` 에 **ce-service 컨테이너가 없다.** 32021 을 가진 건 `portal-aicc-user-service-1` 뿐이고,
  그것도 `0.0.0.0:` 매핑이 없는 **published 되지 않은 내부 전용 포트**다.
- ⚠️ **게이트웨이 경유로 우회 불가.** `ce-proxy.controller.ts:44` 가
  `${ceHost}` + `CE_PREFIX='/api/ce/v1'` 로 컨텍스트 경로를 하드코딩해서,
  `ecpad.etaas.co.kr/aicc/ce-service` 를 넣으면 위 "아웃바운드 전환" 항목의 **이중 prefix** 함정에 그대로 빠진다.
  (`CE_API_LLM_URL` 만 게이트웨이로 도는 건 그쪽 코드가 상대 경로만 붙이기 때문)
- → **106에 ce-service 배포 필요.**

### `.env.106.development` 오늘 변경분

| 줄 | 내용 |
|---|---|
| 41-46 | `AICM_HOST` 를 5F(`124.194.32.36:8173`)로 임시 변경 + 경위 주석. **106 배포되면 교체** |
| 55-59 | `SEARCH_HOST` 주석 처리 — `validation.config.ts:77` Joi 스키마에만 있고 **코드에서 읽는 곳이 없는 죽은 변수**. 없는 106:8173 을 가리켜 오진을 유발했음 |
| 14, 26 | `CE_HOST`/`CE_API_URL` 을 32030 으로 변경(사용자 작업). **106에 해당 포트를 여는 컨테이너 미확인 — 내일 확인 필요** |

### 내일 확인할 것

- [ ] AICM 담당자 회신 (위 표에 따라 분기)
- [ ] `CE_HOST=...:32030` 이 실제로 도달되는지 (`docker ps` 에 32030 컨테이너가 생겼는지)
- [ ] Redis 설정 원복 확인 (`REDIS_HOST=106.242.165.142` / `32014`).
      `dev-ecp-redis.langsa.ai` 로 두면 **langsa.ai 는 106망에서 접근 불가**(`.env.106.development:13` 본인 주석)라
      위 "Redis 접속 정보 불일치" 항목의 기동 불가가 재현된다
