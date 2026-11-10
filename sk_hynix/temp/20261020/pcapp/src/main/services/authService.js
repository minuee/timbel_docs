// 인증 세션 보관 및 토큰 발급/갱신 담당
// - accessToken 은 이 모듈 밖으로 노출하지 않는다(렌더러에도 전달하지 않는다).
//   외부에서는 apiService 를 통해 요청만 보내고, 헤더 부착은 apiService 가 처리한다.
// - 세션은 기본적으로 메모리에만 둔다. 앱을 끄면 사라지고, 다시 켜면 로그인부터 한다.
//   (디스크에 남기지 않으므로 PC를 같이 쓰는 사람이 토큰을 꺼내 갈 수 없다)
//   SESSION_PERSIST_ENABLED 가 true 이고 사용자가 "로그인 유지"를 체크했으면 암호화해서 저장해 두고
//   다음 실행 때 복원한다(sessionStore.js, loginPrefs.js).
// - 로그인 경로는 두 가지다.
//   1) MyAccess(SSO) → 딥링크 timbloRecApp://connect 로 받은 code 교환  : exchangeToken()
//   2) 사번 직접 입력 → HMP API                                       : loginWithEmpno()
//   3) (테스트용) 이름·사번·accessToken 직접 입력                      : startManualSession()

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

// 로그인 유지가 켜져 있으면 지금 세션을 저장한다(꺼져 있으면 저장 파일을 지운다). refreshToken 이 없는 세션(수동 로그인)은 sessionStore 가 건너뛴다.
function persistSession() {
  sessionStore.save({ accessToken, refreshToken, endpoint, profile });
}

