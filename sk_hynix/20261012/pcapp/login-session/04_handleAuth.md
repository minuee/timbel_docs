# 작업 4 — 로그인 게이트 + 인증 IPC 모듈 만들기

**손대는 파일**: `src/main/ipc/handleAuth.js` — **신규** (이미 있으면 통째로 덮어쓰기)
**다른 파일은 건드리지 않는다.**
**선행 작업**: 작업 1, 2

## 왜 필요한가
메인 창의 "홈"을 로그인 여부에 따라 고른다.
- 로그인 전: `src/renderer/pages/login.html`
- 로그인 후: `src/renderer/index.html` (마이크 테스트)

그리고 로그인 화면이 쓸 IPC 3개를 등록한다.

| 채널 | 하는 일 |
|---|---|
| `auth:get-status` | 로그인 여부, 사번 로그인 폼을 보일지 |
| `auth:open-sso` | 기본 브라우저로 MyAccess(SSO) 로그인 페이지 열기 |
| `auth:login-empno` | 사번으로 로그인. 성공하면 메인 화면으로 넘김 |

**녹음 화면에 있을 때는 세션이 끊겨도 화면을 바꾸지 않는다.** 녹음이 끊기면 안 되기 때문이다.

`src/main/ipc/` 폴더는 이미 있다(`handleWindow.js` 가 들어 있음).

## 할 일
아래 내용 그대로 `src/main/ipc/handleAuth.js` 파일을 만든다.

```js
// 로그인 게이트와 인증 IPC
// - 메인 창의 "홈"은 로그인 여부에 따라 둘 중 하나다.
//     로그인 전 : renderer/pages/login.html
//     로그인 후 : renderer/index.html (마이크 테스트)
//   main.js 에서 index.html 을 직접 띄우던 곳은 모두 loadHome() 을 거친다.
// - 녹음 화면(recordingWindow.html)에 있을 때는 세션이 끊겨도 화면을 빼앗지 않는다.
//   녹음이 끊기면 안 되기 때문이다. 업로드가 실패하면 업로드 리스트에 남고,
//   홈으로 돌아오는 순간 로그인 화면이 뜬다.

const path = require('path');
const { ipcMain, shell } = require('electron');
const logger = require('../logger');
const authService = require('../services/authService');
const authConfig = require('../services/authConfig');

const INDEX_PAGE = path.join(__dirname, '../../renderer/index.html');
const LOGIN_PAGE = path.join(__dirname, '../../renderer/pages/login.html');

let getMainWindow = () => null;

function currentUrl(win) {
  try { return win.webContents.getURL() || ''; } catch (_) { return ''; }
}

function loadHome() {
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return { success: false, error: 'mainWindow_unavailable' };
  const page = authService.isAuthenticated() ? INDEX_PAGE : LOGIN_PAGE;
  win.loadFile(page);
  try { logger.logInfo('load_home', { route: path.basename(page) }); } catch (_) {}
  return { success: true };
}

// 로그인 성공 직후 호출. 로그인 화면에 있을 때만 메인 화면으로 넘긴다.
// (이미 로그인한 상태에서 딥링크가 또 와도 녹음 중인 화면을 건드리지 않기 위함)
function onAuthenticated() {
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  if (currentUrl(win).endsWith('/pages/login.html')) loadHome();
}

function registerAuthIpc(options) {
  getMainWindow = options.getMainWindow;

  // 갱신까지 실패하면 마이크 테스트 화면에 있을 때만 로그인 화면으로 보낸다.
  authService.onSessionExpired(() => {
    const win = getMainWindow();
    if (!win || win.isDestroyed()) return;
    if (currentUrl(win).endsWith('/renderer/index.html')) loadHome();
  });

  ipcMain.handle('auth:get-status', () => ({
    authenticated: authService.isAuthenticated(),
    empnoLoginEnabled: authConfig.EMPNO_LOGIN_ENABLED,
  }));

  // "MyAccess 로그인" → 기본 브라우저로 SSO 페이지를 연다.
  // 로그인이 끝나면 웹이 timbloRecApp://connect 딥링크를 호출하고, main.js 의 processDeepLink 가 이어받는다.
  ipcMain.handle('auth:open-sso', async () => {
    try {
      const url = new URL(authConfig.SSO_LOGIN_URL);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new Error('invalid_protocol');
      await shell.openExternal(url.toString());
      try { logger.logInfo('sso_browser_opened', { host: url.host }); } catch (_) {}
      return { success: true };
    } catch (err) {
      try { logger.logError('sso_browser_open_failed', { message: err && err.message }); } catch (_) {}
      return { success: false, error: err && err.message };
    }
  });

  // 사번 직접 로그인. 토큰은 메인 프로세스에만 두고 렌더러에는 성공 여부만 돌려준다.
  ipcMain.handle('auth:login-empno', async (_event, payload) => {
    if (!authConfig.EMPNO_LOGIN_ENABLED) return { success: false, error: 'empno_login_disabled' };
    const empno = payload && payload.empno;
    const password = payload && payload.password;
    const result = await authService.loginWithEmpno(empno, password);
    if (result.success) onAuthenticated();
    return result;
  });
}

module.exports = { registerAuthIpc, loadHome, onAuthenticated };
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/ipc/handleAuth.js','utf8')); console.log('문법OK')"
node -e "const s=require('fs').readFileSync('src/main/ipc/handleAuth.js','utf8'); console.log(s.includes('auth:open-sso'), s.includes('auth:login-empno'), s.includes('module.exports = { registerAuthIpc, loadHome, onAuthenticated }'))"
```
문법OK 와 `true true true` 가 나오면 성공.
