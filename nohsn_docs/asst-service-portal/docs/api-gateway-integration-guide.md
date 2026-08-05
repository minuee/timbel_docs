# API 게이트웨이 연동 가이드 & 체크리스트

> 2026-07-21 asst-service(NestJS)를 106 개발기에서 API 게이트웨이 경유로 전환하면서 실제로 겪은 내용을 정리한 문서.
> **다른 백엔드 서비스(user/ce/aicm/llm-orchestrator 등)를 게이트웨이 뒤로 넣을 때 이 순서대로 따라가면 된다.**

---

## 0. 한 줄 요약

게이트웨이 연동에서 백엔드가 실제로 해야 할 일은 대부분 **코드 수정이 아니라 "경로 재작성 규칙 확인"과 "CORS 소유권 정리"** 두 가지다.
asst-service의 경우 **애플리케이션 코드는 1줄도 고치지 않았고**, 바꾼 건 `docker-compose` 환경변수 1줄(CORS 비활성화)뿐이었다.

단, 이건 운이 좋아서가 아니라 **판별식이 맞아떨어졌기 때문**이다. 그 판별식이 이 문서의 핵심이다.

---

## 1. 먼저 게이트웨이 담당 부서에 물어볼 것 (이거 없이는 시작 못 함)

경로 재작성 규칙을 모르면 어떤 검토도 추측이 된다. **아래 4개를 먼저 문의한다.**

```
1) 게이트웨이 Base URL 과 우리 서비스의 라우팅 경로(라벨)는?
   예) http://<gw-host>:32099 , /aicc/<서비스라벨>/**

2) 경로 재작성 방식은 셋 중 무엇인가?
   (a) 라벨만 떼고 원래 컨텍스트 경로를 다시 붙여줌 (재부여)
   (b) 라벨만 떼고 그대로 흘림 (passthrough)
   (c) 라벨을 떼고 아무것도 안 붙임 (strip only)

3) WebSocket(socket.io) 경로도 동일 규칙인가? Upgrade 통과되는가?

4) 인증 헤더는 어떤 형태로 도착하는가? (x-auth-token 원본 유지 여부)
   CORS 는 게이트웨이가 처리하는가, 백엔드가 처리하는가?
```

### asst-service가 받은 실제 회신 (2026-07-21)

| 항목 | 값 |
|---|---|
| Base URL | `http://106.242.165.142:32099` |
| 경로(라벨) | `/aicc/asst-service/**` |
| 재작성 | **(a) 재부여** — `/aicc/asst-service` 라벨만 제거하고 원래 컨텍스트 경로 `/api/asst/v1` 을 다시 붙여 전달 |
| socket.io | 동일 — `/aicc/asst-service/socket.io/` → `/api/asst/v1/socket.io/` |
| 인증 | `x-auth-token` 그대로 도착 (추가로 `x-auth-sub`/`x-auth-role`/`x-auth-company`/`x-auth-account`도 오지만 안 써도 됨) |
| CORS | **게이트웨이가 단일 처리** |

```
기존: http://106.242.165.142:32025/api/asst/v1/assist-stream
신규: http://106.242.165.142:32099/aicc/asst-service/assist-stream
      (백엔드에는 /api/asst/v1/assist-stream 으로 도착 → 전환 전과 동일)
```

> ⚠️ 라벨 이름을 마음대로 추측하지 말 것. user 서비스는 `user-service`가 아니라 **`/aicc/user-host/**`** 였다.

---

## 2. 판별식 — 내 서비스가 "코드 수정 없이" 전환 가능한가?

### 2-1. 인바운드(외부 → 내 서비스)

게이트웨이 재작성 결과 경로 == 지금 백엔드가 듣고 있는 경로 이면 **코드 수정 불필요**.

| 게이트웨이 방식 | 백엔드가 받는 경로 | 판정 |
|---|---|---|
| (a) 재부여 (`StripPrefix=2` + `PrefixPath=/api/asst/v1`) | `/api/asst/v1/**` | ✅ 그대로 |
| (b) passthrough | `/api/asst/v1/**` (호출자가 다 붙여 보냄) | ✅ 그대로 |
| (c) strip only | `/**` (컨텍스트 경로 없음) | ❌ `setGlobalPrefix` 제거 또는 게이트웨이에 PrefixPath 요청 |

asst-service 확인 지점:
- `src/main.ts:98-99` — `app.setGlobalPrefix(basePath)` (`API_BASE_PATH=/api/asst/v1`)
- `src/common/gateways/socket.gateway.ts:32-35` — `path: '/api/asst/v1/socket.io'`
  (주석에 이미 `StripPrefix=2 + PrefixPath=/api/asst/v1` 시나리오가 명시돼 있었음)

### 2-2. 아웃바운드(내 서비스 → 다른 서비스) ★ 여기가 진짜 함정

**호출 코드가 컨텍스트 경로를 하드코딩하고 있으면 (a) 재부여 게이트웨이와 충돌한다.**

