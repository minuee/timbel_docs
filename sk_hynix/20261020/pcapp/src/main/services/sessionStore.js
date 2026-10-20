// 로그인 유지(옵션) — 세션을 암호화해서 디스크에 저장하고, 다음 실행 때 다시 읽는다.
//
// - SESSION_PERSIST_ENABLED 가 true 일 때만 동작한다. false(기본)면 저장하지 않고,
//   예전에 저장해 둔 파일이 있으면 지운다(앱을 켤 때마다 로그인).
// - 저장 위치: userData/session.dat (Windows: AppData\Roaming\timbloRecApp\session.dat)
// - Electron safeStorage 로 암호화한다. Windows 는 DPAPI 라서 같은 Windows 계정에서만 풀린다.
//   암호화를 쓸 수 없는 환경이면 저장하지 않는다(평문으로는 절대 남기지 않음).
// - refreshToken 이 있는 세션(SSO, 사번 로그인)만 저장한다. 테스트용 수동 로그인은 저장하지 않는다.
// - 토큰 값은 로그에 남기지 않는다.

const fs = require('fs');
const path = require('path');
const { app, safeStorage } = require('electron');
const logger = require('../logger');
const config = require('../config');

const FILE_NAME = 'session.dat';

function isEnabled() {
  return config.getBool('SESSION_PERSIST_ENABLED', false);
}

function filePath() {
  return path.join(app.getPath('userData'), FILE_NAME);
}

function canEncrypt() {
  try { return safeStorage.isEncryptionAvailable(); } catch (_) { return false; }
}

// data: { accessToken, refreshToken, endpoint, profile }
function save(data) {
  if (!isEnabled()) return;
  if (!data || !data.accessToken || !data.refreshToken) return;
  if (!canEncrypt()) {
    try { logger.logWarn('session_persist_unavailable', { reason: 'encryption_unavailable' }); } catch (_) {}
    return;
  }
  try {
    const encrypted = safeStorage.encryptString(JSON.stringify({ ...data, savedAt: Date.now() }));
    const target = filePath();
    const tmp = `${target}.tmp`;
    fs.writeFileSync(tmp, encrypted);
    fs.renameSync(tmp, target);
  } catch (err) {
    try { logger.logWarn('session_persist_save_failed', { message: err && err.message }); } catch (_) {}
  }
}

// 저장된 세션을 돌려준다. 없거나 못 읽으면 null(못 읽는 파일은 지운다).
function load() {
  if (!isEnabled()) {
    clear();
    return null;
  }
  const target = filePath();
  if (!fs.existsSync(target)) return null;
  if (!canEncrypt()) return null;
  try {
    const data = JSON.parse(safeStorage.decryptString(fs.readFileSync(target)));
    if (!data || !data.accessToken || !data.refreshToken || !data.endpoint) throw new Error('invalid_session_data');
    return data;
  } catch (err) {
    try { logger.logWarn('session_persist_load_failed', { message: err && err.message }); } catch (_) {}
    clear();
    return null;
  }
}

function clear() {
  try { fs.rmSync(filePath(), { force: true }); } catch (_) {}
}

module.exports = { isEnabled, save, load, clear };