// 앱 시작 시 저장해 둔 세션을 메모리로 올린다. 복원했으면 true.
// accessToken 이 만료됐어도 그대로 올린다 — 첫 API 요청 전에 ensureFreshToken / 401 처리가 갱신하고,
// 갱신이 거절되면 expireSession 으로 로그인 화면에 간다.
function restoreSession() {
  const saved = sessionStore.load();
  if (!saved) return false;
  accessToken = saved.accessToken;
  refreshToken = saved.refreshToken;
  endpoint = saved.endpoint;
  accessTokenExpiresAt = readJwtExpiry(saved.accessToken);
  profile = { ...(saved.profile || {}) };
  try {
    logger.logInfo('session_restored', {
      savedAt: saved.savedAt ? new Date(saved.savedAt).toISOString() : null,
      accessTokenExpired: accessTokenExpiresAt ? Date.now() >= accessTokenExpiresAt : null,
      hasEmpno: !!profile.empno,
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
// - exchange 응답 : data.accessToken / data.refreshToken
// - hmp, refresh  : data.tokens.accessToken / data.tokens.refreshToken
function pickTokens(data) {
  const src = (data && data.tokens) || data || {};
  return { accessToken: src.accessToken || null, refreshToken: src.refreshToken || null };
}

// 딥링크로 받은 1회용 code 를 accessToken 으로 교환한다.
// GET {endpoint}/api/auth/recorder/exchange/{code}
async function exchangeToken(targetEndpoint, code) {
  // apiService 와 상호 참조 관계라 호출 시점에 지연 로딩한다.
  const { client } = require('./apiService');

  try {
    const res = await client.get(`/api/auth/recorder/exchange/${encodeURIComponent(code)}`, {
      baseURL: targetEndpoint,
      skipAuth: true, // 교환 시점에는 아직 토큰이 없다
      headers: { 'content-type': 'application/json' },
      // 상태코드와 무관하게 응답 본문을 그대로 해석한다(서버가 httpCode 를 본문에 담아 보냄)
      validateStatus: () => true,
    });

    const result = res && res.data;
    if (!result || typeof result !== 'object') {
      try { logger.logError('exchange_token_invalid_response', { status: res && res.status }); } catch (_) {}
      return { success: false, error: 'network_error' };
    }

    if (result.message !== 'Success') {
      try { logger.logError('exchange_token_failed', { httpCode: result.httpCode, message: result.message }); } catch (_) {}
      return { success: false, error: `httpCode : ${result.httpCode}` };
    }

    const tokens = pickTokens(result.data);

    // 토큰 값 자체는 로그에 남기지 않는다(로그 파일은 평문으로 7일간 보존됨).
    try {
      logger.logInfo('exchange_token_success', {
        accessTokenLength: tokens.accessToken ? String(tokens.accessToken).length : 0,
        refreshTokenIssued: !!tokens.refreshToken,
      });
    } catch (_) {}

    return { success: true, result: tokens.accessToken, refreshToken: tokens.refreshToken };
  } catch (err) {
    try { logger.logError('exchange_token_network_error', { message: err && err.message }); } catch (_) {}
    return { success: false, error: 'network_error' };
  }
}

// 사번으로 직접 로그인한다(모바일앱의 HMP 로그인과 같은 API).
// POST {HMP_BASE_URL}{HMP_LOGIN_PATH}  body { empno }
// 응답: { httpCode, message, data: { is2FA, tokens: { accessToken, refreshToken } } }
//
// ⚠️ 이 API 는 비밀번호를 받지 않는다. 모바일은 사내 HMP 앱이 이미 본인 인증을 끝낸 뒤
//    사번을 넘겨주기 때문에 사번만으로 충분했지만, PC 에서는 아무 사번이나 입력할 수 있다.
//    서버가 비밀번호 검증을 추가하기 전까지는 운영 배포에서 이 경로를 막아야 한다.
async function loginWithEmpno(empno, password) {
  const { client } = require('./apiService');
  const baseURL = authConfig.HMP_BASE_URL;
  const body = { empno: String(empno || '').trim() };
  // 서버가 비밀번호 필드를 받게 되면 이름만 맞춰 여기서 보낸다. 그 전에는 보내지 않는다
  // (검증하지 않는 서버로 평문 비밀번호를 흘려보낼 이유가 없다).
  if (authConfig.HMP_PASSWORD_FIELD && password) body[authConfig.HMP_PASSWORD_FIELD] = password;

  if (!body.empno) return { success: false, error: 'empno_required' };

  try {
    try { logger.logInfo('hmp_login_begin', { baseURL }); } catch (_) {}
    const res = await client.post(authConfig.HMP_LOGIN_PATH, body, {
      baseURL,
      skipAuth: true,
      headers: { 'content-type': 'application/json' },
      // 모바일(dio followRedirects: true)과 같게 리다이렉트를 따라간다. axios 기본값도 따라감.
      maxRedirects: 5,
      validateStatus: () => true,
    });

    const result = res && res.data;
    if (!result || typeof result !== 'object') {
      try { logger.logError('hmp_login_invalid_response', { status: res && res.status }); } catch (_) {}
      return { success: false, error: 'invalid_response', status: res && res.status };
    }

    const tokens = pickTokens(result.data);
    if (result.httpCode !== 200 || !tokens.accessToken) {
      try { logger.logWarn('hmp_login_failed', { httpCode: result.httpCode, message: result.message }); } catch (_) {}
      // 모바일 기준 404/422 는 "약관 동의 필요". 서버 메시지를 그대로 보여준다.
      return { success: false, error: 'login_rejected', httpCode: result.httpCode, message: result.message };
    }

    setSession({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken, endpoint: baseURL });
    mergeProfile({ empno: body.empno });
    try {
      logger.logInfo('hmp_login_success', {
        refreshTokenIssued: !!tokens.refreshToken,
        expiresAt: accessTokenExpiresAt ? new Date(accessTokenExpiresAt).toISOString() : null,
      });
    } catch (_) {}
    return { success: true };
  } catch (err) {
    try { logger.logError('hmp_login_network_error', { message: err && err.message, code: err && err.code }); } catch (_) {}
    return { success: false, error: 'network_error', message: err && err.message };
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
    // exchange 응답에 refreshToken 이 없으면 갱신 수단이 없다 → 재로그인 대상.
    return { success: false, error: 'no_refresh_token' };
  }

  const { client } = require('./apiService');
  try {
    const res = await client.request({
      method: authConfig.REFRESH_METHOD,
      url: authConfig.REFRESH_PATH,
      baseURL: endpoint,
      data: { token: refreshToken, fcmToken: '' },
      skipAuth: true,     // 아래에서 만료된 토큰을 직접 붙인다(모바일과 동일)
      skipRefresh: true,  // 갱신 요청이 401 을 받아도 다시 갱신하러 들어가지 않게
      headers: { 'content-type': 'application/json', Authorization: `Bearer ${accessToken}` },
      validateStatus: () => true,
    });

    const result = res && res.data;
    const tokens = pickTokens(result && result.data);
    if (!result || result.httpCode !== 200 || !tokens.accessToken) {
      try { logger.logWarn('token_refresh_failed', { status: res && res.status, httpCode: result && result.httpCode }); } catch (_) {}
      return { success: false, error: 'refresh_rejected' };
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
async function ensureFreshToken() {
  if (!accessToken || !refreshToken || !accessTokenExpiresAt) return;
  if (Date.now() < accessTokenExpiresAt - authConfig.REFRESH_BEFORE_EXPIRY_MS) return;
  await refreshAccessToken();
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
  exchangeToken,
  loginWithEmpno,
  refreshAccessToken,
  ensureFreshToken,
  expireSession,
};
