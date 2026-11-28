// 로그인 게이트와 인증 IPC
// - 메인 창의 "홈"은 로그인 여부에 따라 둘 중 하나다.
//     로그인 전 : renderer/pages/login.html (LOGIN_PAGE_VERSION=2 면 loginV2.html — AM-Tray 전용 화면)
//     로그인 후 : renderer/index.html (마이크 테스트)
//   main.js 에서 index.html 을 직접 띄우던 곳은 모두 loadHome() 을 거친다.
// - 녹음 화면(recordingWindow.html)에 있을 때는 세션이 끊겨도 화면을 빼앗지 않는다.
//   녹음이 끊기면 안 되기 때문이다. 업로드가 실패하면 업로드 리스트에 남고,
//   홈으로 돌아오는 순간 로그인 화면이 뜬다(11-28: 만료 안내 팝업을 먼저 띄운다).
// - 11-28 토큰 갱신이 거절되면(529·530·531 등) 먼저 AM-Tray 로 조용히 다시 로그인한다(silentAmReauth).
//   그것도 안 되면 마이크 테스트 화면에서는 바로 화면을 바꾸지 않고 만료 팝업 [다시 로그인] 을 띄운다.

const path = require('path');
const { app, ipcMain, shell, dialog } = require('electron');
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
// 녹음 화면에 있는 동안 세션이 만료됐으면 true. 홈(로그인 화면)으로 돌아올 때 만료 팝업을 띄운다(11-28).
let pendingExpiredNotice = false;
let expiredDialogOpen = false;

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
  // 녹음 중에 세션이 만료됐었으면 로그인 화면이 뜬 뒤 안내(업로드 못 한 녹음은 다시 로그인 후 재전송)
  if (pendingExpiredNotice && page === LOGIN_PAGE) {
    pendingExpiredNotice = false;
    win.webContents.once('did-finish-load', () => { showExpiredDialog('after_recording').catch(() => {}); });
  }
  // AM-Tray 로그아웃을 미뤄 둔 상태로 마이크 테스트 화면에 돌아왔으면 확인 창
  if (pendingAmLogout && page === INDEX_PAGE) {
    win.webContents.once('did-finish-load', () => { if (pendingAmLogout && canAskAmLogoutNow()) askAmLogout(pendingAmLogout); });
  }
  try { logger.logInfo('load_home', { route: path.basename(page) }); } catch (_) {}
  return { success: true };
}

// 로그인 성공 직후 호출. 사용자 정보를 받아 둔 뒤, 로그인 화면에 있을 때만 메인 화면으로 넘긴다.
// (이미 로그인한 상태에서 로그인 알림이 또 와도 녹음 중인 화면을 건드리지 않기 위함)
// 사용자 정보 조회가 실패해도 로그인은 성공으로 본다. 타이틀에 이름이 안 나올 뿐이다.
// opts.termsCheckedByServer: 로그인 API 가 이미 약관을 확인했다(시스템 로그인 /auth/sso/amtray — 11-28) → HMP 로 다시 확인하지 않는다.
async function onAuthenticated(opts = {}) {
  pendingExpiredNotice = false;
  try { await userService.loadProfileAfterLogin(); } catch (_) {}
  // 약관 확인에 사번이 필요해서 내 정보 조회 뒤에 한다.
  if (opts.termsCheckedByServer) {
    try { logger.logInfo('terms_check_skipped', { reason: 'checked_by_login_api' }); } catch (_) {}
  } else if (!(await passTermsCheck())) return;
  // AI회의록 이용 권한(MyAccess 승인) — 약관 다음에 본다.
  if (!(await passAccessCheck())) return;
  // 업로드 팝업용 템플릿 목록을 미리 받아 둔다(기다리지 않음)
  templateService.refresh().catch(() => {});
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return;
  if (isLoginPageUrl(currentUrl(win))) loadHome();
}

// 약관 동의 확인(로그인·로그인 유지 복원 뒤). 동의했거나 판단할 수 없으면 true.
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
  await logoutForTerms();
  return false;
}

