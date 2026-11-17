// 로그인 화면 체크박스 값 — "로그인 유지"
//
// - 저장 위치: userData/login-prefs.json (Windows: AppData\Roaming\timbloRecApp\login-prefs.json)
// - 내용: { keepLogin }. 토큰은 넣지 않는다(평문).
// - 처음에는 꺼져 있다. 마지막으로 고른 값을 다음 로그인 화면에 그대로 보여준다.
// - keepLogin 은 사용자의 선택일 뿐이고, 실제로 세션을 저장하는지는 SESSION_PERSIST_ENABLED 도 켜져
//   있어야 한다(sessionStore.shouldPersist).

const fs = require('fs');
const path = require('path');
const { app } = require('electron');
const logger = require('../logger');

const FILE_NAME = 'login-prefs.json';
const DEFAULTS = { keepLogin: false };
let cached = null;

function filePath() {
  return path.join(app.getPath('userData'), FILE_NAME);
}

function get() {
  if (cached) return { ...cached };
  cached = { ...DEFAULTS };
  try {
    const saved = JSON.parse(fs.readFileSync(filePath(), 'utf8')) || {};
    cached.keepLogin = saved.keepLogin === true;
  } catch (_) {}
  return { ...cached };
}

function write(next) {
  cached = next;
  try {
    fs.writeFileSync(filePath(), JSON.stringify(next), 'utf8');
  } catch (err) {
    try { logger.logWarn('login_prefs_save_failed', { message: err && err.message }); } catch (_) {}
  }
}

// 체크박스 값을 바꾼다.
function setOptions({ keepLogin } = {}) {
  const next = get();
  if (typeof keepLogin === 'boolean') next.keepLogin = keepLogin;
  write(next);
}

module.exports = { get, setOptions };
