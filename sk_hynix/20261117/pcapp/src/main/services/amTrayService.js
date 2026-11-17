// AM-Tray(SSO 에이전트) 연동 — 시스템 로그인
// - AM 인터페이스 DLL 호출 방식(authConfig.AMTRAY_ENGINE):
//     'koffi'(기본)  → amTrayWorker.js(utilityProcess, 별도 프로세스)가 koffi 로 DLL 을 바로 부른다. C++ 빌드 없음.
//     'helper'       → 예전 방식. AmHelper.exe(src/helpers/windows/amtray)를 한 번씩 실행하고 stdout JSON 한 줄을 읽는다.
//                      ⚠️ AmHelper.exe 는 옛 가정(Java 모양) 그대로라 진짜 DLL 에는 맞지 않는다(2026-11-14). 쓰지 말 것.
//   어느 쪽이든 DLL 이 죽어도 앱은 죽지 않는다(죽는 건 작업 프로세스/exe 뿐).
//   (예외: 11-18 시험용 AMTRAY_DLL_PROCESS='main' — koffi 를 본체에서 바로 부른다. DLL 이 죽으면 앱도 죽는다. runInMain)
// - 흐름과 응답코드 (C++ 매뉴얼 — 함수 모양 11-14, 응답코드 표·대응 11-16. 함수 모양은 amTrayDll.js 맨 위):
//     GetSystemToken(ssoKey, sid, systemCode)   ※ Init 을 포함하므로 따로 부르지 않는다
//       203030                     → 인가토큰                                  kind 'token'
//       504011 미로그인, 503035 토큰 발급 API 통신 실패 → ShowSSOLoginUI          kind 'not_logged_in'
//       503031~503034, 503036      → 응답 메시지 팝업([확인] → 앱 종료)          kind 'denied'
//       509090 / 공백(BOOL=false)   → AM-Tray 설치 페이지 안내                    kind 'install'
//       500001 / 500003            → 연동 모듈(DLL) 문제                         kind 'unavailable'
//     ShowSSOLoginUI (앞에 Init)
//       203012 성공 / 506021 이미 로그인 → 토큰 한 번 더 / 502050·502051 → [다시 시도][앱 종료]
//       502052·공백 → SSO 로그인 불가 [확인] → 앱 종료 / Init 실패(501010·509090·공백) → 설치 안내
//     IsLoginIT (앞에 Init) — 206030 로그인 / 504011 미로그인 / 501010 Init 다시(amTrayDll) / 502011 설정 없음 / 509090 그대로
//     CheckLoginUserIT (앞에 Init) — 206040 같은 사람 / 506040 다른 사람 / 506041·504011 로그아웃
// - authConfig.AMTRAY_MOCK 이 있으면 exe·DLL 없이 흉내 낸다(Mac 에서도 화면 흐름 확인 가능).

const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');
const { utilityProcess } = require('electron');
const logger = require('../logger');
const authConfig = require('./authConfig');
const { tokenShape } = require('./amTrayDll'); // 값은 남기지 않고 모양만 로그에

const CODE_NOT_LOGGED_IN = '504011';
// 토큰 발급 API 통신 실패 — 11-16 결정: 미로그인처럼 AM-Tray 로그인(ShowSSOLoginUI)으로
const CODE_TOKEN_API_FAILED = '503035';
// AM-Tray 가 없음·꺼짐 → 설치 페이지 안내. '' = 명세의 "공백"(BOOL=false 도 여기로)
//   Init 단계에서 나온 501010(초기화 실패)도 같은 안내(매뉴얼 6.2)
const CODES_INSTALL = ['509090', ''];
const CODES_INIT_FAILED = ['501010', '509090', ''];
// 연동 모듈(DLL) 문제 — 500001 DLL 로드 실패, 500003 DLL API 통신 실패
const CODES_UNAVAILABLE = ['500001', '500003'];
// 시스템 접근 불가 → 응답 메시지 팝업 후 앱 종료(권한 없음 팝업과 같게)
const CODES_DENIED = ['503031', '503032', '503033', '503034', '503036'];

const TIMEOUT_TOKEN_MS = 15 * 1000;
const TIMEOUT_SHOW_UI_MS = 30 * 1000; // 창을 띄우고 바로 돌아오는지, 로그인 끝까지 막는지 모름 → 넉넉히
const TIMEOUT_MESSAGE_MS = 5 * 1000;
const TIMEOUT_CHECK_MS = 5 * 1000; // IsLoginIT·CheckLoginUserIT — 녹음 시작을 오래 막지 않도록 짧게

