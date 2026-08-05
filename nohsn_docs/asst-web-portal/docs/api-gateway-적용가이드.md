# API Gateway 적용 가이드 & 체크리스트

- 작성일: 2026-07-22
- 작성 근거: 106 개발기 API Gateway(32099) 전환 실작업 (`GATEWAY-106-요청서.md`, 커밋 `a64dd97`·`c0c3dae`)
- 대상 독자: **API Gateway를 처음 적용하는 백엔드/프론트 개발자**
- 관련 문서: `docs/auth_architecture_0721_확정.pptx` (슬라이드 9 역할별 구현 가이드, 슬라이드 10 부록 E 체크리스트)

---

## 0. 이 문서의 배경

기존 인증 설계(`auth_architecture_0721_확정.pptx` 부록 E)는 **"게이트웨이 없음 기준(직접 접속)"** 전제였다.
즉 앱 서비스 백엔드가 **각자** 토큰 검증(JWKS)·쿠키 세팅·CSRF 방어를 구현하는 구조였다.

106 개발기에 **API Gateway(32099)** 가 앞단에 들어오면서 그 책임이 게이트웨이로 이동했고,
동시에 **게이트웨이가 아니면 못 푸는 문제**(WebSocket 인증, 라우트 오연결 등)가 새로 드러났다.

이 문서는 그 실작업 결과를 **다른 서비스에도 그대로 적용할 수 있는 형태**로 재정리한 것이다.

### 전환 요약

| 구간 | 게이트웨이 前 | 게이트웨이 後 |
|---|---|---|
| 프론트 → 백엔드 | 서비스별 도메인·포트 직결 (`:32025`) | 게이트웨이 단일 진입점 (`:32099`) + `/aicc/{svc}` prefix |
| JWT 서명 검증 | 앱마다 개별 구현 | **게이트웨이 위임** (내부망 신뢰 경계) |
| 쿠키 세팅 / CSRF | 앱마다 개별 구현 | **게이트웨이 단일 지점** |
| 인증 전달 수단 | `X-auth-token` 헤더 | **쿠키**(`withCredentials`) — WebSocket 때문에 필수 |

---

## 1. 역할별 구현 가이드 — 앱 서비스 공통 (프론트)

> PPT 슬라이드 9의 「앱 서비스 공통 (프론트)」 항목 개정안.

1. **API baseURL을 게이트웨이 단일 도메인 + 서비스 prefix(`/aicc/{svc}`)로 통일**
   서비스별 직결 주소·포트 제거. 내부 실제 경로(`/api/asst/v1`)는 게이트웨이가 리라이트하므로 프론트는 몰라도 된다.

2. **`credentials:"include"` 적용** (axios · socket.io `withCredentials`)
   환경 플래그로 on/off — 게이트웨이 미경유 환경(5f·aws)은 기존 헤더 인증을 그대로 유지한다.

3. **WebSocket은 커스텀 헤더 부착 불가 → 게이트웨이 인증은 쿠키 경로만 유효**
   socket.io의 `extraHeaders`는 polling transport에만 적용된다(브라우저 표준 제약).

4. **하드코딩/스토리지 토큰 전면 제거**
   앱이 자체 발급한 개발용 토큰은 게이트웨이 검증을 통과하지 못한다(`AUTH_INVALID`).

5. **프론트 refresh 인터셉터 제거**
   갱신은 백엔드/게이트웨이 담당. 401은 재로그인 유도만 한다.

6. **직접호출(파일·오디오 API 등) → 게이트웨이 라우트 경유로 일원화**
   누락 라우트는 `404`(라우트 없음) vs `401`(인증 차단)로 구분해 사전 식별한다.

> ⚠️ **3·4번이 실작업에서 가장 크게 걸린 지점.**
> "헤더만 허용하는 게이트웨이" + "헤더를 못 붙이는 브라우저 WebSocket" 조합이라
> 프론트 코드로는 우회 경로가 존재하지 않았고, `withCredentials`(쿠키)가 유일한 해법이었다.

---

## 2. 구체 작업 체크리스트 (API Gateway 경유 기준)

> PPT 슬라이드 10 부록 E 대체안. 부제를 **"게이트웨이 없음 기준(직접 접속)" → "API Gateway 경유 기준"** 으로 변경.

### A. 게이트웨이 (선행 필수 — 앱 개발자가 손댈 수 없는 영역)

