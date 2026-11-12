// AM-Tray 인터페이스 DLL 직접 호출 (koffi) — AmHelper.exe(C++) 대신
// - 이 파일은 DLL 을 "부르기만" 한다. 결과 해석(토큰/미로그인/에러)은 amTrayService.js 가 한다.
// - 앱에서는 amTrayWorker.js(utilityProcess, 별도 프로세스)가 이 파일을 쓴다 → DLL 이 죽어도 앱은 안 죽는다.
// - 회사 PC 시험: node scripts/amtray-koffi-test.js (앱 없이 이 파일만 쓴다)
// - koffi 는 npm 설치가 아니라 src/main/vendor/koffi 에 묶어 둔 것(3.3.4, Windows x64 용 koffi.node 포함)을 쓴다.
//
// 모든 함수는 { ok, cmd, fn, result, ... } 또는 { ok:false, error, ... } 를 돌려준다(AmHelper.exe 출력과 같은 모양).

const path = require('path');
const fs = require('fs');

const DEFAULT_DLL = 'AmInterface-RT-X64.dll';

// ============================================
// ★ 가정 — DLL 함수 형식 (cpp 헤더를 받으면 여기만 고친다)
//   signature 'string'   : Java 선언과 같은 모양 (ver.14 가정)
//       const char* GetSystemTokenIT(const char* ssoKey, const char* sid, const char* systemID)  → 토큰 또는 6자리 코드
//   signature 'bool_out' : 명세 "Bool 반환 = 통신 성공 여부, 결과는 lpReturnCode" 에 맞춘 추측
//       BOOL GetSystemTokenIT(const char* ssoKey, const char* sid, const char* systemID, char* lpToken, char* lpReturnCode)
//       lpReturnCode == "203030" 이면 lpToken 이 인가토큰
//   ShowSSOLoginUI / SSOLogout(sid) → bool, GetReturnMessage(code, locale) → 문자열 — 두 방식 공통(Java 선언 기준)
//   문자열: 기본 char*(ANSI, 한글은 CP949 로 본다). wide=true 면 wchar_t*(UTF-16).
//   x64 에서는 __stdcall/__cdecl 구분이 없어 호출 규약은 신경 쓰지 않아도 된다.
// ============================================
const TOKEN_BUF_SIZE = 8192;
const CODE_BUF_SIZE = 64;
const CODE_SUCCESS = '203030';

// 함수 이름 후보(대소문자·오타 차이 대비 — 원본 샘플에 getSystemTokenIT / ShowSSOLoingUI 가 있었다)
const FN_NAMES = {
  token: ['GetSystemTokenIT', 'getSystemTokenIT', 'GetSystemToken'],
  showUi: ['ShowSSOLoginUI', 'ShowSSOLoingUI', 'showSSOLoginUI', 'ShowSsoLoginUI'],
  logout: ['SSOLogout', 'SsoLogout', 'ssoLogout'],
  message: ['GetReturnMessage', 'getReturnMessage'],
};

let koffi = null;
let lib = null;
let libPath = '';
let opts = { dllDir: '', dllName: DEFAULT_DLL, wide: false, utf8Result: false, signature: 'string' };
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
  merged.signature = String(merged.signature || 'string').toLowerCase();
  const changed = merged.dllDir !== opts.dllDir || merged.dllName !== opts.dllName
    || merged.wide !== opts.wide || merged.signature !== opts.signature;
  opts = merged;
  if (changed) {
    for (const k of Object.keys(fnCache)) delete fnCache[k];
    if (lib) { try { lib.unload(); } catch (_) {} lib = null; }
  }
}

// DLL 불러오기. 같은 폴더의 Rathon-CS-Crypt-X64.dll 등 딸린 DLL 도 찾도록 SetDllDirectoryW 로 폴더를 알려 준다.
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

const S = () => (opts.wide ? 'const char16_t *' : 'const char *');

// 이름 후보 중 DLL 에 있는 것으로 함수를 만든다. 없으면 null.
function findFn(key, makeProto) {
  if (fnCache[key]) return fnCache[key];
  const names = opts.fnOverride && opts.fnOverride[key] ? [opts.fnOverride[key]] : FN_NAMES[key];
  for (const name of names) {
    try {
      const fn = lib.func(makeProto(name));
      fnCache[key] = { fn, name };
      return fnCache[key];
    } catch (_) { /* 이 이름은 없음 → 다음 후보 */ }
  }
  return null;
}

// DLL 이 돌려준 문자열 포인터(BigInt) → JS 문자열. DLL 메모리라 해제하지 않는다.
function ptrToString(ptr) {
  if (ptr === null || ptr === undefined || ptr === 0n || ptr === 0) return null;
  const k = loadKoffi();
  if (opts.wide) return k.decode.string16(ptr);
  const bytes = [];
  for (let i = 0; i < 65536; i++) {
    const b = k.decode.uint8(ptr + BigInt(i));
    if (b === 0) break;
    bytes.push(b);
  }
  return bytesToString(Buffer.from(bytes));
}

