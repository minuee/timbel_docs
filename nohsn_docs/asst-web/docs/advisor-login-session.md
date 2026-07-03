# 상담사 로그인 / 인증 / 토큰 세션 구조 분석

> asst-web 프론트엔드의 로그인·인증·토큰·토큰 재발급 흐름 전체 분석.
> 배경: 로컬/사내개발은 `VITE_ACCESS_TOKEN`(exp≈2083, 사실상 무한) 고정토큰이라 문제 없었으나,
> 고객 AWS(멀티테넌트, SSO)는 access 20분 / refresh 1시간이라 방치 시 강제 로그아웃 발생.

---

## 0. 한눈에 보기

- **인증 스택이 이원화**되어 있음 (신규 `apiPlugin` / 레거시 `request.ts`) — 혼란의 근원.
- 토큰 주 저장소는 `CookieManager`(`src/utils/cookies.js`). `VITE_COOKIE_USE_AT`로 **sessionStorage vs 암호화 쿠키** 분기.
- 자동 재발급을 실질적으로 담당하는 건 **선제 타이머 `tokenRefreshTimer.ts` 하나뿐** (특정 화면 마운트에 종속).
- 웹소켓 3종은 전부 **무인증**(토큰 미전송). 인증은 SSE + REST 경로에만 실효.

---

## 1. 토큰 저장 위치 (3중 구조)

| 위치 | 파일 | 실제 사용 | 비고 |
|---|---|---|---|
| **sessionStorage** 또는 **암호화 쿠키** | `src/utils/cookies.js` (`CookieManager`) | ✅ 주 저장소 | `VITE_COOKIE_USE_AT`로 분기 |
| Pinia `user` store → localStorage | `src/stores/modules/user.ts` | 부수적 사본 | postMessage 페이로드용 |
| `VITE_ACCESS_TOKEN` (env 고정) | `.env.*` | 로컬/개발 폴백 | exp≈2083, 사실상 무한 |

### `VITE_COOKIE_USE_AT` 분기 (`cookies.js:39-58`)
```js
setCookie/getCookie/removeCookie:
  if (!cookieUseAt) → sessionStorage 사용       // 현재 모든 env = false
  else              → js-cookie + AES-GCM 암호화 (domain: VITE_APP_DOMAIN)
```
- 현재 **모든 env가 `VITE_COOKIE_USE_AT=false`** → 토큰을 sessionStorage에 평문 저장.
- `=true`면 host 포털과 공유되는 도메인 쿠키(AES-GCM 암복호화).

### 토큰이 저장되는 지점
- `src/utils/postMessage.ts:73-74` — 부모(host)에서 `type:"refresh"` postMessage 수신 시 저장.
- `src/api/modules/request.ts:156-157` — 레거시 인터셉터 `_setRefreshToken`.
- `src/utils/tokenRefreshTimer.ts:100-101` — 선제 타이머 재발급 성공 시.

### 토큰 제거
- `src/utils/advisorSession.ts:58-62` — `clearAdvisorSessionState({ removeTokens:true })`.

---

## 2. 토큰 읽기 & 폴백 로직 ⭐

### `getCurrentAccessToken()` (`src/api/apiPlugin.ts:29-37`)
```ts
const cookieToken = Cookie.getInstance().getCookie("accessToken"); // = sessionStorage "accessToken"
if (cookieToken) return cookieToken;         // 있으면 그거
return process.env.VITE_ACCESS_TOKEN || null; // 없으면 env 고정토큰 폴백
```

**핵심: 폴백 판단은 `accessToken` 유무 딱 하나로만 갈림. `refreshToken`은 폴백 결정에 관여하지 않음.**

| sessionStorage `accessToken` | 결과 |
|---|---|
| 있음 | 그 값 사용 (refreshToken 유무 무관) |
| 없음 | `VITE_ACCESS_TOKEN` 폴백 (refreshToken 유무 무관) |

- 로컬/개발: sessionStorage에 accessToken 없음 → 항상 2083 폴백 → **재발급 불필요**.
- 고객 AWS: host/SSO가 진짜 accessToken(20분)을 심음 → 그게 반환됨 → 20분 뒤 만료.
- `.env.prd`에는 `VITE_ACCESS_TOKEN` 정의 없음 → 운영 폴백은 `null`.

---

## 3. 인증 스택 이원화 (중요)

