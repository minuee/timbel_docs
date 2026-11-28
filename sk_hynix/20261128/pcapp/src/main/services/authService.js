// 인증 세션 보관 및 토큰 발급/갱신 담당
// - accessToken 은 이 모듈 밖으로 노출하지 않는다(렌더러에도 전달하지 않는다).
//   외부에서는 apiService 를 통해 요청만 보내고, 헤더 부착은 apiService 가 처리한다.
// - 세션은 기본적으로 메모리에만 둔다. 앱을 끄면 사라지고, 다시 켜면 로그인부터 한다.
//   (디스크에 남기지 않으므로 PC를 같이 쓰는 사람이 토큰을 꺼내 갈 수 없다)
//   SESSION_PERSIST_ENABLED 가 true 이고 사용자가 "로그인 유지"를 체크했으면 암호화해서 저장해 두고
//   다음 실행 때 복원한다(sessionStore.js, loginPrefs.js).
// - 로그인 경로
//   1) 시스템 로그인(AM-Tray 인가토큰)                                 : startAmTokenSession() / loginWithAmToken()
//   2) (테스트용) 이름·사번·accessToken 직접 입력                      : startManualSession()
//   (예전 MyAccess 딥링크 code 교환·사번 로그인은 SSO 이전 방식이라 11-17 지웠다)

const { EventEmitter } = require('events');
const logger = require('../logger');
const authConfig = require('./authConfig');
const sessionStore = require('./sessionStore');

let accessToken = null;
let refreshToken = null;
let endpoint = '';
// accessToken 만료 시각(ms). JWT 가 아니라서 알 수 없으면 null → 401 을 받은 뒤에만 갱신한다.
let accessTokenExpiresAt = null;
// 갱신 요청이 동시에 여러 번 나가지 않도록 진행 중인 Promise 를 공유한다.
let refreshInFlight = null;
// 로그인한 사용자 정보(이름, 사번, 이메일, 워크스페이스 등). 토큰과 달리 렌더러에 보여줘도 된다.
let profile = {};

// 'changed'  : 로그인/갱신/로그아웃으로 세션이 바뀜
// 'expired'  : 갱신까지 실패해서 세션을 버림 → 로그인 화면으로 보내야 함
const events = new EventEmitter();

// TODO(Q5-2): 서버가 기대하는 deviceId 형식 확인 후 실제 기기 식별자로 교체.
//             현재는 기존 동작을 그대로 유지하기 위해 '1' 고정.
const DEVICE_ID = '1';

// JWT 의 exp(초)를 읽어 ms 로 돌려준다. JWT 가 아니거나 exp 가 없으면 null.
// 서명 검증은 서버 몫이고, 여기서는 "언제 갱신할지" 판단에만 쓴다.
function readJwtExpiry(token) {
  try {
    const parts = String(token || '').split('.');
    if (parts.length !== 3) return null;
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null;
  } catch (_) {
    return null;
  }
}

// 세션 저장. 토큰 교환/로그인/갱신 성공 시 호출한다.
function setSession({ accessToken: nextAccessToken, refreshToken: nextRefreshToken, endpoint: nextEndpoint } = {}) {
  if (nextAccessToken) {
    accessToken = nextAccessToken;
    accessTokenExpiresAt = readJwtExpiry(nextAccessToken);
  }
  if (nextRefreshToken) refreshToken = nextRefreshToken;
  if (nextEndpoint) endpoint = nextEndpoint;
  persistSession();
  events.emit('changed', { authenticated: true });
}

function clearSession() {
  accessToken = null;
  refreshToken = null;
  endpoint = '';
  accessTokenExpiresAt = null;
  profile = {};
  sessionStore.clear();
  events.emit('changed', { authenticated: false });
}

// 로그인 유지가 켜져 있으면 지금 세션을 저장한다(꺼져 있으면 저장 파일을 지운다). 수동 로그인(refreshToken 없음)도 저장한다.
function persistSession() {
  sessionStore.save({ accessToken, refreshToken, endpoint, profile });
}

