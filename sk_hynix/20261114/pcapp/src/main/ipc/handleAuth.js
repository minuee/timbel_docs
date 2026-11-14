// 로그인 게이트와 인증 IPC
// - 메인 창의 "홈"은 로그인 여부에 따라 둘 중 하나다.
//     로그인 전 : renderer/pages/login.html (LOGIN_PAGE_VERSION=2 면 loginV2.html — AM-Tray 전용 화면)
//     로그인 후 : renderer/index.html (마이크 테스트)
//   main.js 에서 index.html 을 직접 띄우던 곳은 모두 loadHome() 을 거친다.
// - 녹음 화면(recordingWindow.html)에 있을 때는 세션이 끊겨도 화면을 빼앗지 않는다.
//   녹음이 끊기면 안 되기 때문이다. 업로드가 실패하면 업로드 리스트에 남고,
//   홈으로 돌아오는 순간 로그인 화면이 뜬다.

const path = require('path');
const { ipcMain, shell, dialog } = require('electron');
const logger = require('../logger');
const authService = require('../services/authService');
const authConfig = require('../services/authConfig');
const userService = require('../services/userService');
const templateService = require('../services/templateService');
const sessionStore = require('../services/sessionStore');
const loginPrefs = require('../services/loginPrefs');
const amTrayService = require('../services/amTrayService');
const amTrayCopyData = require('../services/amTrayCopyData');
const i18n = require('../i18n');

const INDEX_PAGE = path.join(__dirname, '../../renderer/index.html');
const LOGIN_PAGE_V1 = path.join(__dirname, '../../renderer/pages/login.html');
const LOGIN_PAGE_V2 = path.join(__dirname, '../../renderer/pages/loginV2.html');
const LOGIN_PAGE = authConfig.LOGIN_PAGE_VERSION === 2 ? LOGIN_PAGE_V2 : LOGIN_PAGE_V1;

// 지금 화면이 로그인 화면(ver1·ver2 어느 쪽이든)인지
function isLoginPageUrl(url) {
  return /\/pages\/login(V2)?\.html$/.test(String(url || ''));
}

let getMainWindow = () => null;
let onLoggedOut = () => {};
let getActiveUploadCount = () => 0;
// 약관 미동의로 로그아웃시켰으면 true. 다음에 뜨는 로그인 화면이 가져가서 안내 팝업을 띄운다(auth:take-terms-notice).
let pendingTermsNotice = false;
// AI회의록 이용 권한이 없어 로그아웃시켰으면 true. 로그인 화면이 가져가서 권한 안내 팝업([확인] → 앱 종료)을 띄운다.
let pendingAccessNotice = false;

function currentUrl(win) {
  try { return win.webContents.getURL() || ''; } catch (_) { return ''; }
}

function loadHome() {
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return { success: false, error: 'mainWindow_unavailable' };
  const page = authService.isAuthenticated() ? INDEX_PAGE : LOGIN_PAGE;
  // AM-Tray 로그인 알림은 화면과 관계없이 언제든 받는다(로그인 전이면 자동 로그인)
  ensureAmWindowHook();
  win.loadFile(page);
  // AM-Tray 로그아웃을 미뤄 둔 상태로 마이크 테스트 화면에 돌아왔으면 확인 창
  if (pendingAmLogout && page === INDEX_PAGE) {
    win.webContents.once('did-finish-load', () => { if (pendingAmLogout && canAskAmLogoutNow()) askAmLogout(); });
  }
  try { logger.logInfo('load_home', { route: path.basename(page) }); } catch (_) {}
  return { success: true };
}

// 로그인 성공 직후 호출. 사용자 정보를 받아 둔 뒤, 로그인 화면에 있을 때만 메인 화면으로 넘긴다.
// (이미 로그인한 상태에서 딥링크가 또 와도 녹음 중인 화면을 건드리지 않기 위함)
// 사용자 정보 조회가 실패해도 로그인은 성공으로 본다. 타이틀에 이름이 안 나올 뿐이다.
// termsChecked: 사번 로그인처럼 로그인 응답으로 약관 동의를 이미 확인했으면 true(다시 부르지 않는다).
async function onAuthenticated({ termsChecked = false } = {}) {
  try { await userService.loadProfileAfterLogin(); } catch (_) {}
  // 약관 확인에 사번이 필요해서 내 정보 조회 뒤에 한다.
  if (!termsChecked && !(await passTermsCheck())) return;
  // AI회의록 이용 권한(MyAccess 승인) — 약관 다음에 본다. 사번 로그인도 여기서 확인한다.
  if (!(await passAccessCheck())) return;
  // 업로드 팝업용 템플릿 목록을 미리 받아 둔다(기다리지 않음)
  templateService.refresh().catch(() => {});
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  if (isLoginPageUrl(currentUrl(win))) loadHome();
}