function getHelperPath() {
  const candidates = [
    // 설치본: extraFiles 로 설치 폴더 helpers/windows/amtray 에 둔다(AudioHelper 와 같은 방식)
    path.join(process.resourcesPath || '', '..', 'helpers', 'windows', 'amtray', 'AmHelper.exe'),
    path.join(process.resourcesPath || '', 'helpers', 'windows', 'amtray', 'AmHelper.exe'),
    // 개발: 소스 트리
    path.join(__dirname, '..', '..', 'helpers', 'windows', 'amtray', 'bin', 'AmHelper.exe'),
  ];
  for (const p of candidates) {
    try { if (fs.existsSync(p)) return p; } catch (_) {}
  }
  return candidates[0];
}

const DLL_NAME = 'AmInterface_RT_X64.dll';

// DLL 3개가 있는 폴더. 설정(AMTRAY_DLL_DIR)이 없으면 설치 폴더 helpers/windows/amtray(개발: 소스 bin) 중 DLL 이 있는 곳.
function getDllDir() {
  if (authConfig.AMTRAY_DLL_DIR) return authConfig.AMTRAY_DLL_DIR;
  const dirs = [
    path.join(process.resourcesPath || '', '..', 'helpers', 'windows', 'amtray'),
    path.join(process.resourcesPath || '', 'helpers', 'windows', 'amtray'),
    path.join(__dirname, '..', '..', 'helpers', 'windows', 'amtray', 'bin'),
  ];
  for (const d of dirs) {
    try { if (fs.existsSync(path.join(d, DLL_NAME))) return d; } catch (_) {}
  }
  return dirs[0];
}

function engine() {
  return authConfig.AMTRAY_ENGINE === 'helper' ? 'helper' : 'koffi';
}

// ---- koffi 작업 프로세스 ----
let worker = null;
let nextId = 1;
const pending = new Map(); // id → { resolve, timer, cmd }

function finishAll(res) {
  for (const [id, p] of pending) {
    clearTimeout(p.timer);
    p.resolve({ cmd: p.cmd, ...res });
    pending.delete(id);
  }
}

function getWorker() {
  if (worker) return worker;
  const w = utilityProcess.fork(path.join(__dirname, 'amTrayWorker.js'), [], { serviceName: 'AM-Tray DLL' });
  w.on('message', (msg) => {
    const p = msg && pending.get(msg.id);
    if (!p) return;
    clearTimeout(p.timer);
    pending.delete(msg.id);
    p.resolve(msg.res || { ok: false, error: 'worker_bad_output' });
  });
  w.on('exit', (code) => {
    if (worker === w) worker = null;
    // DLL 안에서 죽으면 여기로 온다(AmHelper 의 dll_crashed 와 같은 뜻)
    if (pending.size) {
      try { logger.logError('amtray_worker_exit', { code, pending: pending.size }); } catch (_) {}
      finishAll({ ok: false, error: 'worker_crashed', exitCode: code });
    }
  });
  worker = w;
  return w;
}

function dllOpts() {
  return {
    dllDir: getDllDir(),
    dllName: DLL_NAME,
    useInit: authConfig.AMTRAY_DLL_INIT,
  };
}

// ---- 11-18 시험용: 본체 프로세스에서 DLL 호출 (AMTRAY_DLL_PROCESS = 'main') ----
//   왜: AM-Tray 로그인 알림(WM_COPYDATA)이 앱 창으로 안 온다(11-17). AM-Tray 가 "Init 을 부른 프로세스의 창"으로
//       보내는 방식이라면, 창이 없는 작업 프로세스에서 Init 을 불러서 못 받는 것일 수 있다 → 창이 있는 본체에서 불러 비교.
//   ⚠️ DLL 이 죽으면 앱도 같이 죽는다(녹음 중 포함). 호출 동안 화면이 멈추고, 시간 제한(timeout)도 걸 수 없다.
//      시험이 끝나면 반드시 "" 로 되돌린다.
let mainLogged = false;
function runInMain(cmd, args) {
  if (process.platform !== 'win32') return Promise.resolve({ ok: false, error: 'not_windows' });
  if (!mainLogged) {
    mainLogged = true;
    try { logger.logWarn('amtray_dll_in_main_process', { pid: process.pid }); } catch (_) {}
  }
  const { handle } = require('./amTrayWorker');
  return Promise.resolve(handle({ cmd, args, opts: dllOpts() }));
}