// 앱 시작 시 저장해 둔 세션을 메모리로 올린다. 복원했으면 true.
// accessToken 이 만료됐어도 그대로 올린다 — 첫 API 요청 전에 ensureFreshToken / 401 처리가 갱신하고,
// 갱신이 거절되면 expireSession 으로 로그인 화면에 간다.
function restoreSession() {
  const saved = sessionStore.load();
  if (!saved) return false;
  // 수동 로그인처럼 refreshToken 이 없는 세션은 accessToken 이 만료됐으면 갱신할 방법이 없으니 버린다(로그인 화면).
  // 만료 시각을 모르면(JWT 아님) 그대로 올리고, 쓰다가 401 이 나면 기존 만료 처리를 탄다.
  const savedExpiresAt = readJwtExpiry(saved.accessToken);
  if (!saved.refreshToken && savedExpiresAt && Date.now() >= savedExpiresAt) {
    try { logger.logInfo('session_restore_skipped', { reason: 'access_token_expired_no_refresh_token' }); } catch (_) {}
    sessionStore.clear();
    return false;
  }
  accessToken = saved.accessToken;
  refreshToken = saved.refreshToken || null;
  endpoint = saved.endpoint;
  accessTokenExpiresAt = readJwtExpiry(saved.accessToken);
  profile = { ...(saved.profile || {}) };
  try {
    logger.logInfo('session_restored', {
      savedAt: saved.savedAt ? new Date(saved.savedAt).toISOString() : null,
      accessTokenExpired: accessTokenExpiresAt ? Date.now() >= accessTokenExpiresAt : null,
      hasEmpno: !!profile.empno,
      hasRefreshToken: !!refreshToken,
    });
  } catch (_) {}
  events.emit('changed', { authenticated: true });
  return true;
}

function getAccessToken() {
  return accessToken;
}

function getRefreshToken() {
  return refreshToken;
}

function getEndpoint() {
  return endpoint;
}

function getDeviceId() {
  return DEVICE_ID;
}

function isAuthenticated() {
  return !!accessToken;
}

function getProfile() {
  return { ...profile };
}

// 사용자 정보를 합친다. overwrite: false 면 이미 있는 값은 그대로 둔다
// (수동 로그인으로 입력한 이름을 서버 응답이 덮어쓰지 않게).
function mergeProfile(next, { overwrite = true } = {}) {
  for (const [key, value] of Object.entries(next || {})) {
    if (value === undefined || value === null || value === '') continue;
    if (!overwrite && profile[key]) continue;
    profile[key] = value;
  }
  if (accessToken) persistSession();
}

// 테스트용 수동 로그인. SSO 협조가 늦어져도 녹음 → 업로드를 바로 시험할 수 있게
// 웹에서 복사해 온 accessToken 으로 세션을 만든다. refreshToken 이 없으므로 만료되면 다시 입력해야 한다.
function startManualSession({ name, empno, accessToken: token, endpoint: targetEndpoint } = {}) {
  const trimmedToken = String(token || '').trim().replace(/^Bearer\s+/i, '');
  if (!trimmedToken) return { success: false, error: 'access_token_required' };
  try {
    const url = new URL(targetEndpoint);
    if (!/^https?:$/.test(url.protocol)) throw new Error('invalid_protocol');
  } catch (_) {
    return { success: false, error: 'invalid_endpoint' };
  }

  clearSession();
  setSession({ accessToken: trimmedToken, endpoint: String(targetEndpoint).replace(/\/+$/, '') });
  mergeProfile({ name: String(name || '').trim(), empno: String(empno || '').trim() });
  try { logger.logInfo('manual_session_started', { endpoint: targetEndpoint, hasName: !!profile.name, hasEmpno: !!profile.empno }); } catch (_) {}
  return { success: true };
}

function onSessionExpired(listener) {
  events.on('expired', listener);
}

// 서버 공통 응답 봉투 { message, httpCode, data } 에서 토큰을 꺼낸다.
// - data.tokens.accessToken / data.tokens.refreshToken (refresh 등). data 바로 아래에 있어도 받는다.
function pickTokens(data) {
  const src = (data && data.tokens) || data || {};
  return { accessToken: src.accessToken || null, refreshToken: src.refreshToken || null };
}