// 약관 동의 확인(MyAccess·로그인 유지 복원). 동의했거나 판단할 수 없으면 true.
// 확인을 못 하면(사번 없음·네트워크 오류·그 밖의 응답) 막지 않는다 — 서버 문제로 동의한 사람까지 못 쓰면 안 된다.
async function passTermsCheck() {
  if (!authConfig.TERMS_CHECK_ENABLED) return true;
  const empno = authService.getProfile().empno;
  try { logger.logInfo('terms_check_begin', { hasEmpno: !!empno }); } catch (_) {}
  const result = await authService.checkTermsAgreed(empno);
  if (result.agreed === true) {
    try { logger.logInfo('terms_check_passed'); } catch (_) {}
    return true;
  }
  if (result.agreed !== false) {
    try { logger.logWarn('terms_check_error', { error: result.error, status: result.status, httpCode: result.httpCode, message: result.message }); } catch (_) {}
    return true;
  }
  try { logger.logWarn('terms_not_agreed', { method: 'after_login', httpCode: result.httpCode, message: result.message }); } catch (_) {}
  logoutForTerms();
  return false;
}

// 약관 미동의 → 로그아웃하고 로그인 화면에서 안내 팝업.
// 세션 만료와 같이 마이크 테스트·로그인 화면에 있을 때만 화면을 바꾼다(녹음 화면은 빼앗지 않는다).
function logoutForTerms() {
  try { logger.logUserAction('logout', { reason: 'terms_not_agreed' }); } catch (_) {}
  pendingTermsNotice = true;
  authService.clearSession();
  try { onLoggedOut(); } catch (_) {}
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  const url = currentUrl(win);
  if (isLoginPageUrl(url) || url.endsWith('/renderer/index.html')) loadHome();
}

// AI회의록 이용 권한 확인. 권한이 있거나 판단할 수 없으면 true(서버 문제로 권한 있는 사람까지 막으면 안 된다).
async function passAccessCheck() {
  if (!authConfig.ACCESS_CHECK_ENABLED) return true;
  const result = await authService.checkMinutesAccess();
  if (result.allowed === true) {
    try { logger.logInfo('access_check_passed', { mock: !!result.mock }); } catch (_) {}
    return true;
  }
  if (result.allowed !== false) {
    // not_configured: 확인 API 가 아직 없음(ACCESS_CHECK_PATH 비어 있음)
    try { logger.logWarn('access_check_skipped', { error: result.error, status: result.status, httpCode: result.httpCode, message: result.message }); } catch (_) {}
    return true;
  }
  try { logger.logWarn('access_denied', { httpCode: result.httpCode, message: result.message, mock: !!result.mock }); } catch (_) {}
  logoutForAccess();
  return false;
}

// 권한 없음 → 로그아웃하고 로그인 화면에서 안내 팝업(확인 → 앱 종료). 화면 바꾸는 조건은 약관과 같다.
function logoutForAccess() {
  try { logger.logUserAction('logout', { reason: 'access_denied' }); } catch (_) {}
  pendingAccessNotice = true;
  authService.clearSession();
  try { onLoggedOut(); } catch (_) {}
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  const url = currentUrl(win);
  if (isLoginPageUrl(url) || url.endsWith('/renderer/index.html')) loadHome();
}

