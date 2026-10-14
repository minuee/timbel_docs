// 사용자 관련 API 호출
// - 주소·파라미터는 apiEndpoints.js 에서 읽는다. 이 파일은 "언제, 무엇을" 부를지만 안다.
// - 모두 부가 기능이다. 실패해도 로그인·녹음·업로드는 그대로 진행돼야 하므로 예외를 던지지 않는다.

const logger = require('../logger');
const endpoints = require('./apiEndpoints');
const authService = require('./authService');

// 로그인 화면이 오래 멈춰 있지 않도록 부가 API 는 짧게 끊는다(업로드는 이 함수를 쓰지 않는다).
const CALL_TIMEOUT_MS = 8000;

// '{empno}' 같은 자리표시를 사용자 정보로 바꾼다. 비어 있는 값이 있으면 missing 에 담는다.
function fill(value, vars, missing) {
  if (typeof value === 'string') {
    return value.replace(/\{(\w+)\}/g, (_, key) => {
      const v = vars[key];
      if (v === undefined || v === null || v === '') missing.push(key);
      return v == null ? '' : String(v);
    });
  }
  if (Array.isArray(value)) return value.map((v) => fill(v, vars, missing));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = fill(v, vars, missing);
    return out;
  }
  return value;
}

function getPath(obj, dotted) {
  return String(dotted).split('.').reduce((acc, key) => (acc == null ? undefined : acc[key]), obj);
}

// apiEndpoints 의 항목 하나를 호출한다.
// 반환: { success, data(응답 본문), picked(pick 결과), error }
async function callApi(name) {
  const def = endpoints[name];
  if (!def) return { success: false, error: 'unknown_api' };

  const { client } = require('./apiService');
  const vars = authService.getProfile();
  const missing = [];
  const url = fill(def.url, vars, missing);
  const params = fill(def.params, vars, missing);
  const data = fill(def.body, vars, missing);
  if (missing.length) {
    try { logger.logWarn('api_skipped_missing_value', { api: name, missing }); } catch (_) {}
    return { success: false, error: 'missing_value', missing };
  }

  try {
    const res = await client.request({
      method: def.method || 'get',
      url,
      params,
      data,
      ...(def.baseURL ? { baseURL: def.baseURL } : {}),
      skipAuth: !def.auth,
      timeout: CALL_TIMEOUT_MS,
      validateStatus: () => true,
    });

    const body = res.data;
    // 서버 공통 봉투 { httpCode, message, data } 면 httpCode 로, 아니면 HTTP 상태로 판단한다.
    const code = body && typeof body === 'object' && 'httpCode' in body ? body.httpCode : res.status;
    if (code < 200 || code >= 300) {
      try { logger.logWarn('api_failed', { api: name, status: res.status, httpCode: code, message: body && body.message }); } catch (_) {}
      return { success: false, error: 'api_failed', status: res.status, httpCode: code, data: body };
    }

    const picked = {};
    for (const [key, dotted] of Object.entries(def.pick || {})) {
      const v = getPath(body, dotted);
      if (v !== undefined && v !== null && v !== '') picked[key] = v;
    }
    try { logger.logInfo('api_success', { api: name, pickedKeys: Object.keys(picked) }); } catch (_) {}
    return { success: true, data: body, picked };
  } catch (err) {
    try { logger.logError('api_network_error', { api: name, message: err && err.message, code: err && err.code }); } catch (_) {}
    return { success: false, error: 'network_error' };
  }
}

// 로그인 직후: 내 정보 → 워크스페이스.
// 이미 아는 값(수동 로그인으로 입력한 이름·사번 등)은 덮어쓰지 않는다.
async function loadProfileAfterLogin() {
  const me = await callApi('userMe');
  if (me.success) {
    const p = me.picked;
    authService.mergeProfile({ ...p, name: p.name || p.nickName }, { overwrite: false });
  }
  const ws = await callApi('workspace');
  if (ws.success) authService.mergeProfile(ws.picked, { overwrite: false });
  try { logger.logInfo('profile_loaded', { hasName: !!authService.getProfile().name, hasEmpno: !!authService.getProfile().empno }); } catch (_) {}
}

// 녹음 시작 시: 부서장에게 녹음 시작 안내 메일(서버가 부서장 메일을 찾아 발송).
async function sendRecordingAlert() {
  return callApi('alertRecording');
}

module.exports = { callApi, loadProfileAfterLogin, sendRecordingAlert };