- [ ] 서비스별 라우트 등록 — `/aicc/{svc}` → 업스트림 + PrefixPath 리라이트
- [ ] **라우트 오연결 점검** — 존재하지 않는 경로가 SPA fallback HTML을 `200`으로 반환하지 않는지
- [ ] **WebSocket 업그레이드 경로 인증 예외** (`/socket.io/**`) — 인증은 앱이 handshake 단계에서 자체 수행
- [ ] `Upgrade` / `Connection` 헤더가 업스트림까지 전달되는지 확인
- [ ] JWT 검증 공개키를 발급 주체(인증서버)와 정렬 — 앱 자체 발급 토큰은 미허용
- [ ] CORS: `Access-Control-Allow-Credentials: true` + Origin 명시 (`*` 사용 불가)
- [ ] 에러 포맷 통일 — 게이트웨이 401과 앱 401을 구분 가능하게 (`correlationId` 등)

### B. 앱 백엔드 (게이트웨이 도입으로 **책임이 줄어드는** 영역)

| | 항목 | 게이트웨이 前 → 後 |
|---|---|---|
| [ ] | JWT 서명 검증 | 앱마다 JWKS 로컬검증 → **게이트웨이 위임**(내부망 신뢰 경계) |
| [ ] | 쿠키(httpOnly·Secure·SameSite) 세팅 | 앱 개별 → **BFF/게이트웨이 단일 지점** |
| [ ] | CSRF 방어 | 앱 개별 → **게이트웨이 공통 필터** |
| [ ] | 게이트웨이가 주입한 신원 헤더 신뢰 + **외부 유입 위조 헤더 차단** | ★신규 |
| [ ] | socket.io handshake 자체 인증 **유지** (WS는 게이트웨이 인증 예외이므로) | ★신규 |
| [ ] | SSE(`/assist-stream`) 시작 직전 선제 갱신 — 스트림 중 `Set-Cookie` 불가 | 기존 유지 |
| [ ] | `DynamicDatabaseService` 정리 — 단일 테넌트 확정 → 정적 DB 연결 전환 | 기존 유지 |

> **B의 핵심 주의**: 검증 책임을 게이트웨이에 위임하는 순간, **앱이 직접 노출되면 무방비**가 된다.
> 앱 포트는 반드시 내부망으로 닫고, 게이트웨이를 우회한 직접 접근을 차단해야 한다.

### C. 앱 프론트

- [ ] baseURL을 게이트웨이 도메인 + `/aicc/{svc}` prefix로 교체 (직결 주소 제거)
- [ ] axios / socket.io `withCredentials` 적용 — **환경변수 플래그로 분기**
- [ ] sessionStorage / localStorage 토큰 저장 코드 제거
- [ ] 하드코딩 개발용 토큰(`VITE_ACCESS_TOKEN` 등) 비활성화
- [ ] `X-auth-token` 헤더 수동 생성 로직 제거
- [ ] 프론트 refresh 인터셉터 제거 — 401 시 재로그인 유도만
- [ ] 직접호출(파일·오디오) → 게이트웨이 라우트 경유

### D. 전환 검증 (4항목 모두 통과 시 완료)

```bash
GW=http://<gateway-host>:<port>
TOKEN=<발급받은 유효 토큰>

# 1) WebSocket 업그레이드 → 101 기대 (401이면 인증 예외 미적용)
curl -i -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     "$GW/aicc/asst-service/socket.io/?EIO=4&transport=websocket"

# 2) 토큰 검증 → 200 기대 (AUTH_INVALID면 공개키 미정렬)
curl -H "X-auth-token: $TOKEN" "$GW/aicc/asst-service/configs"

# 3) 각 서비스 루트 → JSON 기대 (HTML이면 라우트 오연결)
curl -H "X-auth-token: $TOKEN" "$GW/aicc/auth-service"

# 4) 신규 라우트 → 404 아님 (404면 라우트 미등록)
curl -o /dev/null -w "%{http_code}\n" "$GW/aicc/audio-streamer"
```

---

## 3. 롤백 경로 확보 (필수)

게이트웨이 URL과 prefix를 **전부 환경변수로 분리**해두면, 직결 복구가 값 2개 교체로 끝난다.

```bash
# 게이트웨이 경유
LANGSA_GATEWAY_URL = http://106.242.165.142:32099
ASST_API_PREFIX    = /aicc/asst-service

# 직결 복구 (게이트웨이 장애 시)
LANGSA_GATEWAY_URL = http://106.242.165.142:32025
ASST_API_PREFIX    = /api/asst/v1
```

