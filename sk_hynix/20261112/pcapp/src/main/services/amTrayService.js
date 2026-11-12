// AM-Tray(SSO 에이전트) 연동 — 시스템 로그인
// - AM 인터페이스 DLL 호출 방식(authConfig.AMTRAY_ENGINE):
//     'koffi'(기본)  → amTrayWorker.js(utilityProcess, 별도 프로세스)가 koffi 로 DLL 을 바로 부른다. C++ 빌드 없음.
//     'helper'       → 예전 방식. AmHelper.exe(src/helpers/windows/amtray)를 한 번씩 실행하고 stdout JSON 한 줄을 읽는다.
//   어느 쪽이든 DLL 이 죽어도 앱은 죽지 않는다(죽는 건 작업 프로세스/exe 뿐).
// - 고객사 샘플(docs/sso-amtray-java/clean/ClientSample.java) 흐름:
//     GetSystemTokenIT(ssoKey, sid, systemID)
//       길이 > 6     → 인가토큰
//       "504011"     → 미로그인 → ShowSSOLoginUI(sid): true 면 AM 로그인 창이 뜸 / false 면 SSO 웹서버 이상
//       "509090" "503035" "503034" "500003" → AM-Tray 가 처리 못 함 → 자체 로그인(사번·MyAccess)으로
//       그 밖의 6자리 → GetReturnMessage(code, locale) 로 안내 문구
// - authConfig.AMTRAY_MOCK 이 있으면 exe·DLL 없이 흉내 낸다(Mac 에서도 화면 흐름 확인 가능).

const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');
const { utilityProcess } = require('electron');
const logger = require('../logger');
const authConfig = require('./authConfig');

const CODE_NOT_LOGGED_IN = '504011';
// '' = 명세의 "공백"(AM-Tray 통신 실패, bool_out 방식에서 Bool=false 도 여기로)
const CODES_UNAVAILABLE = ['509090', '503035', '503034', '500003', ''];

const TIMEOUT_TOKEN_MS = 15 * 1000;
const TIMEOUT_SHOW_UI_MS = 30 * 1000; // 창을 띄우고 바로 돌아오는지, 로그인 끝까지 막는지 모름 → 넉넉히
const TIMEOUT_MESSAGE_MS = 5 * 1000;

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

const DLL_NAME = 'AmInterface-RT-X64.dll';

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

function runWorker(cmd, args, timeout) {
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
      opts: {
        dllDir: getDllDir(),
        dllName: DLL_NAME,
        wide: !!authConfig.AMTRAY_DLL_WIDE,
        signature: authConfig.AMTRAY_DLL_SIGNATURE,
      },
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
    if (authConfig.AMTRAY_DLL_WIDE) full.push('--wide');

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
    case 'uifail': return mockLoggedIn ? 'MOCK.AUTHZ.TOKEN.0123456789' : CODE_NOT_LOGGED_IN;
    case 'unavailable': return '509090';
    default: return '500001';
  }
}

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
    try { logger.logInfo('amtray_token_received', { length: value.length, fn: result.fn, engine: engine(), mock: !!result.mock }); } catch (_) {}
    return { kind: 'token', token: value };
  }
  try { logger.logWarn('amtray_token_code', { code: value, fn: result.fn, engine: engine(), commOk: result.commOk, mock: !!result.mock }); } catch (_) {}
  if (value === CODE_NOT_LOGGED_IN) return { kind: 'not_logged_in', code: value };
  if (CODES_UNAVAILABLE.includes(value)) return { kind: 'unavailable', code: value };
  return { kind: 'error', code: value };
}

// AM 로그인 창 띄우기. true 면 창이 떴다(로그인이 끝나면 윈도우 메시지가 온다), false 면 SSO 웹서버 이상.
async function showLoginUI() {
  if (authConfig.AMTRAY_MOCK) {
    const ok = authConfig.AMTRAY_MOCK !== 'uifail';
    if (ok) {
      setTimeout(() => {
        mockLoggedIn = true;
        try { logger.logInfo('amtray_mock_login_message'); } catch (_) {}
        if (onMockLogin) onMockLogin();
      }, 3000);
    }
    return { ok: true, shown: ok, mock: true };
  }
  const result = await call('show-ui', { sid: sid() }, ['--sid', sid()], TIMEOUT_SHOW_UI_MS);
  try { logger.logInfo('amtray_show_ui', { ...result }); } catch (_) {}
  if (!result.ok) return { ok: false, error: result.error };
  return { ok: true, shown: result.result === true };
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
  isConfigured,
  getSystemToken,
  showLoginUI,
  getReturnMessage,
  setMockLoginListener,
  getHelperPath,
  getDllDir,
};
