# 작업 1 — 로그인 설정 모듈 만들기

**손대는 파일**: `src/main/services/authConfig.js` — **신규** (이미 있으면 통째로 덮어쓰기)
**다른 파일은 건드리지 않는다.**

## 왜 필요한가
로그인 주소, 토큰 갱신 방식처럼 회사·서버마다 달라질 수 있는 값을 한 파일에 모은다.
나중에 값이 바뀌면 이 파일(또는 `.env`)만 고치면 된다.
`.env` 에 같은 이름의 값이 있으면 그 값이 우선한다.

## 할 일
아래 내용 그대로 `src/main/services/authConfig.js` 파일을 만든다.
`★` 표시가 붙은 값은 사람이 나중에 확정한다. 지금은 그대로 둔다.

```js
// 로그인/세션 관련 서버 주소와 옵션을 한곳에 모은다.
// - 회사(온프레미스)마다 값이 달라질 수 있어 코드 곳곳에 흩어두지 않는다.
// - .env 에 같은 이름의 값이 있으면 그 값을 우선 쓴다(재빌드 없이 바꿀 수 있게).
//
// ★ 회사에서 확정해야 하는 값은 ★ 표시. 확정 전에도 아래 기본값으로 코드는 동작한다.

const env = process.env;

module.exports = {
  // ★ MyAccess(SSO) 로그인 페이지. "MyAccess 로그인" 버튼이 기본 브라우저로 이 주소를 연다.
  //   로그인이 끝나면 웹이 timbloRecApp://connect?code=..&host=.. 딥링크를 호출한다.
  SSO_LOGIN_URL:
    env.SSO_LOGIN_URL ||
    'https://amdev.skhynix.com/sso/m/login.jsp?TYPE=XX&REALMOID=XX&GUID=XX',

  // ★ 사번 직접 로그인(HMP) 서버. 모바일앱과 같은 서버를 쓴다.
  //   모바일 소스(api_const.dart) 기준: baseUrl 'https://aimeeting.mobile.skhynix.com/m'
  //   + 경로 '/api/auth/sso/hmp'
  HMP_BASE_URL: env.HMP_BASE_URL || 'https://aimeeting.mobile.skhynix.com/m',
  HMP_LOGIN_PATH: env.HMP_LOGIN_PATH || '/api/auth/sso/hmp',
  // ★ 현재 HMP API 는 body 에 empno 하나만 받는다(비밀번호 검증 없음).
  //   서버가 비밀번호를 검증하게 되면 그 필드 이름(예: 'password')을 넣는다. 비어 있으면 보내지 않는다.
  HMP_PASSWORD_FIELD: env.HMP_PASSWORD_FIELD || '',
  // ★ 사번 직접 로그인 폼을 보여줄지. 비밀번호 검증이 없는 동안에는 운영 빌드에서 false 로 둘 것.
  EMPNO_LOGIN_ENABLED: (env.EMPNO_LOGIN_ENABLED || 'true') === 'true',

  // 토큰 갱신. 모바일 소스(api_service.dart tokenRefresh) 기준으로
  //   PUT /api/auth/refresh, body { token: refreshToken, fcmToken }, Authorization: Bearer {만료된 accessToken}
  //   응답 data.tokens.accessToken (refreshToken 도 내려오면 함께 교체)
  // ★ 서버 담당자가 POST 라고 하면 REFRESH_METHOD 만 'post' 로 바꾼다.
  REFRESH_PATH: env.REFRESH_PATH || '/api/auth/refresh',
  REFRESH_METHOD: (env.REFRESH_METHOD || 'put').toLowerCase(),

  // accessToken 만료 이 시간(ms) 전부터 미리 갱신한다.
  // 업로드는 파일 스트림이라 401 후 재전송이 불가능해서, 보내기 전에 갱신해 두는 편이 안전하다.
  REFRESH_BEFORE_EXPIRY_MS: 60 * 1000,

  // ★ 모바일은 'AOS' / 'IOS' 를 보낸다. PC 값은 서버와 합의 필요.
  APP_OS: env.APP_OS || (process.platform === 'win32' ? 'WINDOWS' : 'MAC'),
};
```

## 확인 방법
```bash
node -e "const c=require('./src/main/services/authConfig.js'); console.log(c.HMP_BASE_URL + c.HMP_LOGIN_PATH, c.REFRESH_METHOD, c.APP_OS)"
```
`https://aimeeting.mobile.skhynix.com/m/api/auth/sso/hmp put WINDOWS` (mac 이면 `MAC`) 가 출력되면 성공.
