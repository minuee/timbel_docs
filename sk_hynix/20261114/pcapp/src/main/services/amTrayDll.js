// AM-Tray 인터페이스 DLL 직접 호출 (koffi)
// - 이 파일은 DLL 을 "부르기만" 한다. 결과 해석(토큰/미로그인/에러)은 amTrayService.js 가 한다.
// - 앱에서는 amTrayWorker.js(utilityProcess, 별도 프로세스)가 이 파일을 쓴다 → DLL 이 죽어도 앱은 안 죽는다.
// - 회사 PC 시험: node scripts/amtray-koffi-test.js (앱 없이 이 파일만 쓴다)
// - koffi 는 npm 설치가 아니라 src/main/vendor/koffi 에 묶어 둔 것(3.3.4, Windows x64 용 koffi.node 포함)을 쓴다.
//
// 모든 함수는 { ok, cmd, fn, ... } 또는 { ok:false, error, ... } 를 돌려준다.
//
// ============================================
// 함수 모양 — AM C++ 매뉴얼 기준 (2026-11-14 확정, 정리본: docs/sso-amtray-java/clean/AmInterface.h)
//   모든 함수: BOOL 반환 = AM-Tray 와 통신 성공 여부. 결과는 첫 인자 lpReturnCode(8바이트, 6자리 코드)로 본다.
//   char (*x)[N] 은 "N바이트 char 배열" → 입력도 N바이트 0 버퍼에 복사해 넘긴다(DLL 이 N바이트를 그대로 읽어도 안전).
//
//   BOOL Init            (char rc[8], char ssoKey[32], char sid[256], char version[32])        성공 201010
//   BOOL GetSystemToken  (char rc[8], char ssoKey[32], char version[32], char sid[256],
//                         char systemCode[32], char authzToken[4096])                         성공 203030
//   BOOL ShowSSOLoginUI  (char rc[8], char *sid)
//   BOOL GetReturnMessage(char *code, char *locale, char message[4096])
//   BOOL IsLoginIT       (char rc[8], char *sid)
//   BOOL CheckLoginUserIT(char rc[8], char *sid, char *userId)
//   [?] version: 샘플은 빈 값으로 넘김 → 입력/출력 몰라도 되게 빈 32바이트 버퍼를 넘기고, 돌아온 값을 기록한다.
//   [?] Init 을 GetSystemToken 전에 꼭 불러야 하는지 샘플에 안 보임 → 기본은 한 번 부름(useInit=false 로 끌 수 있음).
//   문자열은 char*(ANSI). 한글은 CP949 로 읽는다. _WC(wchar_t) 판은 쓰지 않는다.
//   x64 에서는 __stdcall/__cdecl 구분이 없어 호출 규약은 신경 쓰지 않아도 된다.
// ============================================

const path = require('path');
const fs = require('fs');

const DEFAULT_DLL = 'AmInterface_RT_X64.dll';

const SZ = {
  code: 8,
  ssoKey: 32,
  sid: 256,
  version: 32,
  systemCode: 32,
  token: 4096,
  message: 4096,
  userId: 256,
  locale: 32,
};

const CODE_INIT_OK = '201010';
const CODE_SUCCESS = '203030';

// 함수 이름 후보(실제 DLL 이름이 앞). 6-1 결과: GetSystemTokenIT 는 없고 GetSystemToken 이 있음.
const FN_NAMES = {
  init: ['Init'],
  token: ['GetSystemToken', 'GetSystemTokenIT'],
  showUi: ['ShowSSOLoginUI', 'ShowSSOLoingUI'],
  message: ['GetReturnMessage'],
  isLogin: ['IsLoginIT'],
  checkUser: ['CheckLoginUserIT'],
};

// 함수 원형 (이름 → koffi 선언). BOOL 은 int 로 받고 0 이 아니면 true.
const PROTO = {
  init: (n) => `int ${n}(_Inout_ char *rc, _Inout_ char *ssoKey, _Inout_ char *sid, _Inout_ char *version)`,
  token: (n) => `int ${n}(_Inout_ char *rc, _Inout_ char *ssoKey, _Inout_ char *version, _Inout_ char *sid, _Inout_ char *systemCode, _Inout_ char *authzToken)`,
  showUi: (n) => `int ${n}(_Inout_ char *rc, _Inout_ char *sid)`,
  message: (n) => `int ${n}(_Inout_ char *code, _Inout_ char *locale, _Inout_ char *message)`,
  isLogin: (n) => `int ${n}(_Inout_ char *rc, _Inout_ char *sid)`,
  checkUser: (n) => `int ${n}(_Inout_ char *rc, _Inout_ char *sid, _Inout_ char *userId)`,
};

let koffi = null;
let lib = null;
let libPath = '';
let initDone = false;
let opts = { dllDir: '', dllName: DEFAULT_DLL, utf8Result: false, useInit: true };
const fnCache = {};