function runWorker(cmd, args, timeout) {
  if (authConfig.AMTRAY_DLL_PROCESS === 'main') return runInMain(cmd, args);
  return new Promise((resolve) => {
    if (process.platform !== 'win32') return resolve({ ok: false, error: 'not_windows' });
    let w;
    try { w = getWorker(); } catch (e) {
      return resolve({ ok: false, error: 'worker_start_failed', message: String((e && e.message) || e) });
    }
    const id = nextId++;
    const timer = setTimeout(() => {
      if (!pending.has(id)) return;
      pending.delete(id);
      resolve({ ok: false, cmd, error: 'helper_timeout' });
      // DLL 호출이 멈춘 것 → 프로세스를 끝내고 다음에 새로 띄운다
      try { logger.logWarn('amtray_worker_timeout', { cmd }); } catch (_) {}
      try { w.kill(); } catch (_) {}
    }, timeout);
    pending.set(id, { resolve, timer, cmd });
    w.postMessage({
      id,
      cmd,
      args,
      opts: dllOpts(),
    });
  });
}

// cmd 하나를 지금 엔진으로 실행. args 는 koffi 용 객체, helperArgs 는 AmHelper 용 인자 배열.
function call(cmd, args, helperArgs, timeout) {
  if (engine() === 'helper') return runHelper(cmd, helperArgs, timeout);
  return runWorker(cmd, args, timeout);
}

function sid() {
  return authConfig.AMTRAY_SID || authConfig.AMTRAY_SYSTEM_ID;
}

// 설정이 갖춰졌는지. 시스템 ID 가 없으면 DLL 을 부를 수 없다.
function isConfigured() {
  return !!authConfig.AMTRAY_MOCK || !!authConfig.AMTRAY_SYSTEM_ID;
}

// AmHelper.exe 실행 → { ok, result, error, ... }. 실행 자체가 실패해도 같은 모양으로 돌려준다.
function runHelper(cmd, args, timeout) {
  return new Promise((resolve) => {
    if (process.platform !== 'win32') return resolve({ ok: false, error: 'not_windows' });
    const helperPath = getHelperPath();
    if (!fs.existsSync(helperPath)) return resolve({ ok: false, error: 'helper_not_found', path: helperPath });

    const full = [cmd, ...args];
    if (authConfig.AMTRAY_DLL_DIR) full.push('--dll-dir', authConfig.AMTRAY_DLL_DIR);

    execFile(helperPath, full, { timeout, windowsHide: true, encoding: 'utf8' }, (err, stdout) => {
      const line = String(stdout || '').trim().split(/\r?\n/).pop() || '';
      let parsed = null;
      try { parsed = JSON.parse(line); } catch (_) {}
      if (parsed && typeof parsed === 'object') return resolve(parsed);
      if (err && err.killed) return resolve({ ok: false, error: 'helper_timeout' });
      resolve({ ok: false, error: 'helper_bad_output', exitCode: err && err.code, output: line.slice(0, 200) });
    });
  });
}

// ---- 흉내(AMTRAY_MOCK) ----
// notlogin: 처음엔 미로그인 → 로그인 창 → 3초 뒤 로그인 알림(onMockLogin) → 그다음부터 토큰
let mockLoggedIn = false;
let onMockLogin = null;
function setMockLoginListener(fn) { onMockLogin = fn; }

function mockToken() {
  switch (authConfig.AMTRAY_MOCK) {
    case 'token': return 'MOCK.AUTHZ.TOKEN.0123456789';
    case 'notlogin':
    case 'uifail':
    case 'uiblock': return mockLoggedIn ? 'MOCK.AUTHZ.TOKEN.0123456789' : CODE_NOT_LOGGED_IN;
    case 'unavailable': return '509090';
    case 'denied': return '503032';
    case 'ssofail': return mockLoggedIn ? 'MOCK.AUTHZ.TOKEN.0123456789' : CODE_TOKEN_API_FAILED;
    case 'uialready': return mockUiAlreadyCalled ? 'MOCK.AUTHZ.TOKEN.0123456789' : CODE_NOT_LOGGED_IN;
    case 'amlogout':
    case 'otheruser': return 'MOCK.AUTHZ.TOKEN.0123456789';
    default: return '500001';
  }
}
let mockUiAlreadyCalled = false;

// ---- 공개 함수 ----