// 시스템 로그인(AM-Tray): AM DLL 이 준 인가토큰을 우리 백엔드에 보내 우리 토큰으로 바꾼다.
// 백엔드가 SSO 서버(samlam .../tray/api/ValidateToken)로 검증하고 USERID(사번)로 토큰을 발급한다.
// ★ 인증서버 API 는 아직 반영 전(초안·요청서 docs/sso-amtray-java/backend-request/, 경로 /api/auth/sso/amtray).
//   AMTRAY_LOGIN_PATH 가 비면 'amtray_server_not_ready'.
// ★ 요청/응답 — 초안(ssoAmTray.js)과 같다. 실제 반영본이 다르면 여기만 맞춘다:
//   POST {AMTRAY_LOGIN_BASE_URL 또는 HMP_BASE_URL}{AMTRAY_LOGIN_PATH}  body { authzToken }
//   응답 = 서버 공통 봉투 { httpCode, message, data: { empno?, tokens: { accessToken, refreshToken } } }
//   httpCode 404/422 = 약관 미동의, 401/403 = 토큰 검증 실패
// ★ 11-28 인계문서 4-1: refreshToken 은 서버에 PC 키가 없을 때만 온다. 응답에 없으면 갖고 있던 값을 그대로 쓴다
//   (setSession 은 빈 값으로 덮어쓰지 않는다). 로그인 요청에는 토큰 헤더를 붙이지 않는다(skipAuth — 붙이면 옛 토큰을 돌려줌).
async function loginWithAmToken(authzToken) {
  if (!authConfig.AMTRAY_LOGIN_PATH) return { success: false, error: 'amtray_server_not_ready' };
  const { client } = require('./apiService');
  const baseURL = authConfig.AMTRAY_LOGIN_BASE_URL || authConfig.HMP_BASE_URL;
  try {
    try { logger.logInfo('amtray_login_begin', { baseURL }); } catch (_) {}
    const res = await client.post(authConfig.AMTRAY_LOGIN_PATH, { authzToken }, {
      baseURL,
      skipAuth: true,
      headers: { 'content-type': 'application/json' },
      timeout: 15000,
      validateStatus: () => true,
    });
    const result = res && res.data;
    if (!result || typeof result !== 'object') {
      try { logger.logError('amtray_login_invalid_response', { status: res && res.status }); } catch (_) {}
      return { success: false, error: 'invalid_response', status: res && res.status };
    }
    const tokens = pickTokens(result.data);
    if (result.httpCode !== 200 || !tokens.accessToken) {
      try { logger.logWarn('amtray_login_failed', { httpCode: result.httpCode, message: result.message }); } catch (_) {}
      if (authConfig.TERMS_CHECK_ENABLED && isTermsNotAgreedCode(result.httpCode)) {
        return { success: false, error: 'terms_not_agreed', httpCode: result.httpCode, message: result.message };
      }
      return { success: false, error: 'login_rejected', httpCode: result.httpCode, message: result.message };
    }
    setSession({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken, endpoint: baseURL });
    const data = result.data || {};
    // loginMethod: 시스템 로그인 세션 표시 — 로그인 뒤 AM-Tray 상태 확인(IsLoginIT 등)은 이 세션에만 한다
    mergeProfile({ empno: data.empno || data.userId || data.USERID, loginMethod: 'system' });
    try { logger.logInfo('amtray_login_success', { refreshTokenIssued: !!tokens.refreshToken }); } catch (_) {}
    return { success: true };
  } catch (err) {
    try { logger.logError('amtray_login_network_error', { message: err && err.message, code: err && err.code }); } catch (_) {}
    return { success: false, error: 'network_error', message: err && err.message };
  }
}