function loadKoffi() {
  if (koffi) return koffi;
  koffi = require('../vendor/koffi/index.cjs');
  return koffi;
}

// 설정. 이미 DLL 을 불러온 뒤 경로가 바뀌면 다시 불러온다.
function configure(next) {
  const merged = { ...opts, ...(next || {}) };
  if (!merged.dllName) merged.dllName = DEFAULT_DLL;
  const changed = merged.dllDir !== opts.dllDir || merged.dllName !== opts.dllName;
  opts = merged;
  if (changed) {
    for (const k of Object.keys(fnCache)) delete fnCache[k];
    if (lib) { try { lib.unload(); } catch (_) {} lib = null; }
    initDone = false;
  }
}

// DLL 불러오기. 같은 폴더의 Rathon-CS_crypt_X64.dll 등 딸린 DLL 도 찾도록 SetDllDirectoryW 로 폴더를 알려 준다.
function loadDll() {
  if (lib) return null;
  if (process.platform !== 'win32' && !opts.allowNonWindows) return { ok: false, error: 'not_windows' };
  let k;
  try { k = loadKoffi(); } catch (e) {
    return { ok: false, error: 'koffi_load_failed', message: String(e && e.message || e) };
  }
  const full = path.resolve(opts.dllDir || '.', opts.dllName);
  if (!fs.existsSync(full)) return { ok: false, error: 'dll_not_found', path: full };
  if (process.platform === 'win32') {
    try {
      const kernel32 = k.load('kernel32.dll');
      const SetDllDirectoryW = kernel32.func('int __stdcall SetDllDirectoryW(const char16_t *lpPathName)');
      SetDllDirectoryW(path.dirname(full));
    } catch (_) {}
  }
  try {
    lib = k.load(full);
    libPath = full;
  } catch (e) {
    return { ok: false, error: 'dll_load_failed', path: full, message: String(e && e.message || e) };
  }
  return null;
}

// 이름 후보 중 DLL 에 있는 것으로 함수를 만든다. 없으면 null.
function findFn(key) {
  if (fnCache[key]) return fnCache[key];
  for (const name of FN_NAMES[key]) {
    try {
      const fn = lib.func(PROTO[key](name));
      fnCache[key] = { fn, name };
      return fnCache[key];
    } catch (_) { /* 이 이름은 없음 → 다음 후보 */ }
  }
  return null;
}

function notFound(cmd, key) {
  return { ok: false, cmd, error: 'fn_not_found', tried: FN_NAMES[key], dll: libPath };
}

// 문자열 → size 바이트 0 버퍼 (넘치면 자르고 마지막은 NUL)
function inBuf(value, size) {
  const buf = Buffer.alloc(size);
  Buffer.from(String(value == null ? '' : value), 'latin1').copy(buf, 0, 0, size - 1);
  return buf;
}

// 출력 버퍼 → 문자열(첫 NUL 까지)
function outStr(buf) {
  const end = buf.indexOf(0);
  return bytesToString(end < 0 ? buf : buf.subarray(0, end)).trim();
}

// char* 결과는 한글 Windows 기본 코드페이지(CP949)로 본다. UTF-8 로 확인되면 utf8Result=true.
function bytesToString(buf) {
  if (opts.utf8Result) return buf.toString('utf8');
  let ascii = true;
  for (const b of buf) { if (b > 0x7f) { ascii = false; break; } }
  if (ascii) return buf.toString('latin1');
  try { return new TextDecoder('euc-kr').decode(buf); } catch (_) { return buf.toString('utf8'); }
}

const isTrue = (raw) => (Number(raw) & 0xff) !== 0;

// ---- 공개 함수 ----

// AM-Tray 초기화. 결과 code 가 201010 이면 성공. 성공하면 같은 프로세스에서는 다시 부르지 않는다.
function init({ ssoKey, sid, force } = {}) {
  if (!ssoKey) return { ok: false, cmd: 'init', error: 'missing_args', need: ['ssoKey'] };
  const err = loadDll();
  if (err) return { cmd: 'init', ...err };
  if (initDone && !force) return { ok: true, cmd: 'init', skipped: true, code: CODE_INIT_OK, commOk: true };
  const f = findFn('init');
  if (!f) return notFound('init', 'init');
  const rc = Buffer.alloc(SZ.code);
  const ver = Buffer.alloc(SZ.version);
  const raw = f.fn(rc, inBuf(ssoKey, SZ.ssoKey), inBuf(sid, SZ.sid), ver);
  const code = outStr(rc);
  const commOk = isTrue(raw);
  if (commOk && code === CODE_INIT_OK) initDone = true;
  return { ok: true, cmd: 'init', fn: f.name, commOk, code, version: outStr(ver) };
}

