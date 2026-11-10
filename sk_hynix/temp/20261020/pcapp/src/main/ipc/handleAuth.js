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
const userService = require('../services/userService');
const templateService = require('../services/templateService');
const sessionStore = require('../services/sessionStore');
const loginPrefs = require('../services/loginPrefs');

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

// 로그인 성공 직후 호출. 사용자 정보를 받아 둔 뒤, 로그인 화면에 있을 때만 메인 화면으로 넘긴다.
// (이미 로그인한 상태에서 딥링크가 또 와도 녹음 중인 화면을 건드리지 않기 위함)
// 사용자 정보 조회가 실패해도 로그인은 성공으로 본다. 타이틀에 이름이 안 나올 뿐이다.
async function onAuthenticated() {
  try { await userService.loadProfileAfterLogin(); } catch (_) {}
  // 업로드 팝업용 템플릿 목록을 미리 받아 둔다(기다리지 않음)
  templateService.refresh().catch(() => {});
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  if (currentUrl(win).endsWith('/pages/login.html')) loadHome();
}

// 로그인 결과 사용자 동작 로그. 실패 사유는 서버 메시지(있으면)와 에러 코드
function logLoginResult(method, result, extra) {
  try {
    if (result && result.success) {
      logger.logUserAction('login_success', { method, ...extra });
    } else {
      logger.logUserAction('login_failed', {
        method,
        ...extra,
        reason: result && result.error,
        httpCode: result && result.httpCode,
        serverMessage: result && result.message,
      });
    }
  } catch (_) {}
}

function registerAuthIpc(options) {
  getMainWindow = options.getMainWindow;
  const getActiveUploadCount = options.getActiveUploadCount || (() => 0);
  const onLoggedOut = options.onLoggedOut || (() => {});

  // 갱신까지 실패하면 마이크 테스트 화면에 있을 때만 로그인 화면으로 보낸다.
  authService.onSessionExpired(() => {
    try { logger.logUserAction('logout', { reason: 'session_expired' }); } catch (_) {}
    const win = getMainWindow();
    if (!win || win.isDestroyed()) return;
    if (currentUrl(win).endsWith('/renderer/index.html')) loadHome();
  });

  // profile 에는 토큰이 없다(이름·사번·이메일·워크스페이스만).
  // loginPrefs: 로그인 화면 체크박스("사번 저장", "로그인 유지")의 마지막 값과 저장해 둔 사번.
  // keepLoginEnabled 가 false(SESSION_PERSIST_ENABLED=false)면 "로그인 유지" 체크박스를 숨긴다.
  ipcMain.handle('auth:get-status', () => ({
    authenticated: authService.isAuthenticated(),
    empnoLoginEnabled: authConfig.EMPNO_LOGIN_ENABLED,
    manualLoginEnabled: authConfig.MANUAL_LOGIN_ENABLED,
    keepLoginEnabled: sessionStore.isEnabled(),
    loginPrefs: loginPrefs.get(),
    defaultEndpoint: authConfig.DEFAULT_API_BASE_URL,
    profile: authService.getProfile(),
  }));

  // 로그인 화면 체크박스가 바뀔 때마다 저장한다. SSO 는 브라우저 → 딥링크로 돌아오므로
  // 로그인 버튼을 누르기 전에 값이 메인 프로세스에 있어야 한다(세션 저장 여부는 sessionStore 가 이 값을 본다).
  ipcMain.handle('auth:set-login-options', (_event, payload) => {
    const input = payload || {};
    loginPrefs.setOptions({
      rememberEmpno: input.rememberEmpno === true,
      keepLogin: input.keepLogin === true,
    });
    return { success: true };
  });

  // "MyAccess 로그인" → 기본 브라우저로 SSO 페이지를 연다.
  // 로그인이 끝나면 웹이 timbloRecApp://connect 딥링크를 호출하고, main.js 의 processDeepLink 가 이어받는다.
  ipcMain.handle('auth:open-sso', async () => {
    try {
      const url = new URL(authConfig.SSO_LOGIN_URL);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new Error('invalid_protocol');
      try { logger.logUserAction('login_attempt', { method: 'sso' }); } catch (_) {}
      await shell.openExternal(url.toString());
      try { logger.logInfo('sso_browser_opened', { host: url.host }); } catch (_) {}
      return { success: true };
    } catch (err) {
      try { logger.logError('sso_browser_open_failed', { message: err && err.message }); } catch (_) {}
      try { logger.logUserAction('login_failed', { method: 'sso', reason: 'sso_browser_open_failed' }); } catch (_) {}
      return { success: false, error: err && err.message };
    }
  });

  // 사번 직접 로그인. 토큰은 메인 프로세스에만 두고 렌더러에는 성공 여부만 돌려준다.
  ipcMain.handle('auth:login-empno', async (_event, payload) => {
    if (!authConfig.EMPNO_LOGIN_ENABLED) return { success: false, error: 'empno_login_disabled' };
    const empno = payload && payload.empno;
    const password = payload && payload.password;
    try { logger.logUserAction('login_attempt', { method: 'empno', empno }); } catch (_) {}
    const result = await authService.loginWithEmpno(empno, password);
    logLoginResult('empno', result, { empno });
    if (result.success) {
      // "사번 저장" 이 켜져 있으면 다음 로그인 화면에 채워 둔다(꺼져 있으면 지운다). 비밀번호는 저장하지 않는다.
      loginPrefs.rememberEmpno(empno);
      await onAuthenticated();
    }
    return result;
  });

  // 로그아웃(설정 메뉴). 녹음 중인지는 화면(recording.js)이 먼저 막는다.
  // 서버로 업로드 중이면 막는다 — 토큰이 사라지면 전송 중인 업로드가 실패한다.
  // 세션(토큰·사용자 정보)을 지운다(로그인 유지로 저장해 둔 파일도 같이). 녹음 파일·업로드 리스트는 그대로 둔다.
  ipcMain.handle('auth:logout', () => {
    if (getActiveUploadCount() > 0) {
      try { logger.logUserAction('logout_blocked', { reason: 'uploading' }); } catch (_) {}
      return { success: false, error: 'uploading' };
    }
    try { logger.logUserAction('logout', { reason: 'user' }); } catch (_) {}
    authService.clearSession();
    try { onLoggedOut(); } catch (_) {}
    loadHome();
    return { success: true };
  });

  // 테스트용 수동 로그인. 서버 주소를 비우면 DEFAULT_API_BASE_URL 을 쓴다.
  ipcMain.handle('auth:login-manual', async (_event, payload) => {
    if (!authConfig.MANUAL_LOGIN_ENABLED) return { success: false, error: 'manual_login_disabled' };
    const input = payload || {};
    try { logger.logUserAction('login_attempt', { method: 'manual', empno: input.empno }); } catch (_) {}
    const result = authService.startManualSession({
      name: input.name,
      empno: input.empno,
      accessToken: input.accessToken,
      endpoint: String(input.endpoint || '').trim() || authConfig.DEFAULT_API_BASE_URL,
    });
    logLoginResult('manual', result, { empno: input.empno });
    if (result.success) await onAuthenticated();
    return result;
  });
}

module.exports = { registerAuthIpc, loadHome, onAuthenticated };