```
USER_HOST=http://106.242.165.142:32099/aicc/user-host  로 두면

/aicc/user-host/api/user/get_user
  → StripPrefix   → /api/user/get_user
  → PrefixPath 재부여 → /api/user/api/user/get_user   ❌ 이중 prefix
```

내 코드가 어느 패턴인지 아래 명령으로 확인한다.

```bash
# 컨텍스트 경로를 하드코딩한 호출부 찾기
grep -rn "\${.*HOST}/api/\|\${this\..*Host}/api/" src --include="*.ts"
```

| 패턴 | 예시 | 게이트웨이 전환 |
|---|---|---|
| ✅ **base env + 상대 path** | `CE_API_LLM_URL` + `/ai-apps/advisor-todolist/runs`<br>(`src/common/services/ce-llm-client.service.ts:44-48`) | env 한 줄 교체로 끝 |
| ❌ **컨텍스트 경로 하드코딩** | `${USER_HOST}/api/user/get_user`<br>(`src/common/services/user-info.service.ts:113`) | 이중 prefix — 코드 수정 필요 |

asst-service의 USER 호출은 하드코딩 + **prefix가 3종류**라 `PrefixPath` 하나로 커버 자체가 불가능했다.

```
src/common/proxy/user-proxy.controller.ts    /api/user/**        (13곳)
src/common/proxy/user-proxy.controller.ts:48 /api/organization/  (1곳)
src/common/services/tenant-config.service.ts:16 /api/configs/    (1곳)
```

→ **결정: 아웃바운드는 전환하지 않고 내부 직결 유지.** (`/aicc/user-host/**`가 재부여인지 passthrough인지 회신 대기 중. passthrough면 env 한 줄 교체로 전환 가능)

> 💡 **신규 서비스는 처음부터 `base env + 상대 path`로 작성할 것.** 이미 그렇게 짜여 있던
> `LLM_ORCHESTRATOR_HOST`, `CE_API_LLM_URL`은 게이트웨이 주소(`https://ecpad.etaas.co.kr/aicc/...`)로
> **env 한 줄만 바꿔서** 이미 전환돼 있다.

---

## 3. CORS 소유권 정리 (가장 흔한 사고 지점)

**게이트웨이와 백엔드가 CORS를 둘 다 켜면 `Access-Control-Allow-Origin` 헤더가 중복되어 브라우저가 차단한다.**
게이트웨이가 CORS를 처리하는 환경에서는 **백엔드 CORS를 반드시 끈다.**

asst-service 구현 (`src/main.ts:71`):

```ts
// CORS_ALLOWED_ORIGINS 가 설정된 경우에만 백엔드 CORS 활성화
const corsEnabled = !!process.env.CORS_ALLOWED_ORIGINS;
```

→ 전환 시 `docker-compose.dev.106.yml:24`의 `CORS_ALLOWED_ORIGINS` 줄을 **주석 처리**했다.

```yaml
    environment:
      - NODE_ENV=development
      # 게이트웨이(32099) 경유로 전환하면서 비활성화. CORS 는 게이트웨이가 단일 처리한다.
      # 32025 직결을 브라우저에서 다시 써야 하면 아래 줄 주석을 해제한다.
      # - CORS_ALLOWED_ORIGINS=http://106.242.165.142:32000,...
```

> 이 스위치 하나로 "게이트웨이 경유 / 직결" 양쪽을 전환할 수 있게 설계해 두는 것을 권장.

---

## 4. 직결 포트는 남겨둘 것

게이트웨이로 전환해도 **기존 직결 포트(예: `32025:3000`)는 지우지 말고 유지한다.**

- 게이트웨이 장애 시 우회 경로
- 헬스체크 / `curl` 로 백엔드 자체 정상 여부 판별 (게이트웨이 문제와 백엔드 문제 분리)

`docker-compose.dev.106.yml:7-13` 참고.

---

## 5. 배포 후 검증 절차

```bash
# 1) 백엔드 자체 (직결) — 여기가 실패하면 게이트웨이 문제가 아니다
curl -i http://<host>:32025/api/asst/v1/health/check

# 2) 게이트웨이 경유
curl -i http://<gw-host>:32099/aicc/asst-service/health/check

# 3) 인증 헤더 전달 확인
curl -i -H "x-auth-token: <token>" http://<gw-host>:32099/aicc/asst-service/<인증필요 API>

# 4) CORS preflight (중복 헤더 확인 — Access-Control-Allow-Origin 이 2개면 실패)
curl -i -X OPTIONS -H "Origin: http://<front-host>" \
     -H "Access-Control-Request-Method: GET" \
     http://<gw-host>:32099/aicc/asst-service/health/check

# 5) socket.io handshake
curl -i "http://<gw-host>:32099/aicc/asst-service/socket.io/?EIO=4&transport=polling"
```

| 확인 항목 | 실패 시 원인 |
|---|---|
| 게이트웨이 경유 응답 | 404면 게이트웨이 라우팅(라벨/재작성 규칙) 문제 |
| socket.io handshake | 실패면 게이트웨이 **WebSocket Upgrade** 설정 누락 |
| SSE(assist-stream) 첫 토큰 | 지연/멈춤이면 게이트웨이 **버퍼링** → `proxy_buffering off` 요청 |
| `Access-Control-Allow-Origin` 중복 | 백엔드 CORS가 같이 켜져 있음 → 3장 참고 |
| 인증 401 | 게이트웨이가 `x-auth-token` 을 소비/변형했는지 확인 |