// ============================================
// 시스템 로그인 (AM-Tray)
//   1) AM DLL Init → GetSystemToken → 인가토큰(203030)이면 백엔드에 보내 우리 토큰으로(loginWithAmToken) → onAuthenticated
//   2) 미로그인(504011) → AM-Tray 로그인 호출(ShowSSOLoginUI — 로그인 방식은 AM-Tray 몫) → 사용자가 로그인하면
//      AM-Tray 가 앱 창으로 WM_COPYDATA(wParam = AMTRAY_ENV_CODE)를 보낸다 → 1) 을 한 번 더(이번엔 창을 다시 띄우지 않음)
//      ※ 2026-11-14: 알림은 버튼을 누르고 기다릴 때만이 아니라 **언제든** 받는다. 앱이 로그인 전이면 자동 로그인,
//        이미 로그인 중이면 기록만(다른 사용자인지 hash 비교는 형식 확인 뒤).
//      결과는 로그인 화면에 'auth-exchanged' 로 보낸다(MyAccess 딥링크 결과와 같은 통로).
//   3) AM-Tray 사용 불가 / 그 밖의 코드 → 안내(사번·MyAccess 로 로그인)
// ★ AM-Tray 가 어느 창으로 메시지를 보내는지(창 제목·클래스·등록 함수)는 확인 중. 지금은 메인 창에서 받는다.
// ============================================
const WM_COPYDATA = 0x004a;
const WM_USER = 0x0400;
const hookedWindows = new WeakSet();
let amWaitTimer = null;

function sendToLoginPage(payload) {
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  if (!isLoginPageUrl(currentUrl(win))) return;
  try { win.webContents.send('auth-exchanged', payload); } catch (_) {}
}

function readWParam(buf) {
  try {
    if (!Buffer.isBuffer(buf)) return Number(buf);
    return buf.length >= 8 ? Number(buf.readBigUInt64LE(0)) : buf.readUInt32LE(0);
  } catch (_) {
    return NaN;
  }
}

// 메인 창에서 AM-Tray 윈도우 메시지를 받는다(Windows 전용). 창마다 한 번만 건다.
function ensureAmWindowHook() {
  if (process.platform !== 'win32' || !authConfig.SYSTEM_LOGIN_ENABLED) return;
  const win = getMainWindow();
  if (!win || win.isDestroyed() || typeof win.hookWindowMessage !== 'function' || hookedWindows.has(win)) return;
  hookedWindows.add(win);
  const env = authConfig.AMTRAY_ENV_CODE;
  win.hookWindowMessage(WM_COPYDATA, (wParam, lParam) => {
    const value = readWParam(wParam);
    if (value !== env) {
      try { logger.logInfo('amtray_copydata_ignored', { wParam: value, expected: env }); } catch (_) {}
      return;
    }
    // 사용자 hash — 샘플과 같이 lpData 를 cbData 길이만큼 문자열로 읽는다. lParam 은 이 안에서만 유효해서 바로 읽는다.
    let hash = null;
    try {
      const data = amTrayCopyData.readCopyData(lParam);
      hash = data ? data.text : null;
      logger.logInfo('amtray_login_hash', { cbData: data && data.cbData, ...amTrayCopyData.describeHash(hash) });
    } catch (err) {
      try { logger.logWarn('amtray_login_hash_read_failed', { message: String((err && err.message) || err) }); } catch (_) {}
    }
    onAmLoginMessage('window_message', hash);
  });
  win.hookWindowMessage(WM_USER + env, () => onAmLogoutMessage());
  try { logger.logInfo('amtray_window_hook_installed', { env }); } catch (_) {}
}

// ---- AM-Tray 로그아웃 알림 (결정 D, 11-14) ----
//   녹음 중·업로드 중·마이크 테스트 화면이 아닐 때 → 로그아웃하지 않고 미뤄 둔다(pendingAmLogout).
//     마이크 테스트 화면으로 돌아오고 업로드가 없을 때 확인 창을 띄운다(5초마다 확인).
//   마이크 테스트 화면 + 업로드 없음 → 확인 창 [로그아웃] / [취소]. 취소면 로그인 유지.
const PENDING_LOGOUT_CHECK_MS = 5000;
let pendingAmLogout = false;
let pendingLogoutTimer = null;
let amLogoutDialogOpen = false;

function canAskAmLogoutNow() {
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return false;
  return currentUrl(win).endsWith('/renderer/index.html') && getActiveUploadCount() === 0;
}

function stopPendingLogoutWatch() {
  if (pendingLogoutTimer) clearInterval(pendingLogoutTimer);
  pendingLogoutTimer = null;
}

