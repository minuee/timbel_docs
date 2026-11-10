# 작업 1 — 로그인 URL 설정 모듈 만들기

**손대는 파일**: `src/main/services/authConfig.js` — **신규 생성**
**다른 파일은 건드리지 않는다.**

---

## 왜 필요한가

앱이 브라우저를 열려면 "어느 주소를 열지"를 알아야 한다.
그런데 그 주소는 온프레미스 고객사마다 다르고(SKT / 하이닉스 / Timblo),
서버 스펙도 아직 확정 전이다.

그래서 **URL을 만드는 코드를 이 파일 하나에 모아둔다.**
나중에 스펙이 확정되면 이 파일의 상수만 고치면 되고, 다른 파일은 안 건드려도 된다.

---

## 참고 — 기존 코드의 호스트 규칙

`src/main/main.js:156` 에 이미 아래 줄이 있다. **같은 규칙을 쓴다.**

```js
const hostName  = process.env.HOST_NAME || 'dev.timblo.io';
```

---

## 할 일

아래 내용으로 `src/main/services/authConfig.js` 파일을 새로 만든다.

```js
// SSO 로그인 관련 설정 모음
// - 온프레미스 고객사마다 호스트가 다르고 서버 스펙도 확정 전이라,
//   URL 조립 로직을 이 파일 한 곳에 모아둔다.
//   스펙이 바뀌면 이 파일의 상수만 고치고 다른 파일은 건드리지 않는다.

// 호스트 규칙은 main.js 의 hostName 과 동일하게 맞춘다(main.js:156).
const HOST_NAME = process.env.HOST_NAME || 'dev.timblo.io';

// 웹 서비스 기본 주소(프로토콜 포함).
// 온프레미스에서 http 를 쓰는 곳이 있으면 WEB_BASE_URL 환경변수로 통째로 덮어쓴다.
const WEB_BASE_URL = process.env.WEB_BASE_URL || `https://${HOST_NAME}`;

// [스펙 S1] SSO 로그인 페이지 경로.
// 서버 확인 후 실제 경로로 교체할 것.
const LOGIN_PATH = '/login';

// [스펙 S2] 로그인 URL 에 붙일 쿼리 파라미터.
// 웹이 "PC 녹음앱에서 온 로그인"임을 알아야 로그인 완료 후
// timbloRecApp://connect 딥링크로 돌려보낼 수 있다.
// 서버 확인 후 실제 파라미터명/값으로 교체할 것.
const LOGIN_QUERY = {
  redirect: 'recorder',
};

// 브라우저로 열 로그인 URL 을 만든다.
function buildLoginUrl() {
  const url = new URL(LOGIN_PATH, WEB_BASE_URL);
  for (const key of Object.keys(LOGIN_QUERY)) {
    const value = LOGIN_QUERY[key];
    if (value === undefined || value === null || value === '') continue;
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

module.exports = {
  HOST_NAME,
  WEB_BASE_URL,
  buildLoginUrl,
};
```

---

## 확인 방법

프로젝트 루트에서:

```bash
node -e "console.log(require('./src/main/services/authConfig').buildLoginUrl())"
```

출력 예시:
```
https://dev.timblo.io/login?redirect=recorder
```

에러 없이 URL 한 줄이 나오면 성공.