// 약관 미동의 → 로그아웃하고 로그인 화면에서 안내 팝업.
// 세션 만료와 같이 마이크 테스트·로그인 화면에 있을 때만 화면을 바꾼다(녹음 화면은 빼앗지 않는다).
async function logoutForTerms() {
  try { logger.logUserAction('logout', { reason: 'terms_not_agreed' }); } catch (_) {}
  pendingTermsNotice = true;
  await authService.logoutOnServer('terms_not_agreed');
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
  await logoutForAccess();
  return false;
}

// 권한 없음 → 로그아웃하고 로그인 화면에서 안내 팝업(확인 → 앱 종료). 화면 바꾸는 조건은 약관과 같다.
async function logoutForAccess() {
  try { logger.logUserAction('logout', { reason: 'access_denied' }); } catch (_) {}
  pendingAccessNotice = true;
  await authService.logoutOnServer('access_denied');
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
//      결과는 로그인 화면에 'auth-exchanged' 로 보낸다.
//   3) 응답코드별 팝업(11-16 매뉴얼 표 + 결정) — showAmResultDialog
//        설치 안내(509090·공백·Init 실패) [설치 페이지로 이동 → 브라우저 + 앱 종료][닫기]
//        시스템 접근 불가(503031~034·036) 응답 메시지 [확인] — 앱은 열어 둠(11-18)
//        SSO 로그인 페이지 실패(502050·502051)·SSO 로그인 불가(502052·공백) [다시 시도][앱 종료] (11-18)
//        DLL 로드·통신 실패(500001·500003) → 설치 안내(11-18)
//        ShowSSOLoginUI 가 506021(이미 로그인) → 토큰을 **한 번만** 다시 요청(계속 반복하지 않는다)
//   4) 로그인 뒤 AM-Tray 상태 확인(시스템 로그인으로 들어온 경우만) — checkAmSession
//        창이 활성화될 때(30초에 한 번까지) + 녹음 화면으로 넘어가기 전 → IsLoginIT 504011 이면 로그아웃 확인 창
//        녹음 화면으로 넘어가기 전에는 CheckLoginUserIT 로 같은 사람인지도(다른 사람·미로그인이면 확인 창) — 11-18
//   5) ★ 11-18: AM 안내가 Window Message → **API(DLL 함수) 호출 방식**으로 바뀜. 알림 수신 코드는 남겨 두지만 기대하지 않는다.
//        AM 로그인 창을 띄운 뒤에는 [다시 확인] + 앱 창으로 돌아올 때 토큰 한 번 다시 요청(retryAmLoginOnReturn). 주기 확인은 안 함.
// ★ AM-Tray 가 어느 창으로 메시지를 보내는지(창 제목·클래스·등록 함수)는 확인 중. 지금은 메인 창에서 받는다.
//   알림이 안 와도 [다시 확인]·창 활성화 확인(IsLoginIT)으로 버틴다.
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
// 미뤄 둔 로그아웃 확인 — false 또는 종류: 'logout'(AM-Tray 로그아웃) | 'other_user'(다른 사람이 AM-Tray 로그인) | 'forced'(AM-Tray 사용자 정보 없음)
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
    if (canAskAmLogoutNow()) askAmLogout(pendingAmLogout);
  }, PENDING_LOGOUT_CHECK_MS);
}

// AM-Tray 로그아웃(알림 / IsLoginIT 504011) 또는 다른 사용자·사용자 정보 없음(CheckLoginUserIT).
//   지금 물어볼 수 있으면 확인 창, 녹음·업로드 중이면 미룬다. 반환: 확인 창에서 로그아웃했으면 true.
async function onAmLogoutMessage(kind = 'logout', source = 'window_message') {
  const authenticated = authService.isAuthenticated();
  const win = getMainWindow();
  const url = win && !win.isDestroyed() ? currentUrl(win) : '';
  try { logger.logWarn('amtray_logout_message', { kind, source, authenticated, page: path.basename(url), uploads: getActiveUploadCount() }); } catch (_) {}
  if (!authenticated) return false;
  if (canAskAmLogoutNow()) return askAmLogout(kind);
  // 녹음 중(recordingWindow)·업로드 중 등 → 끊지 않고 미룬다
  pendingAmLogout = kind;
  try { logger.logInfo('amtray_logout_deferred', { kind, page: path.basename(url), uploads: getActiveUploadCount() }); } catch (_) {}
  startPendingLogoutWatch();
  return false;
}