function startPendingLogoutWatch() {
  if (pendingLogoutTimer) return;
  pendingLogoutTimer = setInterval(() => {
    if (!pendingAmLogout || !authService.isAuthenticated()) { pendingAmLogout = false; stopPendingLogoutWatch(); return; }
    if (canAskAmLogoutNow()) askAmLogout();
  }, PENDING_LOGOUT_CHECK_MS);
}

function onAmLogoutMessage() {
  const authenticated = authService.isAuthenticated();
  const win = getMainWindow();
  const url = win && !win.isDestroyed() ? currentUrl(win) : '';
  try { logger.logWarn('amtray_logout_message', { authenticated, page: path.basename(url), uploads: getActiveUploadCount() }); } catch (_) {}
  if (!authenticated) return;
  if (canAskAmLogoutNow()) { askAmLogout(); return; }
  // 녹음 중(recordingWindow)·업로드 중 등 → 끊지 않고 미룬다
  pendingAmLogout = true;
  try { logger.logInfo('amtray_logout_deferred', { page: path.basename(url), uploads: getActiveUploadCount() }); } catch (_) {}
  startPendingLogoutWatch();
}

async function askAmLogout() {
  if (amLogoutDialogOpen) return;
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  amLogoutDialogOpen = true;
  pendingAmLogout = false;
  stopPendingLogoutWatch();
  let choice = 1;
  try {
    const res = await dialog.showMessageBox(win, {
      type: 'question',
      buttons: [i18n.t('amtray.logout_btn'), i18n.t('common.cancel')],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
      title: i18n.t('amtray.logout_title'),
      message: i18n.t('amtray.logout_message'),
      detail: i18n.t('amtray.logout_detail'),
    });
    choice = res.response;
  } catch (err) {
    try { logger.logError('amtray_logout_dialog_failed', { message: String((err && err.message) || err) }); } catch (_) {}
  } finally {
    amLogoutDialogOpen = false;
  }
  if (choice !== 0) {
    try { logger.logUserAction('amtray_logout_cancelled'); } catch (_) {}
    return;
  }
  if (!authService.isAuthenticated()) return;
  // 창을 띄운 사이 녹음·업로드가 시작됐으면 다시 미룬다
  if (!canAskAmLogoutNow()) {
    pendingAmLogout = true;
    startPendingLogoutWatch();
    try { logger.logInfo('amtray_logout_deferred', { reason: 'busy_after_confirm' }); } catch (_) {}
    return;
  }
  try { logger.logUserAction('logout', { reason: 'amtray_logout' }); } catch (_) {}
  authService.clearSession();
  try { onLoggedOut(); } catch (_) {}
  loadHome();
}

function stopAmWaiting() {
  if (amWaitTimer) clearTimeout(amWaitTimer);
  amWaitTimer = null;
}

function startAmWaiting() {
  stopAmWaiting();
  amWaitTimer = setTimeout(() => {
    amWaitTimer = null;
    try { logger.logWarn('amtray_login_wait_timeout', { waitMs: authConfig.AMTRAY_LOGIN_WAIT_MS }); } catch (_) {}
    sendToLoginPage({ success: false, error: 'amtray_login_timeout' });
  }, authConfig.AMTRAY_LOGIN_WAIT_MS);
}