| 스택 | 파일 | 인증 | response 인터셉터/401 | 사용처 |
|---|---|---|---|---|
| **신규** | `src/api/apiPlugin.ts` (`getClient`/`super("advisor")`) | request 인터셉터로 헤더 부착 | ❌ **없음** | **대부분의 `*.api.ts`** |
| **레거시** | `src/api/modules/request.ts` | request 인터셉터 raw 토큰 | ✅ code 105/106/107 처리 | `token.ts`/`init.ts`/`temp.ts` 3개뿐 |

- 신규 스택: `advisor`는 `Authorization: Bearer <t>` + `X-Auth-token: <t>` 둘 다 부착 (`apiPlugin.ts:57-60`). **401 재발급/재시도 로직 전무.**
- 레거시 스택: HTTP status가 아니라 **응답 body의 `code`** 로 분기.

---

## 4. 토큰 재발급 경로 (3군데, 서로 독립)

### ① 레거시 인터셉터 (`src/api/modules/request.ts:76-123`)
- `code 105/106` → 만료 간주, 부모창에 `expired` postMessage + 세션 초기화.
- `code 107` → refresh 생존 → `/refresh` 호출 후 **원 요청 1회 재시도** (`:140-149`).
- 재진입 방지는 boolean `isRefreshAttempted` 하나. **retry queue 없음.**
- ⚠️ `_getRefreshTokenCallback`에 `.catch` 없음 → 재발급 실패 시 Promise 영구 pending 가능.
- ⚠️ iframe일 때만(`validateIframe`) 만료 처리 동작.

### ② 신규 스택 (`apiPlugin.ts`)
- **response 인터셉터 자체가 없음 → 401 안전망 전무.**

### ③ 선제 재발급 타이머 (`src/utils/tokenRefreshTimer.ts`) ⭐ 실질적 핵심
- `setTimeout` 기반. JWT `exp` 디코드해 **만료 3분 전(`LEAD_MS`)** 미리 `/refresh` 호출.
- 인터셉터 **우회, 생 axios 직접 호출** (webpack 번들 크래시 회피).
- 성공 시 새 토큰 저장 → 다음 요청/SSE부터 자동 반영.
- **기동:** `src/view/advisor/consultant/index.vue:61` `onBeforeMount`, 중지: `onUnmounted`.
- **refreshToken 쿠키 없으면 no-op** → 로컬/개발은 이 타이머가 안 돎.

### 재발급 엔드포인트
- `src/api/config/path.ts:20` — `REFRESH_TOKEN = {GATEWAY_SERVER}{AUTH_PREFIX}/refresh`

---

## 5. SSE(assist-stream) — 문제의 근원

- `EventSource`가 아니라 **`fetch` + ReadableStream** (`src/api/apis/assist-stream.api.ts:41`).
- 매 호출 `getCurrentAccessToken()`으로 토큰을 헤더에 실음 (`Authorization: Bearer` + `x-auth-token`).
- **문제:** raw fetch라 axios 재발급 인터셉터(①)를 못 탐. 통화 중엔 다른 REST 트래픽도 없어 반응형 재발급 기회조차 없음 → 20분 뒤 401 반복 → 강제 로그아웃.
- **대응:** 선제 타이머 ③이 미리 토큰 교체 → 다음 발화부터 새 토큰 자동 사용.
- SSE `auth-expiry` 이벤트 → 헤더 "세션 만료, 저장 후 재로그인" **안내 칩만** 표시 (실제 동작 없음). `src/stores/modules/authExpiry.ts`.

---

## 6. 웹소켓 (전부 무인증)

| 종류 | 파일 | 인증 |
|---|---|---|
| socket.io (advisor) | `src/api/socketIOPlugin.ts` | 토큰 코드 주석 처리, `withCredentials:false` |
| SocketClient (STT) | `src/utils/SocketClient.js` | 토큰 없음, Origin 헤더만 |
| STOMP/SockJS (CCaaS) | `src/stores/modules/websocket.ts` | connect 헤더 `{}`, 토큰 없음 |

→ 인증은 **SSE + REST 경로에만** 실효.

---

## 7. 진입 플로우 & 라우터 가드

- `main.ts` / `App.vue` — **인증 로직 없음** (App.vue는 새로고침 플래그만).
- 실질 초기화는 `src/view/advisor/consultant/index.vue`의 `onBeforeMount`:
  `initApi` → `initSocket`+`connect` → `setUserProfileInStore` → `startTokenRefreshTimer`.