// AM-Tray 인가토큰을 그대로 사용자 토큰으로 저장(AMTRAY_TOKEN_MODE 'direct', 11-16). 테스트 로그인과 같다.
//   서버 주소는 DEFAULT_API_BASE_URL. refreshToken 은 없다 → 만료되면 로그인 화면 → AM-Tray 로 다시 받는다.
function startAmTokenSession(token) {
  const value = String(token || '').trim();
  if (!value) return { success: false, error: 'access_token_required' };
  clearSession();
  setSession({ accessToken: value, endpoint: String(authConfig.DEFAULT_API_BASE_URL || '').replace(/\/+$/, '') });
  mergeProfile({ loginMethod: 'system' });
  try { logger.logInfo('amtray_token_session_started', { endpoint: endpoint }); } catch (_) {}
  return { success: true };
}

// 모바일(intro_controller.dart termsAgreeCheck) 기준: 약관 확인 API 응답 httpCode 404/422 는 약관 미동의.
function isTermsNotAgreedCode(httpCode) {
  return httpCode === 404 || httpCode === 422;
}

// ★ 약관 동의 확인 전용 — 로그인이 아니다. 테스트 로그인·로그인 유지 복원 뒤에 부른다.
//   (11-28: 시스템 로그인은 로그인 API(/auth/sso/amtray)가 안에서 약관을 확인하고 404/422 면 토큰을 안 준다 → 여기 안 부름)
// 모바일 앱과 같은 API(HMP_LOGIN_PATH, body { empno })를 불러 httpCode 만 본다.
// 응답에 토큰이 같이 오지만 쓰지 않는다(지금 세션은 그대로 둔다). 이 API 로 로그인하지 않는다.
// 반환: { agreed: true } | { agreed: false, httpCode, message } | { agreed: null, error, ... }(판단 못 함)
async function checkTermsAgreed(empno) {
  const { client, mobileAppHeaders } = require('./apiService');
  const id = String(empno || '').trim();
  if (!id) return { agreed: null, error: 'empno_missing' };

  try {
    const res = await client.post(authConfig.HMP_LOGIN_PATH, { empno: id }, {
      baseURL: authConfig.HMP_BASE_URL,
      skipAuth: true,
      skipRefresh: true,
      // 모바일 API 라 예전처럼 모바일 헤더 4개를 그대로 보낸다(11-28 — 다른 요청은 timblo-App-OS 만)
      headers: { 'content-type': 'application/json', ...mobileAppHeaders() },
      maxRedirects: 5,
      timeout: 8000,
      validateStatus: () => true,
    });
    const result = res && res.data;
    if (!result || typeof result !== 'object') return { agreed: null, error: 'invalid_response', status: res && res.status };
    if (isTermsNotAgreedCode(result.httpCode)) return { agreed: false, httpCode: result.httpCode, message: result.message };
    if (result.httpCode === 200) return { agreed: true };
    return { agreed: null, error: 'unexpected_code', httpCode: result.httpCode, message: result.message };
  } catch (err) {
    return { agreed: null, error: 'network_error', message: err && err.message };
  }
}

// AI회의록 이용 권한 확인 — 로그인(약관 확인) 뒤에 부른다. 지금 세션의 토큰으로 서버에 묻는다.
// ★ API 는 백엔드가 새로 만드는 중이라 아직 흉내만 낸다(authConfig ACCESS_CHECK_*).
//   - ACCESS_CHECK_MOCK 'denied' / 'allowed' → 서버를 부르지 않고 그 결과
//   - ACCESS_CHECK_PATH 가 비어 있으면 → 판단 못 함(통과)
// 반환: { allowed: true } | { allowed: false, httpCode, message } | { allowed: null, error, ... }(판단 못 함 → 막지 않음)
async function checkMinutesAccess() {
  if (authConfig.ACCESS_CHECK_MOCK === 'denied') return { allowed: false, mock: true };
  if (authConfig.ACCESS_CHECK_MOCK === 'allowed') return { allowed: true, mock: true };
  if (!authConfig.ACCESS_CHECK_PATH) return { allowed: null, error: 'not_configured' };

  const { client } = require('./apiService');
  try {
    const res = await client.request({
      url: authConfig.ACCESS_CHECK_PATH,
      method: authConfig.ACCESS_CHECK_METHOD,
      timeout: 8000,
      validateStatus: () => true,
    });
    const result = res && res.data;
    if (!result || typeof result !== 'object') return { allowed: null, error: 'invalid_response', status: res && res.status };
    // ★ 응답 해석 — API 가 확정되면 여기만 맞춘다. 지금은 서버 공통 봉투 { httpCode, message, data } 기준으로 가정:
    //   httpCode 403 이거나 data 의 권한 값이 false 면 권한 없음, httpCode 200 이면 권한 있음.
    const data = result.data && typeof result.data === 'object' ? result.data : {};
    const flag = [data.hasAuth, data.authorized, data.allowed].find((v) => typeof v === 'boolean');
    if (result.httpCode === 403 || flag === false) return { allowed: false, httpCode: result.httpCode, message: result.message };
    if (result.httpCode === 200) return { allowed: true };
    return { allowed: null, error: 'unexpected_code', httpCode: result.httpCode, message: result.message };
  } catch (err) {
    return { allowed: null, error: 'network_error', message: err && err.message };
  }
}

