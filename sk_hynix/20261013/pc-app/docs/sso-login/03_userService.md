# 작업 3 — 사용자/워크스페이스/관리자메일 조회 모듈 만들기

**손대는 파일**: `src/main/services/userService.js` — **신규 생성**
**다른 파일은 건드리지 않는다.**

---

## 왜 필요한가

로그인으로 받은 accessToken 으로 서버에서 조회해야 하는 것이 3가지 있다.

1. **내 정보** — 타이틀에 사용자 이름 표시 (이번 작업의 주 목적)
2. **워크스페이스 목록** — 업로드 대상 선택 등 후속 기능에서 사용
3. **관리자 메일주소** — 앱에서 관리자에게 메일 발송할 때 사용

토큰을 직접 다룰 필요는 없다. `apiService` 가 요청마다 자동으로
`baseURL` 과 `Authorization: Bearer ...` 헤더를 붙여준다
(`src/main/services/apiService.js` 참고).

---

## 응답 형식 전제

토큰 교환 API가 아래 형식이므로, 다른 API도 같은 봉투를 쓴다고 가정한다.

```json
{ "message": "Success", "httpCode": 200, "data": { ... } }
```

**만약 실제 응답이 다르면** 아래 코드의 `unwrap()` 함수 **하나만** 고치면 된다.

---

## 할 일

아래 내용으로 `src/main/services/userService.js` 파일을 새로 만든다.

```js
// 로그인 이후 사용자 관련 정보 조회
// - accessToken 은 여기서 다루지 않는다. apiService 인터셉터가
//   baseURL 과 Authorization 헤더를 자동으로 붙인다.
// - 서버 응답은 { message, httpCode, data } 봉투 형식을 전제로 한다
//   (토큰 교환 API 와 동일). 형식이 다르면 unwrap() 만 고치면 된다.

const { client } = require('./apiService');
const logger = require('../logger');

// [스펙 S3] 내 정보 조회 API 경로. 서버 확인 후 교체할 것.
const ME_PATH = '/api/user/me';

// [스펙 S5] 워크스페이스 목록 조회 API 경로. 서버 확인 후 교체할 것.
const WORKSPACE_PATH = '/api/workspace';

// [스펙 S6] 관리자 메일주소 조회 API 경로. 서버 확인 후 교체할 것.
const ADMIN_EMAIL_PATH = '/api/workspace/admin/email';

// 공통 응답 해석.
// 상태코드가 아니라 본문의 message 로 성공을 판정한다(서버가 httpCode 를 본문에 담아 보냄).
function unwrap(res) {
  const result = res && res.data;
  if (!result || typeof result !== 'object') {
    return { success: false, error: 'invalid_response' };
  }
  if (result.message !== 'Success') {
    return { success: false, error: `httpCode : ${result.httpCode}` };
  }
  return { success: true, data: result.data };
}

// 조회 3종의 공통 골격. 경로와 로그 이름만 다르다.
async function requestGet(path, logName) {
  try {
    const res = await client.get(path, {
      headers: { 'content-type': 'application/json' },
      // 상태코드와 무관하게 본문을 해석한다(토큰 교환과 동일한 방식)
      validateStatus: () => true,
    });

    const parsed = unwrap(res);
    if (!parsed.success) {
      try { logger.logError(`${logName}_failed`, { error: parsed.error }); } catch (_) {}
      return parsed;
    }

    try { logger.logInfo(`${logName}_success`); } catch (_) {}
    return parsed;
  } catch (err) {
    try { logger.logError(`${logName}_network_error`, { message: err && err.message }); } catch (_) {}
    return { success: false, error: 'network_error' };
  }
}

// 내 정보 조회. 로그인 직후 호출한다.
async function fetchMyInfo() {
  return requestGet(ME_PATH, 'fetch_my_info');
}

// 워크스페이스 목록 조회.
async function fetchWorkspaces() {
  return requestGet(WORKSPACE_PATH, 'fetch_workspaces');
}

// 관리자 메일주소 조회.
async function fetchAdminEmails() {
  return requestGet(ADMIN_EMAIL_PATH, 'fetch_admin_emails');
}

// 서버 응답에서 화면에 쓸 값만 추려낸다.
// [스펙 S4] 사용자 이름 필드명이 서버마다 다를 수 있어 후보를 순서대로 찾는다.
// 실제 필드명이 확인되면 후보 목록을 그 값 하나로 줄일 것.
function toProfile(data) {
  if (!data || typeof data !== 'object') return null;
  const userName =
    data.userName || data.name || data.userNm || data.nickName || '';
  return {
    userName: String(userName || ''),
    userId: data.userId || data.id || null,
    email: data.email || data.userEmail || null,
  };
}

module.exports = {
  fetchMyInfo,
  fetchWorkspaces,
  fetchAdminEmails,
  toProfile,
};
```

---

## 확인 방법

이 단계에서는 **문법 오류만 확인**한다(실제 호출은 로그인 후에나 가능).

```bash
node -e "const u=require('./src/main/services/userService'); console.log(Object.keys(u)); console.log(u.toProfile({name:'홍길동', id:7}));"
```

출력:
```
[ 'fetchMyInfo', 'fetchWorkspaces', 'fetchAdminEmails', 'toProfile' ]
{ userName: '홍길동', userId: 7, email: null }
```
