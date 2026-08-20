# 04. 인증 · 토큰 · 세션

로컬에서 화면이 안 뜨거나 무한 리다이렉트가 나면 대부분 이 문서 범위의 문제다.

## 관련 파일

| 파일 | 역할 |
|---|---|
| `src/Utils/tokenStore.js` | ★ 토큰 저장/조회 단일 소스 (sessionStorage + 쿠키) |
| `src/Pages/Auth/CheckUser.js` | ★ 라우트 가드. 토큰 검증 후 하위 라우트 렌더 |
| `src/Pages/Auth/CheckCookies.js` | 유사 가드(별도 구현, 일부 경로에서 사용) |
| `src/Pages/Auth/Action.js` | `useAuthAction` — `isValidCookie`, `refreshToken`, `removeAppCookie` |
| `src/Stores/AuthStore.js` | 로그인/로그아웃/내 정보 조회 |
| `src/Utils/jwtUtil.js` | `decodeJwt` |
| `src/Utils/apiUtil.js` | `API.AUTH_SIGN`, `API.AUTH_ADMIN` 등 외부 이동 경로 |
| `src/Components/Layout/Main/Main.jsx` | 2차 검증 + 세션 만료/중복 로그인 모달 |

## 토큰 저장 전략 — 2중 저장소

`tokenStore.js`가 **sessionStorage와 쿠키를 용도에 따라 나눠 쓴다.** 이유는 SSO 창 격리다.

| 키 | 저장소 | 용도 |
|---|---|---|
| `timblo_token` (= `REACT_APP_COOKIE_ALIAS`) | **Cookie** | 일반 로그인 토큰. 같은 브라우저의 모든 탭이 공유 |
| `timblo_token` | **sessionStorage** | SSO 로그인 토큰. **창 단위 격리** |
| `timblo_token.ssoMode` | sessionStorage | SSO 창 표식. 토큰 삭제 후에도 유지 |
| `timblo_token_sso` | Cookie | auth-api가 SSO 발급 시 심는 **핸드오프 전용** 쿠키. 착지 즉시 소비·삭제 |

### 읽기 우선순위 — `getToken()`

```js
// tokenStore.js:43
1. sessionStorage[ALIAS]  가 있으면 그것    ← 내 창의 SSO 토큰 우선
2. sessionStorage[SSO_MODE] 가 있으면 null  ← SSO 창은 쿠키 폴백 금지
3. 그 외 쿠키[ALIAS]
```

2번이 핵심 방어선이다. SSO 창에서 로그아웃한 뒤 **공유 쿠키(다른 계정)로 폴백해 교차 오인증되는 것을 차단**한다.

### 저장 — `saveSsoToken(token, fromLegacyCookie)`
sessionStorage에 저장 + SSO 모드 표식 + 핸드오프 쿠키 폐기. sessionStorage 저장이 실패하면(브라우저 정책/quota) **공유 쿠키로 강등**한다 — 격리는 잃지만 로그인은 살리는 트레이드오프.

### 삭제 — `clearToken()`
SSO 창이면 sessionStorage 토큰만 지우고 **모드 표식은 유지**, 일반 창이면 쿠키를 지운다.

### `exitSsoModeIfLoggedOut()`
SSO 세션이 끝난 창에서 일반 로그인이 막혀 `/sign ↔ /home` 무한 루프가 되는 것을 방지한다. 자기 SSO 토큰이 없는 창만 모드를 해제한다.

> 이 파일의 로직은 실제 교차 인증 사고를 막기 위해 한 줄 한 줄 이유가 붙어 있다. 단순화하려 들기 전에 주석을 먼저 읽을 것.

## 인증 가드 흐름 — `CheckUser.js`

`App.js`에서 인증이 필요한 모든 라우트를 감싼다. `isValidUser`가 true가 되기 전에는 **아무것도 렌더링하지 않는다**(`return isValidUser ? <Outlet/> : null`).

### 개발 모드 (`REACT_APP_IS_DEV === 'true'`)
```
쿠키[ALIAS] 있음?
├─ 예 → AuthStore.refreshAuth({accessToken})
│        ├─ 200  → isValidUser = true → 화면 렌더
│        └─ 그외 → navigate('/login')
└─ 아니오 → navigate('/login')
```

### 운영 모드
```
1) SSO 핸드오프 판별
   getHandoffToken()  (timblo_token_sso 쿠키)  ← 신버전 auth-api
   getCookieToken()   (공유 쿠키)              ← 구버전 auth-api 호환
   → decodeJwt(t).sso.provider === 'shinbo' 인 것만 SSO 핸드오프로 인정
   → 핸드오프 없으면 exitSsoModeIfLoggedOut()

2) 토큰 확보: ssoHandoffToken ?? getCookie()
   없으면 → window.location.href = `${DOMAIN}/sign?f=true&s=<isSSO>`  (풀 리다이렉트)

3) 저장
   shinbo SSO  → saveSsoToken()  (창 격리)
   일반        → setCookie(ALIAS, {accessToken, is2FA},
                   { path:'/', expires: JWT exp, secure: true, sameSite: 'none' })

4) refreshAuth({accessToken})
   200  → isValidUser = true
   실패 → clearToken() 후 /sign 리다이렉트  (만료 토큰으로 인한 재인증 루프 차단)
```