// AM-Tray 로그인 알림(윈도우 메시지 / 흉내). 앱이 로그인 전이면 언제든 토큰을 받아 자동 로그인한다.
// hash: 알림에 들어 있는 사용자 ID 의 SHA-256 문자열(흉내·읽기 실패면 null)
let amLoginBusy = false;
async function onAmLoginMessage(source, hash = null) {
  if (authService.isAuthenticated()) {
    // 로그인 중에 온 알림: 같은 사람인지만 기록한다. 다른 사람일 때 어떻게 할지는 결정 C(나중) — 지금은 기록만.
    const empno = authService.getProfile().empno;
    const same = amTrayCopyData.sameUser(hash, empno);
    try { logger.logInfo('amtray_login_message_ignored', { source, reason: 'already_logged_in', sameUser: same, myHashHead: amTrayCopyData.myHashHead(empno) }); } catch (_) {}
    // 같은 사람이 AM-Tray 에 다시 로그인했으면, 미뤄 둔 로그아웃 확인은 필요 없다
    if (same === true && pendingAmLogout) {
      pendingAmLogout = false;
      stopPendingLogoutWatch();
      try { logger.logInfo('amtray_logout_pending_cleared', { reason: 'same_user_login' }); } catch (_) {}
    }
    return;
  }
  if (!amTrayService.isConfigured()) {
    try { logger.logInfo('amtray_login_message_ignored', { source, reason: 'not_configured' }); } catch (_) {}
    return;
  }
  if (amLoginBusy) {
    try { logger.logInfo('amtray_login_message_ignored', { source, reason: 'busy' }); } catch (_) {}
    return;
  }
  const waiting = !!amWaitTimer;
  stopAmWaiting();
  try { logger.logInfo('amtray_login_message', { source, waiting }); } catch (_) {}
  sendToLoginPage({ success: false, pending: true, error: 'amtray_login_message_received' });
  amLoginBusy = true;
  let result;
  try {
    result = await runAmLogin({ allowShowUi: false });
  } finally {
    amLoginBusy = false;
  }
  logLoginResult('system', result, { code: result.code, after: waiting ? 'login_ui' : 'message' });
  // 로그인됐으면: 알림의 hash 가 로그인한 사번의 SHA-256 과 같은지 기록 (hash 대상이 사번인지 확인용)
  if (result.success && hash !== null) {
    const empno = authService.getProfile().empno;
    try { logger.logInfo('amtray_login_hash_check', { sameUser: amTrayCopyData.sameUser(hash, empno), hashHead: String(hash).slice(0, 8), myHashHead: amTrayCopyData.myHashHead(empno) }); } catch (_) {}
  }
  sendToLoginPage(result);
}