전환 초기에는 게이트웨이 설정 이슈로 서비스 전체가 멈출 수 있으므로,
**빅뱅 전환 금지 — 환경별 순차 적용 + 즉시 롤백 가능 상태**를 유지한다.

---

## 4. 프론트 구현 참고 (asst-web-portal 실제 적용 코드)

플래그 하나로 게이트웨이/직결 환경을 모두 커버하는 구조.

**`.env.106.dev`**
```bash
# 게이트웨이 쿠키 인증 사용(axios/socket.io withCredentials).
# socket.io 는 WebSocket 핸드셰이크에 커스텀 헤더를 못 붙여서, 게이트웨이 인증은 쿠키로만 통과 가능.
# 프론트(:32026)와 게이트웨이(:32099)는 같은 호스트라 same-site → SameSite=Lax 쿠키도 정상 전송.
VITE_USE_CREDENTIALS = true
```

**`src/api/config/path.ts`**
```ts
// 게이트웨이가 Access-Control-Allow-Credentials: true 를 주는 환경에서만 켤 것.
// 미지정 시 false(기존 헤더 인증 유지).
export const USE_CREDENTIALS = process.env.VITE_USE_CREDENTIALS === "true";
```

**`src/api/apiPlugin.ts`** — axios 인스턴스 생성 시 일괄 적용
```ts
const instance = axios.create({ baseURL, timeout: timeoutMs, withCredentials: USE_CREDENTIALS });
```

**`src/api/socketIOPlugin.ts`** — socket.io
```ts
// 게이트웨이 쿠키 인증. WebSocket 핸드셰이크에는 커스텀 헤더를 못 붙이지만 쿠키는 자동으로 실린다.
withCredentials: opts.withCredentials ?? USE_CREDENTIALS,
```

> **포인트**: 플래그를 지정하지 않은 환경(5f·aws)은 자동으로 `false` → 기존 헤더 인증이 그대로 동작한다.
> 즉 **게이트웨이 도입이 다른 환경을 깨뜨리지 않는다.**

---

## 5. 꼭 알아야 할 함정 3가지

### ① `401` vs `404` 구분 — 오진 방지
- `401` = 라우트는 **존재**하는데 인증 필터에서 차단
- `404` = 라우트 **자체가 미등록**

이걸 구분하지 않으면 게이트웨이 설정 문제를 앱 버그로 오진하고 엉뚱한 곳을 파게 된다.

### ② `200 OK`도 실패일 수 있다
라우트가 엉뚱한 프론트 dev server에 물리면 **HTML을 200으로 반환**한다.
존재하지 않는 경로까지 같은 HTML을 돌려주므로, **응답 본문 해시 비교**로 SPA fallback 여부를 판별한다.

```bash
curl -s "$GW/aicc/auth-service/login"                | md5   # dc0404750209c0136c9daadf1eff07cb
curl -s "$GW/aicc/auth-service/zzz-nonexistent-9999" | md5   # dc0404750209c0136c9daadf1eff07cb  → 동일 = 오연결
```

### ③ WebSocket은 헤더 인증이 원천적으로 불가능
게이트웨이를 **"헤더 전용 인증"** 으로 설계하면 실시간 기능이 통째로 죽는다.

| 전달 방식 | 게이트웨이 응답 |
|---|---|
| `X-auth-token` 헤더 | 인식됨 (단, 브라우저 WS에서는 부착 불가) |
| `?token=` / `?access_token=` / `?auth=` 등 쿼리파라미터 | 전부 `AUTH_REQUIRED` |

**브라우저 WebSocket API는 커스텀 헤더를 붙일 수 없다.**
→ 설계 단계에서 **쿠키 인증 도입** 또는 **WS 경로 인증 예외** 중 하나를 반드시 결정해야 한다.

---

## 6. 적용 순서 요약

```
1. 게이트웨이 라우트 등록 + 실측 점검 (401/404/HTML 판별)
2. 게이트웨이 인증 정책 확정 (쿠키 or WS 예외) ← 가장 먼저 합의할 것
3. 공개키 정렬 + 유효 개발 토큰 확보
4. 프론트 baseURL/prefix 환경변수 전환 (롤백값 함께 기재)
5. withCredentials 플래그 적용 (axios + socket.io)
6. 하드코딩 토큰·수동 헤더·refresh 인터셉터 제거
7. D. 전환 검증 4항목 통과 확인
8. 앱 포트 내부망 차단 (게이트웨이 우회 접근 봉쇄)
```

> **2번을 먼저 합의하지 않으면 4~6번을 두 번 하게 된다.** 실작업에서 실제로 겪은 순서 실패다.