---

## 6. 트러블슈팅 — 실제로 겪은 오진 사례

> **게이트웨이 전환 직후 발생한 장애가 게이트웨이 때문이 아닐 수 있다.**

전환 배포 후 `32025` 직결조차 **connection refused**가 났다. 게이트웨이를 의심했지만 실제 원인은 무관했다.

- 증상: `docker ps` 는 `Up` 인데 `curl` 은 **즉시** 거부 (타임아웃 아님)
- 원인: `.env`의 Redis 포트/비밀번호가 다른 서버 값이라 `onModuleInit` 에서 무한 재연결 → `app.listen()` 도달 못 함
- 판별 포인트: **직결 포트에서도 실패하면 게이트웨이 문제가 아니다** (그래서 4장의 직결 포트가 필요하다)

```bash
docker logs <container> --tail 50                      # 기동 로그가 중간에 멈춰 있는지
docker exec <container> sh -c 'ss -lntp || netstat -lntp'  # 앱이 실제로 포트를 잡았는지
```

상세는 `CLAUDE.todo.md` 의 Redis 항목 참고.

---

## 7. 환경별 현황 (asst-service 기준)

| 환경 | 인바운드 | 아웃바운드 |
|---|---|---|
| 106 개발기 | ✅ 게이트웨이 `:32099/aicc/asst-service/**` (32025 직결 병행) | ❌ 내부 직결 유지 (`.env.106.development`) |
| 192 / 5F 개발기 | ❌ 게이트웨이 없음 (직결) | 일부만 게이트웨이 (`LLM_ORCHESTRATOR_HOST`, `CE_API_LLM_URL` = `ecpad.etaas.co.kr/aicc/**`) |
| prod | 게이트웨이/k8s Ingress | k8s 내부 svc 직결 |

> ⚠️ base URL의 **끝 슬래시 주의.** 코드가 `/llm/...` 을 붙이므로 `.../llm-orchestrator-service/` 처럼
> 끝에 `/`가 있으면 `//llm/...` 이중 슬래시가 된다. `.env.192.development:34` 에 실제로 남아 있는 케이스.

---

## 8. 최종 체크리스트 (복붙용)

### 사전 확인
- [ ] 게이트웨이 Base URL / 서비스 라벨 확보 (**라벨명 추측 금지**)
- [ ] 경로 재작성 방식 확인 — 재부여 / passthrough / strip only
- [ ] socket.io·WebSocket 동일 규칙 여부 + Upgrade 허용 여부
- [ ] 인증 헤더 전달 방식 확인
- [ ] CORS 처리 주체 확인 (게이트웨이 vs 백엔드)

### 인바운드
- [ ] `setGlobalPrefix` 값과 게이트웨이 재작성 결과 경로 일치 확인
- [ ] socket.io `path` 값 일치 확인
- [ ] 인증 헤더 수신 코드가 대소문자/헤더명 그대로 동작하는지 확인
- [ ] 게이트웨이가 CORS를 처리하면 **백엔드 CORS 비활성화**
- [ ] 직결 포트 유지 (우회·헬스체크용)

### 아웃바운드
- [ ] `grep -rn "\${.*HOST}/api/" src` 로 컨텍스트 경로 하드코딩 스캔
- [ ] 하드코딩 있으면 → 이중 prefix 여부 계산 후 전환 보류 or 코드 수정
- [ ] prefix 종류가 2개 이상이면 `PrefixPath` 단일 라우트로 커버 불가 → 담당 부서와 협의
- [ ] base URL 끝 슬래시 제거

### 배포 후
- [ ] 직결 헬스체크 200
- [ ] 게이트웨이 경유 200
- [ ] 인증 API 정상
- [ ] CORS preflight 헤더 1개만
- [ ] socket.io 연결 유지
- [ ] SSE 스트리밍 첫 토큰 지연 없음

---

## 참고 파일

| 파일 | 내용 |
|---|---|
| `CLAUDE.todo.md` | 106 전환 작업 이력 / 미해결 항목 |
| `docker-compose.dev.106.yml` | 게이트웨이 전환 실제 변경분 (CORS 스위치, 포트 정책) |
| `.env.106.development` | 아웃바운드 호스트 설정 |
| `src/main.ts:65-99` | CORS 소유권 분기, `setGlobalPrefix` |
| `src/common/gateways/socket.gateway.ts:32-35` | socket.io path |
| `src/common/services/ce-llm-client.service.ts` | ✅ 권장 패턴 (base env + 상대 path) |
| `src/common/proxy/user-proxy.controller.ts` | ❌ 안티패턴 (컨텍스트 경로 하드코딩) |
| `docs/cors-debug-guide.md` | CORS 디버깅 |
| `docs/wss-setup-guide.md` | WebSocket/WSS 설정 |