// 종류별 확인 창 문구. forced 는 [확인] 하나(로그아웃만).
function amLogoutDialogOptions(kind) {
  if (kind === 'other_user') {
    return { type: 'warning', buttons: [i18n.t('amtray.logout_btn'), i18n.t('common.cancel')], defaultId: 0, cancelId: 1,
      title: i18n.t('amtray.other_user_title'), message: i18n.t('amtray.other_user_message'), detail: i18n.t('amtray.other_user_detail') };
  }
  if (kind === 'forced') {
    return { type: 'warning', buttons: [i18n.t('common.ok')], defaultId: 0, cancelId: 0,
      title: i18n.t('amtray.logout_title'), message: i18n.t('amtray.forced_message'), detail: i18n.t('amtray.forced_detail') };
  }
  return { type: 'question', buttons: [i18n.t('amtray.logout_btn'), i18n.t('common.cancel')], defaultId: 0, cancelId: 1,
    title: i18n.t('amtray.logout_title'), message: i18n.t('amtray.logout_message'), detail: i18n.t('amtray.logout_detail') };
}

// [취소]를 누른 뒤에는 창 활성화 확인(IsLoginIT)으로 같은 창을 또 띄우지 않는다 — AM-Tray 가 다시 로그인 상태가 되면 풀린다.
let amLogoutDeclined = false;

async function askAmLogout(kind = 'logout') {
  if (amLogoutDialogOpen) return false;
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return false;
  if (typeof kind !== 'string') kind = 'logout';
  amLogoutDialogOpen = true;
  pendingAmLogout = false;
  stopPendingLogoutWatch();
  let choice = 1;
  try {
    const res = await dialog.showMessageBox(win, { noLink: true, ...amLogoutDialogOptions(kind) });
    choice = res.response;
  } catch (err) {
    try { logger.logError('amtray_logout_dialog_failed', { message: String((err && err.message) || err) }); } catch (_) {}
  } finally {
    amLogoutDialogOpen = false;
  }
  if (choice !== 0) {
    amLogoutDeclined = true;
    try { logger.logUserAction('amtray_logout_cancelled', { kind }); } catch (_) {}
    return false;
  }
  if (!authService.isAuthenticated()) return false;
  // 창을 띄운 사이 녹음·업로드가 시작됐으면 다시 미룬다
  if (!canAskAmLogoutNow()) {
    pendingAmLogout = kind;
    startPendingLogoutWatch();
    try { logger.logInfo('amtray_logout_deferred', { kind, reason: 'busy_after_confirm' }); } catch (_) {}
    return false;
  }
  try { logger.logUserAction('logout', { reason: kind === 'logout' ? 'amtray_logout' : 'amtray_' + kind }); } catch (_) {}
  amLogoutDeclined = false;
  // 사용자가 [로그아웃]을 골랐다 = 사용자 로그아웃 → 서버 로그아웃도 부른다(11-28)
  await authService.logoutOnServer(kind === 'logout' ? 'amtray_logout' : 'amtray_' + kind);
  authService.clearSession();
  try { onLoggedOut(); } catch (_) {}
  loadHome();
  return true;
}

// ---- 로그인 뒤 AM-Tray 상태 확인 (11-16 결정: 창 활성화 + 녹음 시작 전, 1분마다 같은 주기 확인은 안 함) ----
const AM_FOCUS_CHECK_MIN_MS = 30 * 1000;
let lastAmFocusCheck = 0;
let amSessionChecking = false;

// 시스템 로그인(AM-Tray)으로 들어온 세션인가 — 테스트 로그인 세션은 AM-Tray 상태와 상관없다
function isAmSession() {
  return authService.isAuthenticated() && authService.getProfile().loginMethod === 'system' && amTrayService.isConfigured();
}