`refreshAuth`는 이름과 달리 **토큰을 갱신하지 않는다.** 내부적으로 `getMyInfo()`를 호출해 `auth/user/me` + `auth/workspace/me`를 조회하고 성공하면 유효하다고 판단하는 **검증 함수**다 (`AuthStore.js:75`).

## 2차 검증 + 세션 모달 — `Main.jsx`

`CheckUser`를 통과해도 `Main`이 다시 `isValidCookie()`를 확인한다. 그리고 이 시점에 **Socket.IO를 초기화**한다.

```js
// Main.jsx:117
isValidCookie().then((isValid) => {
  if (isValid) { setIsReady(true); initNotifySocket(); }
  else { isDev ? navigate('/login') : window.location.href = `${DOMAIN}${API.AUTH_SIGN}`; }
});
```

`cookies`가 바뀔 때마다 재검증하며, 무효해지면 `webSocket.disconnect()` + 세션 만료 모달을 띄운다.

### 중복 로그인 처리
소켓으로 `DUPLICATE_SESSION_EXPIRED`가 오면 **기존 로그인 사용자에게** 새 세션 IP를 보여주는 모달(`Components/app/SessionExpired/AppSession`)을 띄우고 쿠키를 제거한다. `DUPLICATE_SESSION_CLEARED`는 반대 케이스.

## 로그인 (개발 모드 전용 화면)

`Pages/Auth/LoginPage.js` → `AuthStore.login({email, password, lang})`
```
POST auth/login
 → httpCode 200 & tokens.accessToken 있음
     request.setSessionHeaders(accessToken)
     getMyInfo(accessToken)  → auth/user/me, auth/workspace/me
     set({ auth: { tokens, user, member, isSSO?, sso? } })
     console.setUserInfo({email, accessToken})   ← 로그 전송용 신원 주입
 → 403 / 506 등은 onError(httpCode)
```

`/join`, `/findPassword`도 `REACT_APP_IS_DEV=true`에서만 라우트가 등록된다.

## JWT 클레임에서 읽는 것

| 클레임 | 용도 |
|---|---|
| `exp` | 쿠키 만료 시각 계산 |
| `isSSO` | SSO 여부 |
| `sso` | 신보 SSO 상담 컨텍스트(15개 클레임). 있으면 `/home`에서 달력 대신 상담정보 테이블 표시 |
| `sso.provider === 'shinbo'` | 창 격리 저장 경로 분기 |

## 토큰 갱신(refresh)

`Action.js:34`의 `refreshToken()`이 `PUT /api/auth/refresh`를 호출하지만, **저장된 토큰 객체에 `refreshToken` 필드가 있을 때만** 동작한다. 현재 `CheckUser`가 쿠키에 저장하는 값은 `{ accessToken, is2FA }`뿐이라 실무상 이 경로는 거의 타지 않는다. 토큰 만료 시에는 **재로그인/`/sign` 리다이렉트로 처리**된다고 보면 된다.

또한 소켓 이벤트에 `ACCESS_TOKEN_EXPIRED` 타입이 정의되어 있다(`NotifyManager.js:48`).

## 권한 모델

| 축 | 값 | 위치 |
|---|---|---|
| 회의록 공유 권한 | `OWNER` / `EDITOR` / `VIEWER` | `NotifyManager.js:66` `EDITABLE_ROLES`, `EDITABLE_ROLE` |
| 워크스페이스 멤버 | `auth.member` (`auth/workspace/me`) | AuthStore |
| UI 노출 권한 | `useAuthLayoutStore().allowUIRoles` (예: `isUseClipboard`, 챗봇 허용) | `Stores/ui/authLayoutStore.js` |

`WORKSPACE_SETTINGS_UPDATED` 소켓 이벤트로 관리자 설정이 바뀌면 UI 권한이 실시간 갱신된다.

## 트러블슈팅

| 증상 | 원인 후보 |
|---|---|
| 화면이 흰 채로 아무것도 안 나옴 | `CheckUser`가 `isValidUser=false`로 `null` 렌더 중. 콘솔의 `[CheckUser] token` 로그 확인 |
| 계속 외부 `/sign`으로 튕김 | `REACT_APP_IS_DEV`가 `'true'` 문자열이 아님. `.env` 수정 후 **dev 서버 재시작 필수** |
| `/login`이 404 | 위와 동일 — `IS_DEV`가 false면 라우트 자체가 등록되지 않음 |
| 로그인은 되는데 API가 401 | 쿠키 `secure: true; sameSite: none` — http 환경에서 쿠키가 저장 안 될 수 있음. `REACT_APP_DOMAIN`과 브라우저 주소의 프로토콜 확인 |
| `/sign ↔ /home` 무한 루프 | SSO 모드 표식이 sessionStorage에 남은 상태. 개발자도구 → Application → sessionStorage에서 `timblo_token.ssoMode` 삭제 |
| 로그아웃 후에도 이전 계정 데이터 | `clearToken()` 미호출 경로. sessionStorage/쿠키 둘 다 확인 |