// 인가토큰 요청.
//   result: 203030 이면 인가토큰, 아니면 응답코드. Bool=false(통신 실패)는 명세의 "공백" → ''.
//   useInit 이면 먼저 Init 을 한 번 부르고, Init 이 201010 이 아니면 그 코드를 result 로 돌려준다.
function getSystemToken({ ssoKey, sid, systemId }) {
  if (!ssoKey || !systemId) return { ok: false, cmd: 'token', error: 'missing_args', need: ['ssoKey', 'systemId'] };
  const err = loadDll();
  if (err) return { cmd: 'token', ...err };

  let initRes = null;
  if (opts.useInit) {
    initRes = init({ ssoKey, sid });
    if (!initRes.ok) return { ...initRes, cmd: 'token', step: 'init' };
    if (!initRes.commOk || initRes.code !== CODE_INIT_OK) {
      return { ok: true, cmd: 'token', step: 'init', fn: initRes.fn, commOk: initRes.commOk,
        code: initRes.code, result: initRes.commOk ? initRes.code : '' };
    }
  }

  const f = findFn('token');
  if (!f) return notFound('token', 'token');
  const rc = Buffer.alloc(SZ.code);
  const ver = Buffer.alloc(SZ.version);
  const tok = Buffer.alloc(SZ.token);
  const raw = f.fn(rc, inBuf(ssoKey, SZ.ssoKey), ver, inBuf(sid, SZ.sid), inBuf(systemId, SZ.systemCode), tok);
  const commOk = isTrue(raw);
  const code = outStr(rc);
  const base = { ok: true, cmd: 'token', fn: f.name, commOk, code, version: outStr(ver), init: initRes ? initRes.code : 'skipped' };
  if (!commOk) return { ...base, result: '' };
  if (code === CODE_SUCCESS) return { ...base, result: outStr(tok) };
  return { ...base, result: code };
}

// AM 로그인 창 띄우기 → result: true/false (BOOL), code: 응답코드
function showLoginUI({ sid }) {
  const err = loadDll();
  if (err) return { cmd: 'show-ui', ...err };
  const f = findFn('showUi');
  if (!f) return notFound('show-ui', 'showUi');
  const rc = Buffer.alloc(SZ.code);
  const raw = f.fn(rc, inBuf(sid, SZ.sid));
  return { ok: true, cmd: 'show-ui', fn: f.name, result: isTrue(raw), code: outStr(rc) };
}

// AM-Tray 로그인 상태 확인(토큰 요청 없이) → code 로 판단 (뜻은 회사 시험으로 확인)
function isLogin({ sid }) {
  const err = loadDll();
  if (err) return { cmd: 'is-login', ...err };
  const f = findFn('isLogin');
  if (!f) return notFound('is-login', 'isLogin');
  const rc = Buffer.alloc(SZ.code);
  const raw = f.fn(rc, inBuf(sid, SZ.sid));
  return { ok: true, cmd: 'is-login', fn: f.name, commOk: isTrue(raw), code: outStr(rc) };
}

// AM-Tray 로그인 사용자가 userId 와 같은지 → code 로 판단 (뜻은 회사 시험으로 확인)
function checkLoginUser({ sid, userId }) {
  if (!userId) return { ok: false, cmd: 'check-user', error: 'missing_args', need: ['userId'] };
  const err = loadDll();
  if (err) return { cmd: 'check-user', ...err };
  const f = findFn('checkUser');
  if (!f) return notFound('check-user', 'checkUser');
  const rc = Buffer.alloc(SZ.code);
  const raw = f.fn(rc, inBuf(sid, SZ.sid), inBuf(userId, SZ.userId));
  return { ok: true, cmd: 'check-user', fn: f.name, commOk: isTrue(raw), code: outStr(rc) };
}

// 응답코드 → 안내 문구
function getReturnMessage({ code, locale }) {
  if (!code) return { ok: false, cmd: 'message', error: 'missing_args', need: ['code'] };
  const err = loadDll();
  if (err) return { cmd: 'message', ...err };
  const f = findFn('message');
  if (!f) return notFound('message', 'message');
  const msg = Buffer.alloc(SZ.message);
  const raw = f.fn(inBuf(code, SZ.code), inBuf(locale || 'ko', SZ.locale), msg);
  const value = outStr(msg);
  if (!isTrue(raw) && !value) return { ok: false, cmd: 'message', fn: f.name, error: 'comm_failed' };
  return { ok: true, cmd: 'message', fn: f.name, commOk: isTrue(raw), result: value };
}

function info() {
  let version = '';
  try { version = loadKoffi().version || ''; } catch (e) { version = 'load_failed: ' + (e && e.message); }
  return { ok: true, cmd: 'version', result: { koffi: version, dll: libPath || null, opts } };
}

module.exports = {
  configure, init, getSystemToken, showLoginUI, isLogin, checkLoginUser, getReturnMessage, info,
  CODE_SUCCESS, CODE_INIT_OK, DEFAULT_DLL,
};