// IsLoginIT 로 AM-Tray 로그인 상태를 본다. 미로그인이면 로그아웃 확인(미루기 규칙은 알림과 같다).
// 반환: { checked, state, loggedOut }
async function checkAmSession(reason) {
  if (!isAmSession() || amSessionChecking) return { checked: false };
  amSessionChecking = true;
  try {
    const r = await amTrayService.isLogin();
    try { logger.logInfo('amtray_session_check', { reason, state: r.state, code: r.code, declined: amLogoutDeclined }); } catch (_) {}
    if (r.state === 'in') {
      amLogoutDeclined = false;
      // 녹음 시작 전에만 같은 사람인지도 본다(CheckLoginUserIT — 11-18: 사용자 변경은 드문 일이라 이때만)
      if (reason === 'before_recording') {
        const empno = authService.getProfile().empno;
        if (empno) {
          const u = await amTrayService.checkLoginUser(empno); // 로그 amtray_check_user 는 안에서 남긴다
          if (u.state === 'other') return { checked: true, state: 'other', loggedOut: await onAmLogoutMessage('other_user', 'check_user_' + reason) };
          if (u.state === 'out') return { checked: true, state: 'out', loggedOut: await onAmLogoutMessage('forced', 'check_user_' + reason) };
        }
      }
      return { checked: true, state: r.state };
    }
    if (r.state !== 'out' || amLogoutDeclined || pendingAmLogout) return { checked: true, state: r.state };
    const loggedOut = await onAmLogoutMessage('logout', 'is_login_' + reason);
    return { checked: true, state: r.state, loggedOut };
  } finally {
    amSessionChecking = false;
  }
}

function onMainWindowFocus() {
  // 로그인 전, AM 로그인 창을 띄우고 기다리는 중이면: 앱으로 돌아온 김에 토큰을 한 번 다시 받아 본다(11-18)
  if (amWaitTimer && !authService.isAuthenticated()) { retryAmLoginOnReturn().catch(() => {}); return; }
  const now = Date.now();
  if (now - lastAmFocusCheck < AM_FOCUS_CHECK_MIN_MS) return;
  if (!isAmSession()) return;
  lastAmFocusCheck = now;
  checkAmSession('focus').catch(() => {});
}

