# 작업 4 — main.js 에 인증 IPC 핸들러 추가

**손대는 파일**: `src/main/main.js` — **수정**
**다른 파일은 건드리지 않는다.**

---

## 왜 필요한가

렌더러(화면)는 브라우저를 직접 열 수 없고, 서버 토큰에도 접근할 수 없다.
그래서 메인 프로세스에 창구(IPC 핸들러)를 만들고, 화면은 그걸 호출만 한다.

만들 창구는 3개다.

| 채널명 | 하는 일 |
|---|---|
| `auth:open-login` | 기본 브라우저로 SSO 로그인 페이지를 연다 |
| `auth:get-status` | 지금 로그인 상태인지 알려준다 |
| `auth:get-profile` | 로그인한 사용자 정보를 알려준다 |

---

## 할 일 — 3군데 수정

### 4-1. `shell` 모듈 import 추가

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

### 4-2. 새 모듈 require 추가

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

### 4-3. IPC 핸들러 3개 추가

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

## 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법 OK')"
```

`문법 OK` 가 출력되면 성공. (실행 테스트는 작업 7 이후에 한다)