async function runAmLogin({ allowShowUi }) {
  const tok = await amTrayService.getSystemToken();
  if (tok.kind === 'token') {
    const result = await authService.loginWithAmToken(tok.token);
    if (result.success) await onAuthenticated();
    return result;
  }
  if (tok.kind === 'not_logged_in') {
    if (!allowShowUi) return { success: false, error: 'amtray_not_logged_in', code: tok.code };
    const ui = await amTrayService.showLoginUI();
    if (ui.ok && ui.shown) {
      startAmWaiting();
      return { success: false, pending: true, error: 'amtray_login_ui_shown' };
    }
    return { success: false, error: 'amtray_sso_server_down', detail: ui.error };
  }
  if (tok.kind === 'unavailable') return { success: false, error: 'amtray_unavailable', code: tok.code };
  if (tok.kind === 'error') {
    const message = await amTrayService.getReturnMessage(tok.code, i18n.getLang());
    return { success: false, error: 'amtray_error', code: tok.code, message };
  }
  return { success: false, error: 'amtray_helper_error', detail: tok.error };
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
  getActiveUploadCount = options.getActiveUploadCount || (() => 0);
  onLoggedOut = options.onLoggedOut || (() => {});

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
    systemLoginEnabled: authConfig.SYSTEM_LOGIN_ENABLED,
    manualLoginEnabled: authConfig.MANUAL_LOGIN_ENABLED,
    // 로그인 화면 ver2(AM-Tray 전용)에서는 테스트 로그인을 개발 빌드(APP_ENV=dev)에서만 보인다
    appEnv: authConfig.APP_ENV,
    amConfigured: amTrayService.isConfigured(),
    keepLoginEnabled: sessionStore.isEnabled(),
    loginPrefs: loginPrefs.get(),
    defaultEndpoint: authConfig.DEFAULT_API_BASE_URL,
    termsAgreeUrl: authConfig.TERMS_AGREE_URL,
    profile: authService.getProfile(),
  }));

  // 약관 미동의 안내를 띄워야 하는지. 로그인 화면이 뜰 때 한 번 가져가면 지운다.
  ipcMain.handle('auth:take-terms-notice', () => {
    // access: AI회의록 권한 없음 안내(약관 안내보다 먼저 보여준다 — 확인을 누르면 앱이 끝나므로)
    const show = pendingTermsNotice;
    const access = pendingAccessNotice;
    pendingTermsNotice = false;
    pendingAccessNotice = false;
    return { show, access };
  });

  // 약관 안내 팝업의 링크 → 기본 브라우저. 렌더러가 주소를 넘기지 않고 설정값(TERMS_AGREE_URL)만 연다.
  ipcMain.handle('auth:open-terms-page', async () => {
    try {
      const url = new URL(authConfig.TERMS_AGREE_URL);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new Error('invalid_protocol');
      await shell.openExternal(url.toString());
      try { logger.logUserAction('terms_page_opened', { host: url.host }); } catch (_) {}
      return { success: true };
    } catch (err) {
      try { logger.logError('terms_page_open_failed', { message: err && err.message }); } catch (_) {}
      return { success: false, error: err && err.message };
    }
  });

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

  // "시스템 로그인" → AM-Tray 인가토큰으로 로그인(runAmLogin 위 설명).
  //   AMTRAY_SYSTEM_ID 가 비어 있으면(흉내도 아니면) 지금처럼 '준비 중'.
  //   payload.showUi === false (로그인 화면 ver2 가 열릴 때): 토큰만 시도하고, 미로그인이면 AM 로그인 창은 띄우지 않는다
  //   → 화면이 [AM-Tray 로그인] 버튼(auth:am-show-login-ui)을 보여 준다.
  ipcMain.handle('auth:system-login', async (_event, payload) => {
    if (!authConfig.SYSTEM_LOGIN_ENABLED) return { success: false, error: 'system_login_disabled' };
    const allowShowUi = !(payload && payload.showUi === false);
    try { logger.logUserAction('login_attempt', { method: 'system', auto: !allowShowUi || undefined, mock: authConfig.AMTRAY_MOCK || undefined }); } catch (_) {}
    if (!amTrayService.isConfigured()) {
      const result = { success: false, error: 'system_login_not_ready' };
      logLoginResult('system', result);
      return result;
    }
    if (amLoginBusy) return { success: false, pending: true, error: 'amtray_busy' };
    ensureAmWindowHook();
    stopAmWaiting();
    amLoginBusy = true;
    let result;
    try {
      result = await runAmLogin({ allowShowUi });
    } finally {
      amLoginBusy = false;
    }
    if (!result.pending) logLoginResult('system', result, { code: result.code });
    return result;
  });

  // 로그인 화면 ver2 의 [AM-Tray 로그인] → AM-Tray 로그인 호출. 로그인이 끝나면 윈도우 메시지 → 자동 로그인.
  ipcMain.handle('auth:am-show-login-ui', async () => {
    if (!authConfig.SYSTEM_LOGIN_ENABLED) return { success: false, error: 'system_login_disabled' };
    if (!amTrayService.isConfigured()) return { success: false, error: 'system_login_not_ready' };
    try { logger.logUserAction('amtray_show_login_ui'); } catch (_) {}
    ensureAmWindowHook();
    const ui = await amTrayService.showLoginUI();
    if (ui.ok && ui.shown) {
      startAmWaiting();
      return { success: false, pending: true, error: 'amtray_login_ui_shown' };
    }
    return { success: false, error: 'amtray_sso_server_down', detail: ui.error };
  });

  // 흉내(AMTRAY_MOCK=notlogin)에서는 윈도우 메시지 대신 3초 뒤 이걸로 알려 준다.
  amTrayService.setMockLoginListener(() => onAmLoginMessage('mock'));

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
      // 약관 동의는 로그인 응답(HMP)으로 이미 확인했다. 미동의면 result.error 'terms_not_agreed' 로 로그인 화면이 팝업을 띄운다.
      await onAuthenticated({ termsChecked: true });
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
    pendingAmLogout = false;
    stopPendingLogoutWatch();
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
    // 테스트 로그인도 약관을 확인한다(SSO 와 같이 HMP 를 한 번 더 부른다). 사번은 입력한 값,
    // 비워 두면 내 정보(user/me)의 사번. 둘 다 없으면 확인하지 못하고 통과.
    if (result.success) await onAuthenticated();
    return result;
  });
}

// _test: 집(Mac)에서 윈도우 메시지 없이 알림 처리를 시험할 때만 쓴다(scratch e2e). 앱 코드는 쓰지 않는다.
module.exports = { registerAuthIpc, loadHome, onAuthenticated, _test: { onAmLoginMessage, onAmLogoutMessage } };