// 인가토큰 요청. 반환:
//   { kind: 'token', token }                  → 백엔드로 보낸다
//   { kind: 'not_logged_in', code }           → showLoginUI()
//   { kind: 'unavailable', code }             → 자체 로그인으로
//   { kind: 'error', code }                   → getReturnMessage(code)
//   { kind: 'helper_error', error, ... }      → AmHelper/DLL 문제(파일 없음·로드 실패·죽음·시간 초과)
async function getSystemToken() {
  let result;
  if (authConfig.AMTRAY_MOCK) {
    result = { ok: true, result: mockToken(), mock: true };
  } else {
    result = await call('token',
      { ssoKey: authConfig.AMTRAY_SSO_KEY, sid: sid(), systemId: authConfig.AMTRAY_SYSTEM_ID },
      ['--sso-key', authConfig.AMTRAY_SSO_KEY, '--sid', sid(), '--system-id', authConfig.AMTRAY_SYSTEM_ID],
      TIMEOUT_TOKEN_MS);
  }
  if (!result.ok) {
    try { logger.logError('amtray_token_helper_error', { ...result }); } catch (_) {}
    return { kind: 'helper_error', ...result };
  }
  const value = String(result.result || '').trim();
  // 샘플: 길이 6 이하 = 에러코드. 토큰 값 자체는 로그에 남기지 않는다.
  if (value.length > 6) {
    try { logger.logInfo('amtray_token_received', { shape: tokenShape(value), fn: result.fn, init: result.init, engine: engine(), mock: !!result.mock }); } catch (_) {}
    return { kind: 'token', token: value };
  }
  try { logger.logWarn('amtray_token_code', { code: value, step: result.step, init: result.init, version: result.version, fn: result.fn, engine: engine(), commOk: result.commOk, mock: !!result.mock }); } catch (_) {}
  if (value === CODE_NOT_LOGGED_IN || value === CODE_TOKEN_API_FAILED) return { kind: 'not_logged_in', code: value };
  if (result.step === 'init' && CODES_INIT_FAILED.includes(value)) return { kind: 'install', code: value };
  if (CODES_INSTALL.includes(value)) return { kind: 'install', code: value };
  if (CODES_UNAVAILABLE.includes(value)) return { kind: 'unavailable', code: value };
  if (CODES_DENIED.includes(value)) return { kind: 'denied', code: value };
  return { kind: 'error', code: value };
}

// AM 로그인 창 띄우기. 반환 { ok, status, code }
//   status: 'shown'(203012 — 로그인이 끝나면 윈도우 메시지가 온다) | 'already'(506021 이미 로그인 — 토큰을 다시 요청)
//           | 'retryable'(502050·502051 — [다시 시도][앱 종료]) | 'blocked'(502052·공백 — SSO 로그인 불가 → 앱 종료)
//           | 'install'(Init 실패 — 설치 안내)
//   ok:false 면 작업 프로세스·DLL 문제(error)
function classifyShowUi(result) {
  const code = String(result.code || '').trim();
  if (result.step === 'init') return CODES_INIT_FAILED.includes(code) ? 'install' : 'retryable';
  if (!result.commOk) return 'blocked';
  if (code === '203012') return 'shown';
  if (code === '506021') return 'already';
  if (code === '502052' || code === '') return 'blocked';
  return 'retryable';
}

async function showLoginUI() {
  if (authConfig.AMTRAY_MOCK) {
    const m = authConfig.AMTRAY_MOCK;
    const status = m === 'uifail' ? 'retryable' : m === 'uiblock' ? 'blocked' : m === 'uialready' ? 'already' : 'shown';
    if (m === 'uialready') mockUiAlreadyCalled = true;
    if (status === 'shown') {
      setTimeout(() => {
        mockLoggedIn = true;
        try { logger.logInfo('amtray_mock_login_message'); } catch (_) {}
        if (onMockLogin) onMockLogin();
      }, 3000);
    }
    const code = { retryable: '502051', blocked: '502052', already: '506021', shown: '203012' }[status];
    return { ok: true, status, code, mock: true };
  }
  const result = await call('show-ui', { ssoKey: authConfig.AMTRAY_SSO_KEY, sid: sid() }, ['--sid', sid()], TIMEOUT_SHOW_UI_MS);
  if (!result.ok) {
    try { logger.logWarn('amtray_show_ui', { ...result }); } catch (_) {}
    return { ok: false, error: result.error };
  }
  const status = classifyShowUi(result);
  try { logger.logInfo('amtray_show_ui', { code: result.code, step: result.step, commOk: result.commOk, status, reinit: result.reinit }); } catch (_) {}
  return { ok: true, status, code: result.code };
}

