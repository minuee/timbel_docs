# PC 녹음앱 SSO 로그인 도입 — 작업 지시서 (통합본)

> **이 파일은 `docs/sso-login/` 의 문서 10개를 하나로 합친 것입니다.**
> 원본 파일이 그대로 남아 있으니, 회사 AI에게는 **원본을 한 개씩** 주는 것을 권합니다.
> 이 통합본은 사람이 전체를 훑어보거나, 파일 반입이 어려울 때 쓰세요.
>
> **작성일**: 2026-09-02 · **대상**: `recording-pc-app` (Electron)
> **기준 커밋**: `eec5a56` — 문서의 파일 경로와 줄 번호는 이 커밋 기준으로 검증되었습니다.

---

## ⚠️ 저성능 AI에게 이 통합본을 통째로 주지 마세요

이 파일은 1,500줄이 넘습니다. 컨텍스트가 짧은 AI는 앞부분을 잊어버립니다.
**반드시 아래 목차의 섹션 하나씩 잘라서** 주세요.
각 섹션은 그것만 읽어도 수행 가능하도록 독립적으로 작성돼 있습니다.

---

## 통합본 목차

0. [개요 · 스펙 기입란 · 공통 규칙](#00_index) — `00_INDEX.md`
1. [작업 1 — 로그인 URL 설정 모듈](#01_authconfig) — `01_authConfig.md`
2. [작업 2 — 사용자 프로필 보관](#02_authservice_profile) — `02_authService_profile.md`
3. [작업 3 — 조회 API 모듈](#03_userservice) — `03_userService.md`
4. [작업 4 — 인증 IPC 핸들러](#04_main_ipc) — `04_main_ipc.md`
5. [작업 5 — preload authAPI 노출](#05_preload) — `05_preload.md`
6. [작업 6 — 로그인 대기 화면](#06_login_page) — `06_login_page.md`
7. [작업 7 — 로그인 게이트 조립](#07_main_gate) — `07_main_gate.md`
8. [작업 8 — 타이틀 사용자 이름 (부가)](#08_title_username) — `08_title_username.md`
9. [작업 9 — 개발 모드 딥링크 테스트](#09_dev_deeplink_test) — `09_dev_deeplink_test.md`

---


<a id="00_index"></a>

## 📄 원본 파일: `00_INDEX.md`


## PC 녹음앱 SSO 로그인 도입 — 작업 지시서 (INDEX)

> **작성일**: 2026-09-02
> **대상 저장소**: `recording-pc-app` (Electron)
> **사용법**: 회사 AI에게 **한 번에 파일 1개(작업 1개)씩만** 던져주세요.
> 각 작업 문서는 그것만 읽어도 수행 가능하도록 독립적으로 작성돼 있습니다.
>
> 전체를 한 파일로 합친 `ALL_IN_ONE.md` 도 같은 폴더에 있습니다.
> **사람이 훑어보거나 파일 반입이 어려울 때만** 쓰세요. AI에게 통째로 주면 안 됩니다(1,500줄 이상).

---

### 1. 목표

설치형 앱(timbloRecApp)에 로그인 단계를 만든다.

```
앱 실행
  └─ 인증정보 없음
       └─ 로그인 대기 화면 표시 + 기본 브라우저 자동 실행
            └─ 브라우저에서 회사 SSO 로그인
                 └─ 웹이 딥링크 호출  timbloRecApp://connect?code=..&host=..
                      └─ 앱이 code → accessToken 교환   ← ★ 이미 구현되어 있음
                           └─ 내 정보 조회 → 메인 화면(index.html)으로 이동
```

이번 범위는 **로그인 단계까지**. 부가 목표로 타이틀의 하드코딩된 이름을
로그인한 사용자 이름으로 바꾼다.

---

### 2. 현재 코드 상태 (이미 되어 있는 것 / 없는 것)

#### 이미 구현됨 — 건드리지 말 것
| 내용 | 위치 |
|---|---|
| 딥링크 스킴 등록 (`timbloRecApp`) | `src/main/main.js:176`, `scripts/register-protocol.js` |
| 딥링크 수신 (mac `open-url` / win `second-instance`) | `src/main/main.js:1198~1236` |
| 딥링크 파싱 + 토큰 교환 | `src/main/main.js:224` `processDeepLink()` |
| 토큰 교환 API 호출 | `src/main/services/authService.js:52` `exchangeToken()` |
| 토큰 메모리 보관 | `src/main/services/authService.js` |
| 요청에 Authorization 자동 부착 | `src/main/services/apiService.js` |
| 렌더러로 결과 통지 채널 | `main.js:283` `auth-exchanged` → `preload.js:21` |

#### 없어서 만들어야 하는 것 — 이번 작업
1. 앱이 **브라우저를 여는 코드** (`shell.openExternal`이 프로젝트 전체에 하나도 없음)
2. 인증 전/후를 가르는 **로그인 게이트 화면**
3. **내 정보 / 워크스페이스 / 관리자 메일** 조회 API 호출부
4. `auth-exchanged` 이벤트를 **실제로 받는 렌더러 코드** (preload에만 있고 아무도 안 씀)

#### 이번 범위에서 제외 (결정 사항)
- **토큰 영속 저장 안 함.** 메모리 보관 유지 → 앱 재시작 시 재로그인.
  (`docs/server_spec_questions.md` Q4-5 답변 후 별도 작업으로 진행)
- 토큰 갱신(refresh) 안 함. (Q4-1/Q4-3 답변 대기)
- 로그인 콜백은 **기존 딥링크를 재사용**한다. 로컬 루프백 서버 만들지 않는다.

---

### 3. ★ 서버 스펙 기입란 (회사에서 먼저 채울 것)

각 작업 문서는 아래 `S1~S7`을 참조합니다. **여기를 먼저 채우고 시작하세요.**
값을 모르면 각 문서에 적힌 기본값(placeholder)으로 두고 진행해도 코드는 완성됩니다.

| ID | 항목 | 값 |
|---|---|---|
| **S1** | SSO 로그인 페이지 경로 (예: `/login`) | ` ` |
| **S2** | 로그인 URL에 붙일 쿼리 파라미터 (예: `redirect=recorder`) | ` ` |
| **S3** | 내 정보 조회 API (메서드 + 경로) | ` ` |
| **S4** | 내 정보 응답에서 **사용자 이름** 필드명 (예: `data.userName`) | ` ` |
| **S5** | 워크스페이스 목록 조회 API | ` ` |
| **S6** | 관리자 메일주소 조회 API | ` ` |
| **S7** | 웹 서비스 기본 호스트 (온프레미스별) | 기본 `dev.timblo.io` |

#### 참고 — 이미 아는 스펙 (토큰 교환)
```
GET {host}/api/auth/recorder/exchange/{code}
응답: { "message": "Success", "httpCode": 200, "data": { "accessToken": "..." } }
```
→ 다른 API들도 **같은 `{ message, httpCode, data }` 봉투 형식**일 가능성이 높음.
  작업 문서의 응답 파싱 코드는 이 형식을 전제로 작성돼 있습니다.

---

### 4. 작업 목록 (이 순서대로 진행)

| # | 파일 | 작업 내용 | 손대는 파일 | 크기 |
|---|---|---|---|---|
| 1 | `01_authConfig.md` | 로그인 URL 조립 설정 모듈 신규 | `services/authConfig.js` (신규) | 소 |
| 2 | `02_authService_profile.md` | 사용자 프로필 보관 기능 추가 | `services/authService.js` | 소 |
| 3 | `03_userService.md` | 내정보/워크스페이스/관리자메일 조회 모듈 신규 | `services/userService.js` (신규) | 중 |
| 4 | `04_main_ipc.md` | 인증 IPC 핸들러 3개 추가 | `main/main.js` | 소 |
| 5 | `05_preload.md` | 렌더러에 `authAPI` 노출 | `main/preload.js` | 소 |
| 6 | `06_login_page.md` | 로그인 대기 화면 신규 | `renderer/pages/login.html`, `renderer/scripts/login.js` (신규) | 중 |
| 7 | `07_main_gate.md` | 시작 화면 분기 + 교환 성공 후 처리 | `main/main.js` | 중 |
| 8 | `08_title_username.md` | 타이틀에 사용자 이름 노출 | `renderer/index.html`, `renderer/index.js` | 소 |
| 9 | `09_dev_deeplink_test.md` | 개발 모드 딥링크 테스트 수단 | `main/main.js`, `main/preload.js` | 중 |

**1~7이 로그인 기능. 8은 부가 작업. 9는 테스트 수단.**
7번까지 끝나면 로그인이 동작합니다. 시간이 없으면 8번은 버려도 됩니다.

**9번은 먼저 해도 됩니다.** macOS에서 개발하신다면 7번을 검증하려면 9번이 필요하므로,
`7 → 9 → 검증` 또는 `4 → 9 → 5~7` 순서로 진행하세요.

---

### 5. 회사 AI에게 줄 공통 규칙 (작업 문서와 함께 붙여넣기)

```
[공통 규칙]
1. 이 문서에 적힌 파일 외에는 절대 수정하지 마라.
2. 기존 코드를 삭제하지 마라. 지시된 위치에 "추가"만 해라.
3. 문서에 "신규 파일"이라고 적힌 것은 파일 전체를 그대로 생성해라.
4. 문서에 "수정"이라고 적힌 것은 [찾을 코드]를 파일에서 찾아
   [바꿀 코드]로 교체해라. 찾는 코드가 없으면 멈추고 보고해라.
5. 주석은 한국어로, 기존 파일의 주석 스타일(왜 그렇게 했는지 설명)을 따라라.
6. 작업이 끝나면 변경한 파일명과 줄 수만 보고해라. 코드 전문을 다시 출력하지 마라.
```

---

### 6. 완료 확인 방법 (7번 작업 후)

1. `yarn start` (또는 `npm start`) 로 앱 실행
2. 로그인 대기 화면이 뜨고, 기본 브라우저가 자동으로 열리는지 확인
3. 브라우저에서 SSO 로그인 완료
4. 앱이 자동으로 메인 화면(마이크 테스트)으로 전환되는지 확인
5. 로그 확인: `deeplink_exchange_success`, `auth_profile_loaded` 가 찍히는지
   - 로그 위치는 `src/main/logger.js` 참고

> **딥링크 테스트 방법은 OS마다 다릅니다.** `09_dev_deeplink_test.md` 를 참고하세요.
> - **Windows**: 개발 모드에서도 실제 딥링크 테스트 가능 (작업 9에서 등록 조건 1줄 수정)
> - **macOS**: 개발 모드에서는 불가. 작업 9의 시뮬레이션 훅으로 테스트
> - **양쪽 공통**: 최종 확인은 `npm run build` 후 빌드본으로
>
> 실행 명령도 구분해서 씁니다.
> - 평소 개발: `npm run dev`
> - **딥링크/로그인 테스트: `npm start -- --dev`**

---

### 부록 A. 작업 중 발견한 기존 이슈 (참고용 · 이번 범위 아님)

#### 딥링크가 두 번 처리될 수 있음

`main.js:177~205` 를 보면 딥링크 하나가 `processDeepLink()` 를 **두 번** 탈 수 있다.

```js
function sendDeepLinkToRenderer(url) {
  if (!mainWindow) { deepLinkQueue.push(url); return; }
  if (mainWindow.webContents.isLoading()) {
    deepLinkQueue.push(url);      // ← 큐에 넣고
  } else { ... }
  processDeepLink(url).catch(() => {});   // ← 여기서 이미 처리하는데
}

function flushDeepLinks() {
  for (const url of deepLinkQueue) {
    mainWindow.webContents.send("deep-link", url);
    processDeepLink(url).catch(() => {});  // ← 큐에서 또 처리
  }
}
```

**언제 문제가 되나**: 앱이 꺼진 상태에서 딥링크로 실행될 때(=창 로딩 중).
`code` 는 1회용이므로 두 번째 교환은 실패하고,
`broadcastAuthExchanged({ success: false })` 가 화면으로 날아간다.

**영향**: 로그인 성공 직후 화면에 로그인 실패 문구가 뜰 수 있다.
(작업 6의 `login.js` 는 성공 시 곧바로 화면을 넘기므로 대부분 묻히지만,
타이밍에 따라 보일 수 있다)

**한 줄 수정안** — 이미 처리한 URL은 건너뛴다.
```js
const processedDeepLinks = new Set();

async function processDeepLink(url) {
  if (processedDeepLinks.has(url)) return;   // 함수 맨 앞에 추가
  processedDeepLinks.add(url);
  ...
}
```

> 이번 로그인 작업과 별개 건이라 지시서에 넣지 않았다.
> 로그인 테스트 중 "로그인은 됐는데 실패 문구가 뜬다"는 증상이 보이면 이걸 적용할 것.


---


<a id="01_authconfig"></a>

## 📄 원본 파일: `01_authConfig.md`


## 작업 1 — 로그인 URL 설정 모듈 만들기

**손대는 파일**: `src/main/services/authConfig.js` — **신규 생성**
**다른 파일은 건드리지 않는다.**

---

### 왜 필요한가

앱이 브라우저를 열려면 "어느 주소를 열지"를 알아야 한다.
그런데 그 주소는 온프레미스 고객사마다 다르고(SKT / 하이닉스 / Timblo),
서버 스펙도 아직 확정 전이다.

그래서 **URL을 만드는 코드를 이 파일 하나에 모아둔다.**
나중에 스펙이 확정되면 이 파일의 상수만 고치면 되고, 다른 파일은 안 건드려도 된다.

---

### 참고 — 기존 코드의 호스트 규칙

`src/main/main.js:156` 에 이미 아래 줄이 있다. **같은 규칙을 쓴다.**

```js
const hostName  = process.env.HOST_NAME || 'dev.timblo.io';
```

---

### 할 일

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

### 확인 방법

프로젝트 루트에서:

```bash
node -e "console.log(require('./src/main/services/authConfig').buildLoginUrl())"
```

출력 예시:
```
https://dev.timblo.io/login?redirect=recorder
```

에러 없이 URL 한 줄이 나오면 성공.


---


<a id="02_authservice_profile"></a>

## 📄 원본 파일: `02_authService_profile.md`


## 작업 2 — authService 에 사용자 프로필 보관 기능 추가

**손대는 파일**: `src/main/services/authService.js` — **수정**
**다른 파일은 건드리지 않는다.**

---

### 왜 필요한가

로그인 성공 후 서버에서 내려받은 사용자 정보(이름, 이메일 등)를
앱이 살아있는 동안 들고 있어야 한다. 타이틀에 이름을 표시하거나,
업로드 시 참고하는 데 쓴다.

토큰과 같은 생명주기(앱 실행 중에만 유지, 로그아웃 시 소멸)를 가지므로
**토큰을 이미 관리하고 있는 authService 에 같이 둔다.**

> 주의: accessToken 은 렌더러로 절대 보내지 않는다(파일 상단 주석 참고).
> 하지만 **프로필은 화면에 표시해야 하므로 렌더러로 보내도 된다.**

---

### 할 일 — 3군데 수정

#### 2-1. 상태 변수 추가

**[찾을 코드]** (파일 상단, 8~10번째 줄 근처)
```js
let accessToken = null;
let refreshToken = null;
let endpoint = '';
```

**[바꿀 코드]**
```js
let accessToken = null;
let refreshToken = null;
let endpoint = '';
// 로그인 사용자 정보. 화면 표시용이라 렌더러로 내보내도 되는 값만 담는다
// (토큰은 절대 여기 넣지 않는다).
let profile = null;
```

---

#### 2-2. clearSession 에서 프로필도 비우기

**[찾을 코드]**
```js
function clearSession() {
  accessToken = null;
  refreshToken = null;
  endpoint = '';
}
```

**[바꿀 코드]**
```js
function clearSession() {
  accessToken = null;
  refreshToken = null;
  endpoint = '';
  profile = null;
}
```

---

#### 2-3. 프로필 get/set 함수 추가 + export

**[찾을 코드]**
```js
function isAuthenticated() {
  return !!accessToken;
}
```

**[바꿀 코드]**
```js
function isAuthenticated() {
  return !!accessToken;
}

// 사용자 정보 저장. 로그인 직후 내 정보 조회에 성공하면 호출한다.
function setProfile(nextProfile) {
  profile = nextProfile || null;
}

// 사용자 정보 조회. 아직 조회 전이거나 실패했으면 null.
function getProfile() {
  return profile;
}
```

그리고 **파일 맨 아래 `module.exports` 에 두 개를 추가한다.**

**[찾을 코드]**
```js
  isAuthenticated,
  exchangeToken,
  refreshAccessToken,
};
```

**[바꿀 코드]**
```js
  isAuthenticated,
  setProfile,
  getProfile,
  exchangeToken,
  refreshAccessToken,
};
```

---

### 확인 방법

```bash
node -e "const a=require('./src/main/services/authService'); a.setProfile({userName:'홍길동'}); console.log(a.getProfile()); a.clearSession(); console.log(a.getProfile());"
```

출력:
```
{ userName: '홍길동' }
null
```


---


<a id="03_userservice"></a>

## 📄 원본 파일: `03_userService.md`


## 작업 3 — 사용자/워크스페이스/관리자메일 조회 모듈 만들기

**손대는 파일**: `src/main/services/userService.js` — **신규 생성**
**다른 파일은 건드리지 않는다.**

---

### 왜 필요한가

로그인으로 받은 accessToken 으로 서버에서 조회해야 하는 것이 3가지 있다.

1. **내 정보** — 타이틀에 사용자 이름 표시 (이번 작업의 주 목적)
2. **워크스페이스 목록** — 업로드 대상 선택 등 후속 기능에서 사용
3. **관리자 메일주소** — 앱에서 관리자에게 메일 발송할 때 사용

토큰을 직접 다룰 필요는 없다. `apiService` 가 요청마다 자동으로
`baseURL` 과 `Authorization: Bearer ...` 헤더를 붙여준다
(`src/main/services/apiService.js` 참고).

---

### 응답 형식 전제

토큰 교환 API가 아래 형식이므로, 다른 API도 같은 봉투를 쓴다고 가정한다.

```json
{ "message": "Success", "httpCode": 200, "data": { ... } }
```

**만약 실제 응답이 다르면** 아래 코드의 `unwrap()` 함수 **하나만** 고치면 된다.

---

### 할 일

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

### 확인 방법

이 단계에서는 **문법 오류만 확인**한다(실제 호출은 로그인 후에나 가능).

```bash
node -e "const u=require('./src/main/services/userService'); console.log(Object.keys(u)); console.log(u.toProfile({name:'홍길동', id:7}));"
```

출력:
```
[ 'fetchMyInfo', 'fetchWorkspaces', 'fetchAdminEmails', 'toProfile' ]
{ userName: '홍길동', userId: 7, email: null }
```


---


<a id="04_main_ipc"></a>

## 📄 원본 파일: `04_main_ipc.md`


## 작업 4 — main.js 에 인증 IPC 핸들러 추가

**손대는 파일**: `src/main/main.js` — **수정**
**다른 파일은 건드리지 않는다.**

---

### 왜 필요한가

렌더러(화면)는 브라우저를 직접 열 수 없고, 서버 토큰에도 접근할 수 없다.
그래서 메인 프로세스에 창구(IPC 핸들러)를 만들고, 화면은 그걸 호출만 한다.

만들 창구는 3개다.

| 채널명 | 하는 일 |
|---|---|
| `auth:open-login` | 기본 브라우저로 SSO 로그인 페이지를 연다 |
| `auth:get-status` | 지금 로그인 상태인지 알려준다 |
| `auth:get-profile` | 로그인한 사용자 정보를 알려준다 |

---

### 할 일 — 3군데 수정

#### 4-1. `shell` 모듈 import 추가

`shell.openExternal()` 이 기본 브라우저를 여는 Electron API다.
현재 이 프로젝트는 `shell` 을 import 하고 있지 않다.

**[찾을 코드]** (파일 1번째 줄)
```js
const { app, BrowserWindow, ipcMain, Tray, nativeImage, Menu, Notification } = require("electron");
```

**[바꿀 코드]**
```js
const { app, BrowserWindow, ipcMain, Tray, nativeImage, Menu, Notification, shell } = require("electron");
```

> 1번째 줄 맨 앞에 눈에 안 보이는 BOM 문자가 있을 수 있다. 지우지 말 것.

---

#### 4-2. 새 모듈 require 추가

**[찾을 코드]** (45번째 줄 근처)
```js
const authService = require("./services/authService");
const { client: apiClient } = require("./services/apiService");
```

**[바꿀 코드]**
```js
const authService = require("./services/authService");
const { client: apiClient } = require("./services/apiService");
const authConfig = require("./services/authConfig");
const userService = require("./services/userService");
```

---

#### 4-3. IPC 핸들러 3개 추가

`ipcMain.handle("load-index", ...)` 를 파일에서 찾는다 (334번째 줄 근처).
**그 핸들러 블록 바로 위에** 아래 코드를 통째로 삽입한다.

```js
// --- 인증 IPC -----------------------------------------------------------
// 렌더러는 토큰을 직접 다루지 않는다. 아래 창구를 통해서만 인증을 다룬다.

// 기본 브라우저로 SSO 로그인 페이지를 연다.
// 로그인이 끝나면 웹이 timbloRecApp://connect 딥링크로 앱을 다시 호출하고,
// 그 뒤는 기존 processDeepLink() 가 처리한다.
ipcMain.handle("auth:open-login", async () => {
  try {
    const loginUrl = authConfig.buildLoginUrl();
    try { logger.logInfo('auth_open_login', { urlHost: new URL(loginUrl).host }); } catch (_) {}
    await shell.openExternal(loginUrl);
    return { success: true };
  } catch (err) {
    try { logger.logError('auth_open_login_failed', { message: err && err.message }); } catch (_) {}
    return { success: false, error: err && err.message };
  }
});

// 현재 로그인 상태 조회. accessToken 값 자체는 절대 넘기지 않는다.
ipcMain.handle("auth:get-status", () => {
  return {
    success: true,
    authenticated: authService.isAuthenticated(),
    profile: authService.getProfile(),
  };
});

// 로그인 사용자 정보 조회. 아직 못 받았으면 이 시점에 한 번 더 시도한다.
ipcMain.handle("auth:get-profile", async () => {
  try {
    if (!authService.isAuthenticated()) {
      return { success: false, error: 'not_authenticated' };
    }
    let profile = authService.getProfile();
    if (!profile) {
      const res = await userService.fetchMyInfo();
      if (res.success) {
        profile = userService.toProfile(res.data);
        authService.setProfile(profile);
      }
    }
    return { success: !!profile, profile: profile || null };
  } catch (err) {
    return { success: false, error: err && err.message };
  }
});
```

---

### 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법 OK')"
```

`문법 OK` 가 출력되면 성공. (실행 테스트는 작업 7 이후에 한다)


---


<a id="05_preload"></a>

## 📄 원본 파일: `05_preload.md`


## 작업 5 — preload 에 authAPI 노출

**손대는 파일**: `src/main/preload.js` — **수정**
**다른 파일은 건드리지 않는다.**

---

### 왜 필요한가

이 앱은 `contextIsolation: true` 라서(`main.js:302` 근처) 렌더러가
`ipcRenderer` 를 직접 쓸 수 없다. preload 에서 `contextBridge` 로
노출한 함수만 화면에서 쓸 수 있다.

작업 4에서 만든 IPC 창구 3개를 화면이 부를 수 있게 연결한다.

> `auth-exchanged` 이벤트 수신은 **이미 `electronAPI.onAuthExchanged` 로
> 노출되어 있다**(preload.js 21번째 줄 근처). 새로 만들지 말고 그걸 그대로 쓴다.

---

### 할 일 — 1군데 추가

`contextBridge.exposeInMainWorld('dbAPI', {` 라는 줄을 파일에서 찾는다.
**그 줄 바로 위에** 아래 코드를 통째로 삽입한다.

```js
// 인증 관리
// - accessToken 자체는 절대 렌더러로 넘어오지 않는다.
//   화면은 "로그인 상태인지"와 "사용자 표시 정보"만 받는다.
// - 로그인 완료 통지는 기존 electronAPI.onAuthExchanged 를 쓴다.
contextBridge.exposeInMainWorld('authAPI', {
  // 기본 브라우저로 SSO 로그인 페이지 열기
  openLogin: () => {
    return ipcRenderer.invoke('auth:open-login')
  },

  // 현재 로그인 상태 조회 → { success, authenticated, profile }
  getStatus: () => {
    return ipcRenderer.invoke('auth:get-status')
  },

  // 로그인 사용자 정보 조회 → { success, profile }
  getProfile: () => {
    return ipcRenderer.invoke('auth:get-profile')
  },
});
```

---

### 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/preload.js','utf8')); console.log('문법 OK')"
grep -n "authAPI" src/main/preload.js
```

`문법 OK` 와 `authAPI` 가 들어간 줄이 보이면 성공.


---


<a id="06_login_page"></a>

## 📄 원본 파일: `06_login_page.md`


## 작업 6 — 로그인 대기 화면 만들기

**손대는 파일**
- `src/renderer/pages/login.html` — **신규 생성**
- `src/renderer/scripts/login.js` — **신규 생성**

**다른 파일은 건드리지 않는다.**

---

### 왜 필요한가

로그인은 브라우저에서 이뤄지므로, 앱 쪽에는 "브라우저에서 로그인 중"이라는
대기 화면이 필요하다. 아무 화면도 없으면 사용자는 앱이 멈춘 줄 안다.

화면이 할 일은 3가지뿐이다.
1. 화면이 뜨면 브라우저를 자동으로 1회 연다
2. 브라우저를 놓친 사용자를 위해 "다시 열기" 버튼을 준다
3. 로그인 성공 통지(`auth-exchanged`)를 받으면 메인 화면으로 넘어간다

> 메인 화면 이동은 **이미 있는 IPC** `electronAPI.loadIndex()` 를 쓴다
> (`main.js` 의 `load-index` 핸들러). 새로 만들지 않는다.

---

### 참고 — 창 크기와 프레임

메인 창은 `380 x 436`, `frame: false`(제목표시줄 없음)다.
그래서 이 화면도 **닫기/최소화 버튼을 직접 그려야 한다.**
버튼 동작은 이미 있는 `windowAPI.minimizeWindow()` / `windowAPI.closeWindow()` 를 쓴다.

아이콘 경로는 메인 화면(`src/renderer/index.html`)과 동일하다.
단, 이 파일은 `pages/` 안에 있으므로 경로 앞에 `../` 가 붙는다.

---

### 할 일 1 — `src/renderer/pages/login.html` 생성

```html
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 회의록 녹음기 - 로그인</title>
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@100;300;400;500;700;900&display=swap"
    />
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }

      body {
        font-family: "Noto Sans KR", sans-serif;
        height: 100vh;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        background: #ffffff;
      }

      /* 프레임 없는 창이라 제목 영역을 직접 그린다. -webkit-app-region 으로 드래그 이동을 준다. */
      .title-area {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        -webkit-app-region: drag;
      }
      .title-text { font-size: 18px; font-weight: 600; }
      .title-right { display: flex; gap: 8px; -webkit-app-region: no-drag; }
      .title-right button {
        background: none; border: none; cursor: pointer; padding: 0;
      }

      .login-body {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 16px;
        padding: 0 24px 32px;
        text-align: center;
      }

      .login-title { font-size: 16px; font-weight: 600; }
      .login-desc { font-size: 13px; line-height: 1.6; color: #666; }

      #retryBtn {
        margin-top: 8px;
        padding: 10px 20px;
        font-family: inherit;
        font-size: 14px;
        border: 1px solid #d0d0d0;
        border-radius: 6px;
        background: #fff;
        cursor: pointer;
      }
      #retryBtn:hover { background: #f5f5f5; }

      /* 로그인 실패 시에만 보인다. */
      #errorText { font-size: 12px; color: #d33; min-height: 18px; }
    </style>
  </head>

  <body>
    <div class="title-area">
      <div class="title-text">AI 회의록 녹음기</div>
      <div class="title-right">
        <button id="minimizeBtn">
          <img src="../assets/icons/minalizeBtn.svg" alt="최소화" />
        </button>
        <button id="closeBtn">
          <img src="../assets/icons/closeBtn.svg" alt="닫기" />
        </button>
      </div>
    </div>

    <div class="login-body">
      <div class="login-title">로그인이 필요합니다</div>
      <div class="login-desc">
        브라우저에서 로그인을 완료해주세요.<br />
        완료되면 이 화면이 자동으로 넘어갑니다.
      </div>
      <div id="errorText"></div>
      <button id="retryBtn">브라우저에서 다시 로그인</button>
    </div>

    <script src="../scripts/login.js"></script>
  </body>
</html>
```

---

### 할 일 2 — `src/renderer/scripts/login.js` 생성

```js
// 로그인 대기 화면
// - 실제 로그인은 브라우저에서 이뤄진다. 이 화면은 대기와 안내만 담당한다.
// - 로그인 완료는 딥링크 → 토큰 교환 → main 이 보내는 auth-exchanged 로 알게 된다.

const retryBtn = document.getElementById("retryBtn");
const errorText = document.getElementById("errorText");
const minimizeBtn = document.getElementById("minimizeBtn");
const closeBtn = document.getElementById("closeBtn");

// 브라우저를 여러 번 여는 것을 막는다(사용자가 버튼을 연타하는 경우).
let opening = false;

async function openLogin() {
  if (opening) return;
  opening = true;
  errorText.textContent = "";
  try {
    const res = await window.authAPI.openLogin();
    if (!res || !res.success) {
      errorText.textContent = "브라우저를 열지 못했습니다. 다시 시도해주세요.";
    }
  } catch (_) {
    errorText.textContent = "브라우저를 열지 못했습니다. 다시 시도해주세요.";
  } finally {
    opening = false;
  }
}

// 로그인 실패 사유를 사용자 문구로 바꾼다.
// main 이 보내는 error 값은 main.js 의 processDeepLink() 참고.
function toErrorMessage(error) {
  if (error === "invalid_parameters") return "로그인 정보가 올바르지 않습니다. 다시 시도해주세요.";
  if (error === "invalid_host") return "서버 주소가 올바르지 않습니다. 관리자에게 문의해주세요.";
  if (error === "network_error") return "서버에 연결하지 못했습니다. 네트워크를 확인해주세요.";
  return "로그인에 실패했습니다. 다시 시도해주세요.";
}

// 토큰 교환 결과 수신
window.electronAPI.onAuthExchanged((payload) => {
  if (payload && payload.success) {
    // 메인 화면으로 이동. 기존 load-index IPC 를 그대로 쓴다.
    window.electronAPI.loadIndex();
    return;
  }
  errorText.textContent = toErrorMessage(payload && payload.error);
});

retryBtn.addEventListener("click", openLogin);
minimizeBtn.addEventListener("click", () => window.windowAPI.minimizeWindow());
closeBtn.addEventListener("click", () => window.windowAPI.closeWindow());

// 화면이 뜨면 브라우저를 자동으로 1회 연다.
openLogin();
```

---

### 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/renderer/scripts/login.js','utf8')); console.log('문법 OK')"
ls -l src/renderer/pages/login.html src/renderer/scripts/login.js
```

두 파일이 존재하고 `문법 OK` 가 나오면 성공.
**화면 확인은 작업 7 이후에 한다** (아직 앱이 이 화면을 띄우지 않는다).


---


<a id="07_main_gate"></a>

## 📄 원본 파일: `07_main_gate.md`


## 작업 7 — 로그인 게이트 연결 (마지막 조립 단계)

**손대는 파일**: `src/main/main.js` — **수정**
**다른 파일은 건드리지 않는다.**

> ⚠️ **작업 1~6이 모두 끝난 뒤에 진행할 것.** 이 작업이 앞의 조각들을 이어 붙인다.

---

### 왜 필요한가

지금까지 만든 것들(설정, 조회 모듈, IPC, preload, 로그인 화면)은
아직 아무도 부르지 않는다. 두 가지를 연결하면 로그인이 동작한다.

1. **앱 시작 시** — 로그인 안 되어 있으면 `index.html` 대신 `login.html` 을 띄운다
2. **토큰 교환 성공 시** — 내 정보를 조회해서 저장한 뒤 화면에 알린다

---

### 할 일 — 2군데 수정

#### 7-1. 시작 화면 분기

토큰은 메모리에만 보관하므로, 앱을 새로 켜면 항상 로그인 화면부터 시작한다.

**[찾을 코드]** (306번째 줄 근처, `createWindow()` 함수 안)
```js
  mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  try { logger.logInfo('window_created', { windowId: mainWindow.id, route: 'index.html' }); } catch (_) {}
```

> 주의: `loadFile(... "../renderer/index.html")` 은 이 파일에 4군데 있다.
> **바로 아래 줄에 `window_created` 로그가 붙어 있는 것**만 고친다.

**[바꿀 코드]**
```js
  // 토큰은 메모리에만 보관하므로(앱 종료 시 소멸) 새로 켜면 항상 로그인 화면부터 시작한다.
  // 인증 후에는 login.js 가 load-index IPC 로 index.html 을 띄운다.
  const startRoute = authService.isAuthenticated()
    ? "../renderer/index.html"
    : "../renderer/pages/login.html";
  mainWindow.loadFile(path.join(__dirname, startRoute));
  try { logger.logInfo('window_created', { windowId: mainWindow.id, route: startRoute }); } catch (_) {}
```

---

#### 7-2. 토큰 교환 성공 직후 내 정보 조회

`processDeepLink()` 함수 안(268번째 줄 근처)을 고친다.

**[찾을 코드]**
```js
    authService.setSession({
      accessToken: exchangeResult.result,
      refreshToken: exchangeResult.refreshToken,
      endpoint,
    });
    try { logger.logInfo('deeplink_exchange_success'); } catch (_) {}

    broadcastAuthExchanged({ success: true, endpoint });
```

**[바꿀 코드]**
```js
    authService.setSession({
      accessToken: exchangeResult.result,
      refreshToken: exchangeResult.refreshToken,
      endpoint,
    });
    try { logger.logInfo('deeplink_exchange_success'); } catch (_) {}

    // 사용자 정보를 미리 받아둔다.
    // 실패해도 로그인 자체는 성공으로 처리한다 — 이름 표시가 안 될 뿐,
    // 토큰은 유효하므로 녹음·업로드는 정상 동작해야 한다.
    try {
      const meResult = await userService.fetchMyInfo();
      if (meResult.success) {
        authService.setProfile(userService.toProfile(meResult.data));
        try { logger.logInfo('auth_profile_loaded'); } catch (_) {}
      } else {
        try { logger.logWarn('auth_profile_load_failed', { error: meResult.error }); } catch (_) {}
      }
    } catch (err) {
      try { logger.logWarn('auth_profile_load_error', { message: err && err.message }); } catch (_) {}
    }

    broadcastAuthExchanged({
      success: true,
      endpoint,
      profile: authService.getProfile(),
    });
```

---

### 확인 방법

#### 1) 문법 검사
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법 OK')"
```

#### 2) 화면 확인
```bash
yarn start
```
- 로그인 대기 화면("로그인이 필요합니다")이 뜬다
- 기본 브라우저가 자동으로 열린다
- 브라우저 주소가 `작업 1`에서 설정한 로그인 URL 인지 확인

#### 3) 로그인 완료 확인

브라우저 로그인 완료 후 앱이 **자동으로 마이크 테스트 화면으로 전환**되면 성공.

단, 개발 모드에서는 OS마다 딥링크가 도달하는 방식이 다르다.
**자세한 절차는 `09_dev_deeplink_test.md` 를 볼 것.**

| 환경 | 방법 |
|---|---|
| Windows 개발 | 작업 9의 등록 수정 후 실제 딥링크로 테스트 |
| macOS 개발 | 딥링크가 안 온다. 작업 9의 시뮬레이션 훅 사용 |
| 빌드본 | `npm run build` (macOS는 `npm run register-protocol` 추가) |

> 실행은 `npm start -- --dev` 로 한다. `npm run dev`(electronmon)는
> argv에 플래그가 섞여 딥링크 등록 경로가 어긋날 수 있다.

#### 4) 로그로 확인
성공 시 아래 순서로 로그가 찍힌다.
```
deeplink_received
deeplink_exchange_begin
exchange_token_success
deeplink_exchange_success
fetch_my_info_success       ← 내 정보 조회 API 경로가 맞을 때만
auth_profile_loaded
```

`fetch_my_info_failed` 가 나오면 **작업 3의 `ME_PATH` 값이 틀린 것**이다.
그 경우 서버 담당자에게 실제 경로를 확인해 `userService.js` 의 `ME_PATH` 만 고친다.
로그인 자체는 그대로 성공한다.

---

### 문제가 생겼을 때

| 증상 | 원인 | 조치 |
|---|---|---|
| 로그인 화면이 안 뜨고 바로 메인 화면 | 7-1이 적용 안 됨 | `startRoute` 코드가 들어갔는지 확인 |
| 브라우저가 안 열림 | `shell` import 누락 | 작업 4-1 확인 |
| 화면이 하얗게 뜸 | `login.js` 경로 오류 | `login.html` 의 `<script src="../scripts/login.js">` 확인 |
| 로그인 후 화면이 안 넘어감 | `auth-exchanged` 미수신 | 개발 모드에서 딥링크가 안 온 것 → `09_dev_deeplink_test.md` 참고 |


---


<a id="08_title_username"></a>

## 📄 원본 파일: `08_title_username.md`


## 작업 8 — 타이틀에 로그인 사용자 이름 표시 (부가 작업)

**손대는 파일**
- `src/renderer/index.html` — **수정**
- `src/renderer/index.js` — **수정**

**다른 파일은 건드리지 않는다.**

> 이 작업은 로그인 기능과 무관한 부가 작업이다. 작업 1~7이 끝난 뒤에 한다.

---

### 왜 필요한가

`src/renderer/index.html` 22번째 줄에 개발자 이름이 하드코딩되어 있다.

```html
<div class="title-text">AI 회의록 녹음기(노성남)</div>
```

이걸 **로그인한 사용자 이름**으로 바꾼다.
이름을 못 가져오면 괄호 없이 `AI 회의록 녹음기` 만 나오게 한다
(하드코딩된 이름이 남는 것보다 낫다).

---

### 할 일 — 2군데 수정

#### 8-1. `src/renderer/index.html` — 이름 자리 비우기

**[찾을 코드]** (22번째 줄)
```html
        <div class="title-text">AI 회의록 녹음기(노성남)</div>
```

**[바꿀 코드]**
```html
        <div class="title-text">AI 회의록 녹음기<span id="userNameLabel"></span></div>
```

> `<span>` 은 비워둔다. 값을 못 받으면 아무것도 안 보이는 게 정상이다.

---

#### 8-2. `src/renderer/index.js` — 이름 채우기

**파일 맨 아래에** 아래 코드를 추가한다. (기존 코드는 건드리지 않는다)

```js
// --- 타이틀 사용자 이름 ---------------------------------------------------
// 로그인한 사용자 이름을 타이틀에 붙인다.
// 이름을 못 가져오면 아무것도 표시하지 않는다(빈 괄호가 남지 않도록).
(async () => {
  const label = document.getElementById("userNameLabel");
  if (!label) return;

  try {
    const res = await window.authAPI.getProfile();
    const userName = res && res.success && res.profile ? res.profile.userName : "";
    if (userName) label.textContent = `(${userName})`;
  } catch (_) {
    // 조회 실패는 무시한다. 이름 표시는 녹음 기능과 무관하다.
  }
})();
```

---

### 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/renderer/index.js','utf8')); console.log('문법 OK')"
grep -n "노성남" src/renderer/index.html
```

- `문법 OK` 출력
- `grep` 결과가 **아무것도 안 나오면** 성공 (하드코딩 제거됨)

앱 실행 후 로그인하면 타이틀이 `AI 회의록 녹음기(로그인한이름)` 으로 보인다.

---

### 이름이 안 나올 때

이름 표시는 아래가 모두 맞아야 동작한다. 순서대로 확인한다.

1. **작업 3의 `ME_PATH`** 가 실제 API 경로인가?
   → 로그에 `fetch_my_info_success` 가 찍히는지 확인
2. **작업 3의 `toProfile()`** 이 이름 필드를 찾고 있는가?
   → 서버 응답의 실제 필드명이 `userName`/`name`/`userNm`/`nickName` 중에 없으면
     `toProfile()` 의 후보 목록에 실제 필드명을 추가한다

**서버 스펙 확인이 안 되면** 이 작업은 8-1만 적용해도 된다.
그러면 타이틀이 `AI 회의록 녹음기` 로만 나오고, 하드코딩된 이름은 사라진다.


---


<a id="09_dev_deeplink_test"></a>

## 📄 원본 파일: `09_dev_deeplink_test.md`


## 작업 9 — 개발 모드에서 딥링크 테스트하기

**손대는 파일**
- `src/main/main.js` — **수정 2곳**
- `src/main/preload.js` — **수정 1곳**

**다른 파일은 건드리지 않는다.**

> ⚠️ **작업 4가 끝난 뒤에 진행할 것.** (`authConfig` require 가 필요하다)
> 이 작업은 **기능이 아니라 테스트 수단**이다. 로그인 자체는 작업 7까지로 이미 완성이다.

---

### 왜 필요한가

로그인은 `브라우저 → 딥링크 → 앱` 순서로 동작하는데,
**개발 모드에서는 딥링크가 앱까지 도달하지 않는다.** 그래서 개발 중에는
로그인 완료 이후를 테스트할 방법이 없다.

원인은 `main.js:1265` 다.

```js
// 프로토콜 기본 앱 등록 (빌드 환경에서만)
if (!process.defaultApp) {          // 패키징된 앱일 때만 true
  app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
}
// 개발 모드에서는 등록하지 않음 (LaunchServices 충돌 방지)
```

`electron .` 으로 실행하면 `process.defaultApp === true` 라서 등록을 건너뛴다.
**의도적으로 막아둔 것이고, macOS 에서는 이 판단이 맞다.**

#### OS 별 사정이 다르다

| | 개발 모드 딥링크 | 이유 |
|---|---|---|
| **Windows** | **되게 만들 수 있음** | 레지스트리에 `electron.exe + 앱경로` 형태로 등록 가능 |
| **macOS** | **사실상 불가** | 아래 참고 |

**macOS 가 안 되는 이유**: macOS 는 URL 스킴 주인을 **앱 번들의 `Info.plist`
(CFBundleURLTypes)** 로 판단한다. 개발 모드의 번들은
`node_modules/electron/dist/Electron.app` 인데, 여기에 스킴을 등록하면
스킴 주인이 "Electron.app" 이 되어 **빌드본으로 가야 할 딥링크까지 가로챈다.**
`main.js` 주석의 "LaunchServices 충돌"이 이 얘기다.

그래서 이 문서는 **Windows 는 실제 딥링크를, macOS 는 시뮬레이션을** 쓴다.

---

### 할 일 — 3군데 수정

#### 9-1. Windows 개발 모드 프로토콜 등록 (`main.js`)

**[찾을 코드]**
```js
  // 프로토콜 기본 앱 등록 (빌드 환경에서만)
  try {
    if (!process.defaultApp) {
      // 프로덕션 빌드에서만 등록
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
    }
    // 개발 모드에서는 등록하지 않음 (LaunchServices 충돌 방지)
    // 빌드 후 자동 등록: scripts/register-protocol.js (afterPack 훅)
  } catch (_) {}
```

**[바꿀 코드]**
```js
  // 프로토콜 기본 앱 등록
  try {
    if (!process.defaultApp) {
      // 프로덕션 빌드에서만 등록
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME);
    } else if (process.platform === "win32") {
      // Windows 개발 모드: 레지스트리는 "실행파일 + 인자" 형태로 등록할 수 있어,
      // electron.exe 에 앱 경로를 붙여두면 개발 중에도 실제 딥링크를 받을 수 있다.
      // argv[1] 은 electronmon 이 끼워넣는 --require 등에 밀릴 수 있어 신뢰하지 않는다.
      app.setAsDefaultProtocolClient(PROTOCOL_SCHEME, process.execPath, [app.getAppPath()]);
    }
    // macOS 개발 모드에서는 등록하지 않는다.
    // macOS 는 앱 번들 Info.plist 로 스킴 주인을 정하는데, 개발 번들
    // (node_modules/electron/dist/Electron.app)로 주인이 바뀌면 빌드본으로 가야 할
    // 딥링크까지 가로챈다(LaunchServices 충돌).
    // → macOS 는 아래 dev:simulate-deeplink 로 테스트한다.
    // 빌드 후 자동 등록: scripts/register-protocol.js (afterPack 훅)
  } catch (_) {}
```

---

#### 9-2. 딥링크 시뮬레이션 IPC 추가 (`main.js`)

`ipcMain.handle("load-index", () => {` 를 파일에서 찾는다.
**그 줄 바로 위에** 아래 코드를 통째로 삽입한다.

> 작업 4에서 넣은 인증 IPC 들도 같은 위치에 넣었으므로,
> 이 코드는 그 아래·`load-index` 위에 자리하게 된다. 순서는 상관없다.

```js
// --- 개발용 딥링크 시뮬레이션 -------------------------------------------
// macOS 개발 모드에서는 실제 딥링크가 앱까지 오지 않는다(위 프로토콜 등록 주석 참고).
// 브라우저에서 받은 code 만 넣으면 딥링크가 온 것처럼 처리해서,
// OS 라우팅을 제외한 전 과정(토큰 교환 → 내 정보 조회 → 화면 전환)을 검증할 수 있다.
// --dev 플래그로 실행했을 때만 등록되므로 프로덕션 빌드에는 존재하지 않는다.
if (process.argv.includes("--dev")) {
  ipcMain.handle("dev:simulate-deeplink", async (event, input) => {
    try {
      const value = String(input || "").trim();
      if (!value) return { success: false, error: "empty_input" };

      // 전체 URL 을 그대로 넣어도 되고, code 값만 넣어도 된다.
      // code 만 준 경우 host 는 authConfig 의 기본 주소를 base64 로 붙인다.
      const isFullUrl = value
        .toLowerCase()
        .startsWith((PROTOCOL_SCHEME + "://").toLowerCase());

      const url = isFullUrl
        ? value
        : `${PROTOCOL_SCHEME}://connect?code=${encodeURIComponent(value)}` +
          `&host=${Buffer.from(authConfig.WEB_BASE_URL, "utf8").toString("base64")}`;

      try { logger.logInfo("dev_simulate_deeplink", { isFullUrl }); } catch (_) {}
      await processDeepLink(url);
      return { success: true, url };
    } catch (err) {
      return { success: false, error: err && err.message };
    }
  });
}
```

---

#### 9-3. 렌더러에 시뮬레이션 함수 노출 (`preload.js`)

이미 있는 `developerAPI` 안에 함수 하나만 추가한다. 새 API 를 만들지 않는다.

**[찾을 코드]** (파일 맨 끝)
```js
  sendDebug: (message, context) => {
    ipcRenderer.invoke('send-debug', message, context)
  },
});
```

**[바꿀 코드]**
```js
  sendDebug: (message, context) => {
    ipcRenderer.invoke('send-debug', message, context)
  },

  // 개발용 딥링크 시뮬레이션.
  // 개발자도구 콘솔에서 직접 호출한다:
  //   developerAPI.simulateDeepLink('브라우저에서받은code')
  // main 쪽 핸들러가 --dev 실행일 때만 등록되므로, 프로덕션에서는 호출해도 실패한다.
  simulateDeepLink: (input) => {
    return ipcRenderer.invoke('dev:simulate-deeplink', input)
  },
});
```

---

### 실행 방법 — 이 프로젝트의 스크립트 2개 구분

`package.json` 에 실행 스크립트가 두 개 있다.

```json
"start": "electron .",            // 순수 electron
"dev":   "electronmon . --dev",   // 핫리로드 + 개발자도구
```

| 용도 | 명령 |
|---|---|
| 평소 개발 (파일 저장 시 자동 재시작) | `npm run dev` |
| **딥링크 / 로그인 테스트** | `npm start -- --dev` |
| 최종 검증 | `npm run build` 후 빌드본 실행 |

**딥링크 테스트에 `npm start -- --dev` 를 쓰는 이유**:
`electronmon` 은 electron 을 감싸 실행하면서 `--require` 같은 인자를 끼워넣는다
(`main.js:1231` 주석에 이미 기록되어 있음).
Windows 레지스트리 등록 시 경로가 어긋날 수 있어, 딥링크를 볼 때는
`electron .` 을 직접 쓰는 편이 안전하다.
`--dev` 를 붙여야 개발자도구가 열리고(`main.js:1327`) 시뮬레이션 IPC 도 등록된다.

---

### 테스트 절차

#### macOS — 시뮬레이션으로 테스트

1. 앱 실행
   ```bash
   npm start -- --dev
   ```
2. 로그인 대기 화면이 뜨고 브라우저가 자동으로 열린다
3. 브라우저에서 SSO 로그인을 끝까지 진행한다
4. 로그인 완료 후 **브라우저 주소창의 `code` 값**을 복사한다
   - 웹이 `timbloRecApp://connect?code=XXXX&host=...` 로 넘어가려다 실패하면
     그 URL 이 주소창이나 브라우저 경고창에 보인다. 거기서 `code` 를 꺼낸다
5. 앱의 **개발자도구 콘솔**에 입력한다
   ```js
   developerAPI.simulateDeepLink('복사한code값')
   ```
   URL 전체를 복사했다면 그대로 넣어도 된다.
   ```js
   developerAPI.simulateDeepLink('timbloRecApp://connect?code=XXXX&host=aHR0cHM6...')
   ```
6. 앱이 마이크 테스트 화면으로 전환되면 성공

#### Windows — 실제 딥링크로 테스트

1. 앱 실행 (한 번 실행해야 레지스트리에 등록된다)
   ```bash
   npm start -- --dev
   ```
2. 앱을 켜 둔 채로, 다른 터미널에서
   ```cmd
   start "" "timbloRecApp://connect?code=test&host=aHR0cHM6Ly9kZXYudGltYmxvLmlv"
   ```
3. 로그에 `deeplink_received` 가 찍히면 **OS 라우팅 성공**
   (`code=test` 는 가짜라서 교환은 실패한다. 여기서는 라우팅만 확인하는 것)
4. 실제 로그인은 브라우저에서 끝까지 진행하면 자동으로 앱까지 들어온다

> `host` 값은 서버 주소를 base64 로 인코딩한 것이다.
> `aHR0cHM6Ly9kZXYudGltYmxvLmlv` = `https://dev.timblo.io`
> 다른 주소가 필요하면:
> ```bash
> node -e "console.log(Buffer.from('https://내서버주소').toString('base64'))"
> ```

#### 빌드본으로 최종 확인 (양쪽 OS 공통)

```bash
npm run build
npm run register-protocol    # macOS 전용. LaunchServices 에 빌드본 등록
```

macOS 에서는 빌드본을 한 번 실행하거나 위 명령을 돌려야
`timbloRecApp://` 의 주인이 빌드본으로 잡힌다.

---

### 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('main OK')"
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/preload.js','utf8')); console.log('preload OK')"
grep -n "dev:simulate-deeplink" src/main/main.js src/main/preload.js
```

`main OK`, `preload OK` 와 함께 두 파일에서 `dev:simulate-deeplink` 가 보이면 성공.

---

### 문제가 생겼을 때

| 증상 | 원인 | 조치 |
|---|---|---|
| 콘솔에서 `developerAPI is not defined` | preload 수정 누락 | 9-3 확인 |
| `No handler registered for 'dev:simulate-deeplink'` | `--dev` 없이 실행함 | `npm start -- --dev` 로 재실행 |
| Windows에서 `deeplink_received` 가 안 찍힘 | 레지스트리 등록 실패 | 앱을 한 번 실행했는지, 9-1이 적용됐는지 확인 |
| Windows에서 앱이 새로 하나 더 뜸 | 단일 인스턴스 락 미동작 | `main.js:1198` `requestSingleInstanceLock()` 결과 확인 |
| macOS에서 `open` 하면 dist 빌드본이 뜸 | 정상 동작 | macOS 는 시뮬레이션으로 테스트할 것 |

> **미검증 사항**: Windows 에서 딥링크가 들어올 때 새 electron 프로세스가
> 기존 개발 인스턴스와 같은 앱으로 인식되어 `second-instance` 가 발생하는지는
> Windows 실기에서 확인이 필요하다. 로그에 `deeplink_received` 가 찍히면 정상이다.


---