// 출력 버퍼(Buffer) → 문자열(첫 NUL 까지)
function bufToString(buf) {
  if (opts.wide) {
    let end = 0;
    while (end + 1 < buf.length && (buf[end] || buf[end + 1])) end += 2;
    return buf.subarray(0, end).toString('utf16le');
  }
  const end = buf.indexOf(0);
  return bytesToString(end < 0 ? buf : buf.subarray(0, end));
}

// char* 결과는 한글 Windows 기본 코드페이지(CP949)로 본다. UTF-8 로 확인되면 utf8Result=true.
function bytesToString(buf) {
  if (opts.utf8Result) return buf.toString('utf8');
  let ascii = true;
  for (const b of buf) { if (b > 0x7f) { ascii = false; break; } }
  if (ascii) return buf.toString('latin1');
  try { return new TextDecoder('euc-kr').decode(buf); } catch (_) { return buf.toString('utf8'); }
}

function notFound(key) {
  return { ok: false, error: 'fn_not_found', tried: FN_NAMES[key], dll: libPath };
}

// ---- 공개 함수 ----

// 인가토큰 요청 → result: 토큰(6자리 초과) 또는 응답코드
function getSystemToken({ ssoKey, sid, systemId }) {
  if (!ssoKey || !systemId) return { ok: false, cmd: 'token', error: 'missing_args', need: ['ssoKey', 'systemId'] };
  const err = loadDll();
  if (err) return { cmd: 'token', ...err };

  if (opts.signature === 'bool_out') {
    const out = opts.wide ? 'char16_t *' : 'char *';
    const f = findFn('token', (n) => `int ${n}(${S()} ssoKey, ${S()} sid, ${S()} systemID, _Out_ ${out} lpToken, _Out_ ${out} lpReturnCode)`);
    if (!f) return { cmd: 'token', ...notFound('token') };
    const unit = opts.wide ? 2 : 1;
    const tokenBuf = Buffer.alloc(TOKEN_BUF_SIZE * unit);
    const codeBuf = Buffer.alloc(CODE_BUF_SIZE * unit);
    const raw = f.fn(ssoKey, sid || '', systemId, tokenBuf, codeBuf);
    const commOk = (raw & 0xff) !== 0;
    const code = bufToString(codeBuf).trim();
    const token = bufToString(tokenBuf).trim();
    // 통신 실패(Bool=false)는 명세의 "공백"과 같게 본다 → amTrayService 가 509090 처럼 처리
    if (!commOk) return { ok: true, cmd: 'token', fn: f.name, signature: 'bool_out', commOk, code, result: '' };
    if (code === CODE_SUCCESS) return { ok: true, cmd: 'token', fn: f.name, signature: 'bool_out', commOk, code, result: token };
    return { ok: true, cmd: 'token', fn: f.name, signature: 'bool_out', commOk, code, result: code };
  }

  const f = findFn('token', (n) => `void * ${n}(${S()} ssoKey, ${S()} sid, ${S()} systemID)`);
  if (!f) return { cmd: 'token', ...notFound('token') };
  const value = ptrToString(f.fn(ssoKey, sid || '', systemId));
  if (value === null) return { ok: false, cmd: 'token', fn: f.name, error: 'null_result' };
  return { ok: true, cmd: 'token', fn: f.name, signature: 'string', result: value };
}

// AM 로그인 창 띄우기 / 로그아웃 → result: true/false
function callSidBool(cmd, key, sid) {
  const err = loadDll();
  if (err) return { cmd, ...err };
  // bool / BOOL 둘 다 맞도록 int 로 받고 하위 1바이트만 본다
  const f = findFn(key, (n) => `int ${n}(${S()} sid)`);
  if (!f) return { cmd, ...notFound(key) };
  const raw = f.fn(sid || '');
  return { ok: true, cmd, fn: f.name, result: (raw & 0xff) !== 0, raw };
}
const showLoginUI = ({ sid }) => callSidBool('show-ui', 'showUi', sid);
const logout = ({ sid }) => callSidBool('logout', 'logout', sid);

// 응답코드 → 안내 문구
function getReturnMessage({ code, locale }) {
  if (!code) return { ok: false, cmd: 'message', error: 'missing_args', need: ['code'] };
  const err = loadDll();
  if (err) return { cmd: 'message', ...err };
  const f = findFn('message', (n) => `void * ${n}(${S()} code, ${S()} locale)`);
  if (!f) return { cmd: 'message', ...notFound('message') };
  const value = ptrToString(f.fn(String(code), locale || 'ko'));
  if (value === null) return { ok: false, cmd: 'message', fn: f.name, error: 'null_result' };
  return { ok: true, cmd: 'message', fn: f.name, result: value };
}

function info() {
  let version = '';
  try { version = loadKoffi().version || ''; } catch (e) { version = 'load_failed: ' + (e && e.message); }
  return { ok: true, cmd: 'version', result: { koffi: version, dll: libPath || null, opts } };
}

module.exports = { configure, getSystemToken, showLoginUI, logout, getReturnMessage, info, CODE_SUCCESS };