// refreshToken 으로 accessToken 을 새로 받는다.
// 동시에 여러 요청이 401 을 받아도 갱신은 한 번만 나가고, 모두 그 결과를 기다린다.
function refreshAccessToken() {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = doRefresh().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

async function doRefresh() {
  if (!refreshToken || !endpoint) {
    // refreshToken 이 없으면(테스트 로그인 등) 갱신 수단이 없다 → 재로그인 대상.
    return { success: false, error: 'no_refresh_token' };
  }

  const { client, tokenHeaders } = require('./apiService');
  try {
    const res = await client.request({
      method: authConfig.REFRESH_METHOD,
      url: authConfig.REFRESH_PATH,
      baseURL: endpoint,
      data: { token: refreshToken, fcmToken: '' },
      skipAuth: true,     // 아래에서 만료된 토큰을 직접 붙인다(모바일과 동일)
      skipRefresh: true,  // 갱신 요청이 401 을 받아도 다시 갱신하러 들어가지 않게
      headers: { 'content-type': 'application/json', ...tokenHeaders(accessToken) },
      validateStatus: () => true,
    });

    const result = res && res.data;
    const tokens = pickTokens(result && result.data);
    if (!result || result.httpCode !== 200 || !tokens.accessToken) {
      // 529 리프레시 토큰 없음 / 530 저장값과 다름 / 531 서명 오류·만료 → AM-Tray 로 다시 로그인 대상(인계문서 7-2)
      try { logger.logWarn('token_refresh_failed', { status: res && res.status, httpCode: result && result.httpCode }); } catch (_) {}
      return { success: false, error: 'refresh_rejected', httpCode: result && result.httpCode };
    }

    setSession({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken });
    try { logger.logInfo('token_refresh_success', { refreshTokenRotated: !!tokens.refreshToken }); } catch (_) {}
    return { success: true };
  } catch (err) {
    try { logger.logError('token_refresh_network_error', { message: err && err.message }); } catch (_) {}
    // 네트워크 오류는 토큰 문제가 아니므로 세션을 버리지 않는다(호출부가 실패 처리).
    return { success: false, error: 'network_error' };
  }
}

// 요청 직전에 호출. 만료가 임박했으면 미리 갱신한다.
// 만료 시각을 모르거나(JWT 아님) refreshToken 이 없으면 아무것도 하지 않는다.
// 갱신이 거절되면(529·530·531 등) AM-Tray 로 다시 로그인을 한 번 해 보고, 그것도 안 되면 세션을 버린다(11-28).
async function ensureFreshToken() {
  if (!accessToken || !refreshToken || !accessTokenExpiresAt) return;
  if (Date.now() < accessTokenExpiresAt - authConfig.REFRESH_BEFORE_EXPIRY_MS) return;
  const refreshed = await refreshAccessToken();
  if (refreshed.success || refreshed.error === 'network_error') return;
  const reauth = await tryReauth(refreshed);
  if (!reauth.success) expireSession(reauth.error);
}

// ---- 갱신이 거절됐을 때 AM-Tray 로 조용히 다시 로그인 (11-28) ----
// handleAuth 가 실제 동작(GetSystemToken → loginWithAmToken, 같은 사람인지 확인)을 넣어 준다.
// 화면·팝업은 건드리지 않는다(녹음 중에도 불릴 수 있다). 여러 요청이 동시에 실패해도 한 번만 한다.
let reauthHandler = null;
let reauthInFlight = null;
function setReauthHandler(fn) {
  reauthHandler = typeof fn === 'function' ? fn : null;
}
function tryReauth(cause = {}) {
  if (reauthInFlight) return reauthInFlight;
  reauthInFlight = (async () => {
    if (!reauthHandler || !accessToken || profile.loginMethod !== 'system') {
      return { success: false, error: cause.error || 'refresh_rejected' };
    }
    try { logger.logInfo('reauth_begin', { cause: cause.error, httpCode: cause.httpCode }); } catch (_) {}
    let r;
    try { r = await reauthHandler(); } catch (err) { r = { success: false, error: 'reauth_exception', message: err && err.message }; }
    try { logger[r && r.success ? 'logInfo' : 'logWarn']('reauth_result', { success: !!(r && r.success), error: r && r.error, code: r && r.code, httpCode: r && r.httpCode }); } catch (_) {}
    return r && r.success ? { success: true } : { success: false, error: (r && r.error) || 'reauth_failed' };
  })().finally(() => { reauthInFlight = null; });
  return reauthInFlight;
}

// 서버 로그아웃(DELETE /api/auth/logout, 인계문서 4-3). 서버의 PC refreshToken·세션을 지운다.
//   이걸 안 부르면 다음 로그인 때 서버가 refreshToken 을 새로 주지 않아(키가 남아 있으면 미발급, 4-1) 갱신을 못 한다.
//   ★ 시스템 로그인(AM-Tray → 우리 토큰) 세션만 부른다. 테스트 로그인은 웹에서 복사한 토큰이라 부르면 웹 세션이 끊긴다.
//   실패해도 앱 로그아웃은 그대로 진행한다(호출부는 clearSession 전에 부르고 결과를 기다리되 오래 막지 않는다).
async function logoutOnServer(reason) {
  if (!accessToken || profile.loginMethod !== 'system' || authConfig.AMTRAY_TOKEN_MODE !== 'backend' || !authConfig.LOGOUT_PATH) {
    return { called: false };
  }
  const { client, tokenHeaders } = require('./apiService');
  try {
    const res = await client.request({
      method: authConfig.LOGOUT_METHOD,
      url: authConfig.LOGOUT_PATH,
      baseURL: endpoint,
      skipAuth: true,
      skipRefresh: true,
      headers: tokenHeaders(accessToken),
      timeout: 5000,
      validateStatus: () => true,
    });
    const result = res && res.data;
    const httpCode = result && typeof result === 'object' ? result.httpCode : undefined;
    try { logger.logInfo('server_logout', { reason, status: res && res.status, httpCode }); } catch (_) {}
    return { called: true, ok: httpCode === 204 || httpCode === 200 };
  } catch (err) {
    try { logger.logWarn('server_logout_failed', { reason, message: err && err.message }); } catch (_) {}
    return { called: true, ok: false };
  }
}

// 갱신까지 실패해서 더는 쓸 수 없는 세션을 정리하고 알린다.
function expireSession(reason) {
  if (!accessToken) return;
  try { logger.logWarn('session_expired', { reason }); } catch (_) {}
  clearSession();
  events.emit('expired', { reason });
}

module.exports = {
  setSession,
  clearSession,
  restoreSession,
  getAccessToken,
  getRefreshToken,
  getEndpoint,
  getDeviceId,
  isAuthenticated,
  getProfile,
  mergeProfile,
  startManualSession,
  onSessionExpired,
  loginWithAmToken,
  startAmTokenSession,
  checkTermsAgreed,
  checkMinutesAccess,
  refreshAccessToken,
  ensureFreshToken,
  expireSession,
  setReauthHandler,
  tryReauth,
  logoutOnServer,
};