- host 포털 ↔ 앱 토큰 교환: `src/utils/postMessage.ts` (`type:"refresh"` 저장 / `type:"expired"` → `clearAdvisorSessionState` + `LOGIN_URL(/login)` 리다이렉트).
- 라우터 가드(`src/routers/index.ts:48-84`): **토큰 검사 없음**, 메뉴 권한 기반. 게다가 `getAuthMenuList`는 현재 **목업** 사용.

---

## 8. "고객 AWS도 2083 고정토큰 쓰면 되지 않나?" — 결론: 사실상 불가

고정토큰이 로컬에서 통하는 건 프론트가 아니라 **백엔드가 그 토큰을 받아주기 때문**. 고객 AWS에서 같이 하려면 3가지가 전부 충족돼야 함:

| 조건 | 로컬/개발 | 고객 AWS |
|---|---|---|
| ① 프론트가 고정토큰 선택 | ✅ 자동 폴백 | 가능(코드 수정) |
| ② 백엔드가 서명·exp 인정 | ✅ | ❌ 서명 키/issuer 다름 → 401, 장수명 exp 정책상 미발급 |
| ③ 단일 신원으로 충분 | ✅ 개발자 1인 | ❌ 멀티테넌트 → 토큰 1개 공유 시 전원 동일인 로그인, 매칭·권한·집계 붕괴 |

- ②③은 **프론트로 해결 불가능한 벽.** 로컬이 편했던 건 "개발자 1인 + 개발 백엔드 + 보안 무관"이라는 특수 조건 덕분.
- 진짜 해법은 고정토큰이 아니라 **refreshToken 기반 자동 재발급 견고화**(= 선제 타이머 ③ 보강 + 신규 스택 401 안전망).

---

## 9. 리스크 요약 (고객 AWS 관점)

1. **신규 스택엔 401 안전망 전무.** 선제 타이머 ③ 실패/미기동 시 대부분 API가 401 그대로 실패.
2. **타이머 ③은 `consultant/index.vue` 마운트에 종속.** 화면 밖/마운트 전후 구간은 무방비.
3. **재발급 실패 처리 미흡** (`request.ts` `_getRefreshTokenCallback` catch 없음 → 영구 pending 가능).
4. **웹소켓 전부 무인증.**
5. **주석/상태 불일치**: `authExpiry.ts`는 "재발급 API 없음"이라 적혀있으나 실제론 타이머 ③이 재발급함(옛 주석).

---

## 10. 후속 확인 필요 (미확정)

- [ ] 고객 AWS 실제 env: `VITE_COOKIE_USE_AT`, `VITE_APP_DOMAIN`, refreshToken이 실제로 쿠키/스토리지에 들어오는지.
- [ ] 선제 타이머 ③이 고객 환경에서 **실제로 도는지** (refreshToken 존재 여부에 달림).
- [ ] host 포털이 `refresh` postMessage로 토큰을 **주기 갱신해 내려주는지**, 최초 1회뿐인지.

---

## 부록: 핵심 파일 목록

| 파일 | 역할 |
|---|---|
| `src/utils/cookies.js` | `CookieManager` — 토큰 저장/조회, `VITE_COOKIE_USE_AT` 분기 |
| `src/api/apiPlugin.ts` | `getCurrentAccessToken`, 서비스별 헤더 전략, env 폴백 |
| `src/api/modules/request.ts` | 레거시 인터셉터, code 105/106/107 재발급/재시도 |
| `src/api/modules/token.ts` | `refreshToken()` API 래퍼 |
| `src/utils/tokenRefreshTimer.ts` | ⭐ 선제 재발급 타이머 (실질 핵심) |
| `src/api/apis/assist-stream.api.ts` | SSE(fetch 스트리밍), 토큰 헤더 주입 |
| `src/stores/modules/authExpiry.ts` | auth-expiry 안내 상태 (표시 전용) |
| `src/utils/postMessage.ts` | host 포털 ↔ 앱 토큰 교환(refresh/expired) |
| `src/utils/advisorSession.ts` | 세션/토큰 정리 |
| `src/view/advisor/consultant/index.vue` | 실질 초기화 엔트리, 타이머 기동 |