// AM 로그인 창을 띄운 뒤 사용자가 앱 창으로 돌아왔을 때 — 토큰 요청 한 번(로그인 창은 다시 띄우지 않는다).
//   아직 미로그인(504011 등)이면 조용히 계속 기다린다(안내 문구·[다시 확인] 그대로). 그 밖의 결과는 로그인 화면에 보낸다.
const AM_RETURN_RETRY_MIN_MS = 3 * 1000;
let lastAmReturnRetry = 0;
async function retryAmLoginOnReturn() {
  const now = Date.now();
  if (amLoginBusy || now - lastAmReturnRetry < AM_RETURN_RETRY_MIN_MS) return;
  lastAmReturnRetry = now;
  amLoginBusy = true;
  let result;
  try {
    result = await runAmLogin({ allowShowUi: false });
  } finally {
    amLoginBusy = false;
  }
  try { logger.logInfo('amtray_return_retry', { success: !!result.success, error: result.error, code: result.code }); } catch (_) {}
  if (!result.success && result.error === 'amtray_not_logged_in') return; // 아직 — 계속 기다림
  stopAmWaiting();
  logLoginResult('system', result, { code: result.code, after: 'return_to_app' });
  sendToLoginPage(await showAmResultDialog(result));
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
    // 로그인 중에 온 알림: 같은 사람인지 CheckLoginUserIT 로 본다(11-16). 판단 못 하면 예전처럼 hash 비교를 기록만.
    const empno = authService.getProfile().empno;
    const same = amTrayCopyData.sameUser(hash, empno);
    try { logger.logInfo('amtray_login_message_ignored', { source, reason: 'already_logged_in', sameUser: same, myHashHead: amTrayCopyData.myHashHead(empno) }); } catch (_) {}
    let state = same === true ? 'same' : 'unknown';
    if (isAmSession() && empno) state = (await amTrayService.checkLoginUser(empno)).state;
    if (state === 'same') {
      amLogoutDeclined = false;
      // 같은 사람이 AM-Tray 에 다시 로그인했으면, 미뤄 둔 로그아웃 확인은 필요 없다
      if (pendingAmLogout) {
        pendingAmLogout = false;
        stopPendingLogoutWatch();
        try { logger.logInfo('amtray_logout_pending_cleared', { reason: 'same_user_login' }); } catch (_) {}
      }
    } else if (state === 'other') {
      amLogoutDeclined = false;
      await onAmLogoutMessage('other_user', source);
    } else if (state === 'out') {
      await onAmLogoutMessage('forced', source);
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
  sendToLoginPage(await showAmResultDialog(result));
}

// 토큰 요청 한 번 → 결과. allowShowUi 면 미로그인(504011·503035)일 때 AM-Tray 로그인 창까지 띄운다.
async function runAmLogin({ allowShowUi }) {
  const tok = await amTrayService.getSystemToken();
  if (tok.kind === 'token') {
    // 비교용: SMSESSION 모양도 로그에(기다리지 않음, 쓰지 않음)
    amTrayService.logSmSessionShape().catch(() => {});
    if (authConfig.AMTRAY_TOKEN_MODE === 'direct') return loginWithAmTokenDirect(tok.token);
    const result = await authService.loginWithAmToken(tok.token);
    if (result.success) await onAuthenticated({ termsCheckedByServer: true });
    return result;
  }
  if (tok.kind === 'not_logged_in') {
    if (!allowShowUi) return { success: false, error: 'amtray_not_logged_in', code: tok.code };
    return runAmShowLoginUi();
  }
  if (tok.kind === 'install') return { success: false, error: 'amtray_install_required', code: tok.code };
  // 500001·500003(DLL 로드·통신 실패) — 11-18: 설치 페이지 안내로(구성도 "DLL 로딩 실패 → 설치 페이지")
  if (tok.kind === 'unavailable') return { success: false, error: 'amtray_install_required', code: tok.code };
  if (tok.kind === 'denied' || tok.kind === 'error') {
    const message = await amTrayService.getReturnMessage(tok.code, i18n.getLang());
    return { success: false, error: tok.kind === 'denied' ? 'amtray_denied' : 'amtray_error', code: tok.code, message };
  }
  return { success: false, error: 'amtray_helper_error', detail: tok.error };
}

// 인가토큰을 그대로 사용자 토큰으로(AMTRAY_TOKEN_MODE 'direct') → 내 정보(/api/auth/user/me)로 확인.
//   /me 가 안 되면(401 등) 세션을 지우고 실패로 돌려준다 — 로그인 화면이 다시 자동 시도하며 도는 일이 없게
//   onAuthenticated(화면 이동)는 /me 가 된 뒤에만 부른다.
async function loginWithAmTokenDirect(token) {
  const started = authService.startAmTokenSession(token);
  if (!started.success) return started;
  const me = await userService.callApi('userMe');
  try { logger.logInfo('amtray_direct_me', { success: me.success, status: me.status, httpCode: me.httpCode, error: me.error, pickedKeys: me.picked ? Object.keys(me.picked) : [] }); } catch (_) {}
  if (!me.success) {
    authService.clearSession();
    return { success: false, error: 'amtray_token_rejected', code: me.httpCode || me.status || me.error };
  }
  authService.mergeProfile({ ...me.picked, name: me.picked.name || me.picked.nickName }, { overwrite: false });
  await onAuthenticated();
  return { success: authService.isAuthenticated() };
}

// AM-Tray 로그인 창(ShowSSOLoginUI) → 결과.
//   506021(이미 로그인) → 토큰을 한 번만 다시 요청한다(이번엔 창을 다시 띄우지 않으므로 반복되지 않는다).
async function runAmShowLoginUi() {
  const ui = await amTrayService.showLoginUI();
  if (!ui.ok) return { success: false, error: 'amtray_helper_error', detail: ui.error };
  switch (ui.status) {
    case 'shown':
      startAmWaiting();
      return { success: false, pending: true, error: 'amtray_login_ui_shown' };
    case 'already': {
      try { logger.logInfo('amtray_already_logged_in_retry', { code: ui.code }); } catch (_) {}
      return runAmLogin({ allowShowUi: false });
    }
    case 'install':
      return { success: false, error: 'amtray_install_required', code: ui.code };
    case 'blocked':
      return { success: false, error: 'amtray_sso_blocked', code: ui.code };
    default: // retryable
      return { success: false, error: 'amtray_sso_page_failed', code: ui.code };
  }
}

// 응답코드별 팝업(메인 프로세스 대화상자 — 로그인 화면 ver1·ver2 모두 같다). 팝업이 끝난 뒤의 결과를 돌려준다.
//   [다시 시도] 는 AM-Tray 로그인 창을 다시 부른다(사용자가 누를 때만 — 저절로 반복하지 않는다).
async function showAmResultDialog(result) {
  const r = result || {};
  const win = getMainWindow();
  if (!win || win.isDestroyed() || r.success || r.pending) return r;
  const codeLine = r.code ? i18n.t('loginV2.code', { code: r.code }) : '';
  const show = (opts) => dialog.showMessageBox(win, { noLink: true, ...opts }).then((x) => x.response).catch(() => -1);
  switch (r.error) {
    case 'amtray_install_required': {
      const url = amTrayService.getInstallUrl();
      const buttons = url ? [i18n.t('amtray.install_btn'), i18n.t('common.close')] : [i18n.t('common.ok')];
      const choice = await show({ type: 'warning', buttons, defaultId: 0, cancelId: buttons.length - 1,
        title: i18n.t('amtray.install_title'), message: i18n.t('amtray.install_message'),
        detail: [url ? i18n.t('amtray.install_detail') : '', codeLine].filter(Boolean).join('\n') });
      if (url && choice === 0) {
        try { logger.logUserAction('amtray_install_page', { code: r.code }); } catch (_) {}
        try { await shell.openExternal(url); } catch (err) {
          try { logger.logError('amtray_install_page_open_failed', { message: String((err && err.message) || err) }); } catch (_) {}
        }
        app.quit();
      }
      return r;
    }
    case 'amtray_denied': {
      // 503031~503034·503036(접근 권한 없음 등) — 팝업만 띄우고 앱은 열어 둔다(11-18 결정). 로그인 화면에 같은 문구가 남는다.
      const text = r.message || i18n.t('amtray.code_' + r.code);
      await show({ type: 'warning', buttons: [i18n.t('common.ok')], defaultId: 0, cancelId: 0,
        title: i18n.t('amtray.denied_title'), message: text, detail: codeLine });
      try { logger.logUserAction('amtray_denied_popup', { code: r.code }); } catch (_) {}
      return r;
    }
    case 'amtray_sso_page_failed': {
      const choice = await show({ type: 'warning', buttons: [i18n.t('loginV2.retry_btn'), i18n.t('amtray.quit_btn')], defaultId: 0, cancelId: 1,
        title: i18n.t('amtray.sso_title'), message: i18n.t('amtray.sso_page_failed'), detail: codeLine });
      if (choice === 0) {
        try { logger.logUserAction('amtray_sso_page_retry', { code: r.code }); } catch (_) {}
        return showAmResultDialog(await runAmShowLoginUi());
      }
      try { logger.logUserAction('amtray_sso_page_quit', { code: r.code }); } catch (_) {}
      app.quit();
      return r;
    }
    case 'amtray_sso_blocked': {
      // 502052·공백(SSO 로그인 불가) — 11-18: 앱을 바로 끄지 않고 [다시 시도](로그인 창 다시 호출)를 준다(구성도의 "자체 로그인" 자리)
      const choice = await show({ type: 'error', buttons: [i18n.t('loginV2.retry_btn'), i18n.t('amtray.quit_btn')], defaultId: 0, cancelId: 1,
        title: i18n.t('amtray.sso_title'), message: i18n.t('amtray.sso_blocked'), detail: codeLine });
      if (choice === 0) {
        try { logger.logUserAction('amtray_sso_blocked_retry', { code: r.code }); } catch (_) {}
        return showAmResultDialog(await runAmShowLoginUi());
      }
      try { logger.logUserAction('amtray_sso_blocked_quit', { code: r.code }); } catch (_) {}
      app.quit();
      return r;
    }
    default:
      return r;
  }
}

// ---- 토큰 갱신이 거절됐을 때 AM-Tray 로 조용히 다시 로그인 (11-28, 인계문서 7-2: 529·530·531 → AM-Tray 인가토큰으로 재로그인) ----
//   화면·팝업은 띄우지 않는다(녹음 중일 수 있다). AM-Tray 에 같은 사람이 로그인돼 있을 때만 한다.
//   로그인 창(ShowSSOLoginUI)은 띄우지 않는다 — 미로그인이면 실패로 돌려주고 만료 처리로 넘어간다.
async function silentAmReauth() {
  if (!authConfig.SYSTEM_LOGIN_ENABLED || !amTrayService.isConfigured()) return { success: false, error: 'amtray_not_configured' };
  if (authConfig.AMTRAY_TOKEN_MODE !== 'backend') return { success: false, error: 'not_backend_mode' };
  if (amLoginBusy) return { success: false, error: 'amtray_busy' };
  amLoginBusy = true;
  try {
    const empno = authService.getProfile().empno;
    if (empno) {
      const u = await amTrayService.checkLoginUser(empno);
      if (u.state !== 'same') return { success: false, error: 'amtray_user_' + (u.state || 'unknown') };
    }
    const tok = await amTrayService.getSystemToken();
    if (tok.kind !== 'token') return { success: false, error: 'amtray_' + tok.kind, code: tok.code };
    return await authService.loginWithAmToken(tok.token);
  } finally {
    amLoginBusy = false;
  }
}

// 세션 만료 팝업. kind: 'now'(마이크 테스트 화면에서 바로) | 'after_recording'(녹음 중 만료 → 홈으로 돌아온 뒤)
//   'now' 는 [다시 로그인] → 로그인 화면(로그인 화면이 열리면 AM-Tray 자동 로그인을 다시 시도한다).
async function showExpiredDialog(kind) {
  const win = getMainWindow();
  if (!win || win.isDestroyed() || expiredDialogOpen) return;
  expiredDialogOpen = true;
  try {
    const detail = kind === 'after_recording' ? i18n.t('auth.expired_after_recording_detail') : i18n.t('auth.expired_detail');
    const buttons = kind === 'after_recording' ? [i18n.t('common.ok')] : [i18n.t('auth.relogin_btn')];
    await dialog.showMessageBox(win, { noLink: true, type: 'warning', buttons, defaultId: 0, cancelId: 0,
      title: i18n.t('auth.expired_title'), message: i18n.t('auth.expired_message'), detail });
    try { logger.logUserAction('session_expired_dialog', { kind }); } catch (_) {}
  } catch (err) {
    try { logger.logError('session_expired_dialog_failed', { message: String((err && err.message) || err) }); } catch (_) {}
  } finally {
    expiredDialogOpen = false;
  }
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

  // 갱신이 거절되면 AM-Tray 로 조용히 다시 로그인(authService.tryReauth 가 부른다)
  authService.setReauthHandler(silentAmReauth);

  // 갱신·재로그인까지 실패하면(11-28):
  //   마이크 테스트 화면 → 화면을 바로 바꾸지 않고 만료 팝업 [다시 로그인] → 로그인 화면
  //   녹음 화면 등 → 아무것도 안 한다(녹음은 계속). 업로드 실패분은 업로드 리스트에 남고, 홈으로 돌아올 때 팝업
  authService.onSessionExpired(async () => {
    try { logger.logUserAction('logout', { reason: 'session_expired' }); } catch (_) {}
    const win = getMainWindow();
    if (!win || win.isDestroyed()) return;
    if (currentUrl(win).endsWith('/renderer/index.html')) {
      await showExpiredDialog('now');
      if (!authService.isAuthenticated()) loadHome();
      return;
    }
    if (!isLoginPageUrl(currentUrl(win))) pendingExpiredNotice = true;
  });

  // profile 에는 토큰이 없다(이름·사번·이메일·워크스페이스만).
  // loginPrefs: 로그인 화면 체크박스("로그인 유지")의 마지막 값.
  // keepLoginEnabled 가 false(SESSION_PERSIST_ENABLED=false)면 "로그인 유지" 체크박스를 숨긴다.
  ipcMain.handle('auth:get-status', () => ({
    authenticated: authService.isAuthenticated(),
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

  // 로그인 화면 체크박스가 바뀔 때마다 저장한다. 로그인(AM-Tray 알림 자동 로그인 포함)보다 먼저
  // 값이 메인 프로세스에 있어야 한다(세션 저장 여부는 sessionStore 가 이 값을 본다).
  ipcMain.handle('auth:set-login-options', (_event, payload) => {
    const input = payload || {};
    loginPrefs.setOptions({ keepLogin: input.keepLogin === true });
    return { success: true };
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
    return showAmResultDialog(result);
  });

  // 로그인 화면 ver2 의 [AM-Tray 로그인] → AM-Tray 로그인 호출. 로그인이 끝나면 윈도우 메시지 → 자동 로그인.
  ipcMain.handle('auth:am-show-login-ui', async () => {
    if (!authConfig.SYSTEM_LOGIN_ENABLED) return { success: false, error: 'system_login_disabled' };
    if (!amTrayService.isConfigured()) return { success: false, error: 'system_login_not_ready' };
    try { logger.logUserAction('amtray_show_login_ui'); } catch (_) {}
    ensureAmWindowHook();
    if (amLoginBusy) return { success: false, pending: true, error: 'amtray_busy' };
    stopAmWaiting();
    amLoginBusy = true;
    let result;
    try {
      result = await runAmShowLoginUi();
    } finally {
      amLoginBusy = false;
    }
    if (!result.pending) logLoginResult('system', result, { code: result.code, after: 'login_ui' });
    return showAmResultDialog(result);
  });

  // 녹음 화면으로 넘어가기 전 AM-Tray 로그인 확인(시스템 로그인 세션만). { proceed:false } 면 넘어가지 않는다(로그아웃됨).
  ipcMain.handle('auth:am-check-before-recording', async () => {
    try {
      const r = await checkAmSession('before_recording');
      return { proceed: !r.loggedOut };
    } catch (_) {
      return { proceed: true };
    }
  });

  // 창이 활성화될 때 AM-Tray 로그인 확인(시스템 로그인 세션만, 30초에 한 번까지)
  app.on('browser-window-focus', (_e, w) => {
    const win = getMainWindow();
    if (win && w === win) onMainWindowFocus();
  });

  // 흉내(AMTRAY_MOCK=notlogin)에서는 윈도우 메시지 대신 3초 뒤 이걸로 알려 준다.
  amTrayService.setMockLoginListener(() => onAmLoginMessage('mock'));

  // 로그아웃(설정 메뉴). 녹음 중인지는 화면(recording.js)이 먼저 막는다.
  // 서버로 업로드 중이면 막는다 — 토큰이 사라지면 전송 중인 업로드가 실패한다.
  // 세션(토큰·사용자 정보)을 지운다(로그인 유지로 저장해 둔 파일도 같이). 녹음 파일·업로드 리스트는 그대로 둔다.
  ipcMain.handle('auth:logout', async () => {
    if (getActiveUploadCount() > 0) {
      try { logger.logUserAction('logout_blocked', { reason: 'uploading' }); } catch (_) {}
      return { success: false, error: 'uploading' };
    }
    try { logger.logUserAction('logout', { reason: 'user' }); } catch (_) {}
    pendingAmLogout = false;
    amLogoutDeclined = false;
    stopPendingLogoutWatch();
    // 서버 로그아웃(DELETE /api/auth/logout) — 시스템 로그인 세션만. 실패해도 앱 로그아웃은 한다(최대 5초)
    await authService.logoutOnServer('user');
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
module.exports = { registerAuthIpc, loadHome, onAuthenticated, _test: { onAmLoginMessage, onAmLogoutMessage, checkAmSession, showAmResultDialog } };