// AM-Tray 로그인 상태(토큰 요청 없이). 반환 { state: 'in' | 'out' | 'unknown', code }
//   unknown(509090 통신 실패, 502011 설정 없음, 작업 프로세스 문제 등) → 부르는 쪽은 지금 상태를 그대로 둔다.
async function isLogin() {
  if (authConfig.AMTRAY_MOCK) {
    const m = authConfig.AMTRAY_MOCK;
    const out = m === 'amlogout' || ((m === 'notlogin' || m === 'uifail') && !mockLoggedIn);
    return { state: out ? 'out' : 'in', code: out ? CODE_NOT_LOGGED_IN : '206030', mock: true };
  }
  const result = await call('is-login', { ssoKey: authConfig.AMTRAY_SSO_KEY, sid: sid() }, ['--sid', sid()], TIMEOUT_CHECK_MS);
  const code = String((result && result.code) || '').trim();
  const state = !result.ok || result.step === 'init' ? 'unknown'
    : code === '206030' ? 'in'
    : code === CODE_NOT_LOGGED_IN ? 'out'
    : 'unknown';
  const log = { code, state, step: result.step, commOk: result.commOk, error: result.error, reinit: result.reinit };
  try {
    if (code === '502011') logger.logWarn('amtray_is_login', { ...log, note: 'AM-Tray 설정 없음 — ssoKey 확인' });
    else logger.logInfo('amtray_is_login', log);
  } catch (_) {}
  return { state, code };
}

// AM-Tray 에 로그인한 사람이 userId(사번)와 같은지. 반환 { state: 'same' | 'other' | 'out' | 'unknown', code }
//   out = 506041(ID 없음)·504011(미로그인)
async function checkLoginUser(userId) {
  if (authConfig.AMTRAY_MOCK) {
    const m = authConfig.AMTRAY_MOCK;
    const state = m === 'otheruser' ? 'other' : m === 'amlogout' ? 'out' : 'same';
    return { state, code: { other: '506040', out: CODE_NOT_LOGGED_IN, same: '206040' }[state], mock: true };
  }
  if (!userId) return { state: 'unknown', code: '' };
  const result = await call('check-user', { ssoKey: authConfig.AMTRAY_SSO_KEY, sid: sid(), userId: String(userId) },
    ['--sid', sid(), '--user-id', String(userId)], TIMEOUT_CHECK_MS);
  const code = String((result && result.code) || '').trim();
  const state = !result.ok || result.step === 'init' ? 'unknown'
    : code === '206040' ? 'same'
    : code === '506040' ? 'other'
    : (code === '506041' || code === CODE_NOT_LOGGED_IN) ? 'out'
    : 'unknown';
  try { logger.logInfo('amtray_check_user', { code, state, step: result.step, commOk: result.commOk, error: result.error }); } catch (_) {}
  return { state, code };
}

// SMSESSION(웹 SSO 쿠키값) — 11-16: 쓰지 않고 **모양만** 로그에 남긴다(인가토큰과 비교용). 반환 { ok, shape?, code? }
async function logSmSessionShape() {
  if (authConfig.AMTRAY_MOCK) return { ok: false, mock: true };
  const result = await call('sm-session', { ssoKey: authConfig.AMTRAY_SSO_KEY, sid: sid() }, ['--sid', sid()], TIMEOUT_CHECK_MS);
  const log = result.ok && result.commOk && result.result
    ? { shape: tokenShape(result.result), fn: result.fn }
    : { code: result.code, step: result.step, commOk: result.commOk, error: result.error };
  try { logger.logInfo('amtray_smsession_shape', log); } catch (_) {}
  return { ok: !!log.shape, ...log };
}

// AM-Tray 설치 페이지 주소(설정 AMTRAY_INSTALL_URL — 개발/운영 묶음)
function getInstallUrl() {
  return authConfig.AMTRAY_INSTALL_URL || '';
}

// 에러코드 → AM 이 주는 안내 문구. 실패하면 빈 문자열.
async function getReturnMessage(code, locale) {
  if (authConfig.AMTRAY_MOCK) return locale === 'en' ? `(mock) AM error ${code}` : `(흉내) AM 오류 ${code}`;
  const result = await call('message', { code: String(code), locale: locale || 'ko' },
    ['--code', String(code), '--locale', locale || 'ko'], TIMEOUT_MESSAGE_MS);
  if (!result.ok) {
    try { logger.logWarn('amtray_message_failed', { code, error: result.error }); } catch (_) {}
    return '';
  }
  return String(result.result || '');
}

module.exports = {
  CODE_NOT_LOGGED_IN,
  CODES_UNAVAILABLE,
  CODES_DENIED,
  isConfigured,
  getSystemToken,
  showLoginUI,
  isLogin,
  checkLoginUser,
  logSmSessionShape,
  getInstallUrl,
  getReturnMessage,
  setMockLoginListener,
  getHelperPath,
  getDllDir,
};
