// 자동 업데이트 (Windows 전용, 강제)
//
// 흐름
//   앱 실행 → UPDATE_SERVER_URL 의 latest.yml 로 버전 확인
//     ├─ 최신이거나 확인 실패 → 아무것도 안 함(그대로 로그인 화면 사용)
//     └─ 새 버전 있음 → 메인 창을 "업데이트 중" 화면으로 바꾸고 다운로드
//          └─ 다운로드 완료 → 조용히 설치(필요하면 Windows 가 관리자 권한 창을 띄움) → 앱 자동 재실행
//
// 업데이트 서버는 파일만 올려 두는 폴더면 된다(electron-updater generic provider).
//   npm run build 결과물 중 아래 3개를 UPDATE_SERVER_URL 폴더에 올린다.
//     latest.yml / timbloRecApp Setup <버전>.exe / timbloRecApp Setup <버전>.exe.blockmap
//
// 확인은 앱을 켤 때 한 번만 한다. 녹음 중에 업데이트가 끼어들 일이 없다.
// 업데이트 서버 장애로 녹음을 못 하는 일이 없도록, 실패는 전부 "업데이트 건너뜀"으로 처리한다.

const path = require('path');
const { app } = require('electron');
const config = require('../config');
const logger = require('../logger');

const ENABLED = config.getBool('UPDATE_ENABLED', true);
const SERVER_URL = String(config.get('UPDATE_SERVER_URL', '')).trim();
const CHECK_TIMEOUT_MS = 15 * 1000;
const UPDATE_PAGE = path.join(__dirname, '../../renderer/pages/update.html');

function log(level, message, context) {
  try { logger[level](message, context); } catch (_) {}
}

function currentUrl(win) {
  try { return win.webContents.getURL() || ''; } catch (_) { return ''; }
}

// 로그인 화면이나 마이크 테스트 화면일 때만 업데이트 화면으로 바꾼다(녹음 화면은 건드리지 않는다).
function canTakeOver(win) {
  const url = currentUrl(win);
  return url === '' || url.endsWith('/pages/login.html') || url.endsWith('/renderer/index.html');
}

function sendStatus(win, status) {
  try { if (win && !win.isDestroyed()) win.webContents.send('update-status', status); } catch (_) {}
}

// '1.2.10' > '1.2.9' 처럼 숫자 단위로 비교한다. 서버 버전이 더 높을 때만 업데이트한다
// (서버에 옛 버전이 올라가 있어도 강제로 내려가지 않게). '-beta' 같은 꼬리는 무시한다.
function isNewer(latest, current) {
  const parse = (v) => String(v || '').split('-')[0].split('.').map((n) => parseInt(n, 10) || 0);
  const a = parse(latest);
  const b = parse(current);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0);
  }
  return false;
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('update_check_timeout')), ms)),
  ]);
}

// options.getMainWindow : 메인 창을 돌려주는 함수
// options.onSkipped     : 업데이트 화면으로 바꿨다가 실패해서 돌아가야 할 때 호출(보통 loadHome)
// options.updater       : 테스트용 주입. 없으면 electron-updater 의 autoUpdater
// 반환: 'skipped' | 'no_update' | 'updating' | 'error'
async function runStartupUpdate(options = {}) {
  const { getMainWindow, onSkipped } = options;
  const isTest = !!options.updater;

  if (!isTest) {
    if (process.platform !== 'win32') return skip('not_windows');
    if (!app.isPackaged) return skip('not_packaged');
  }
  if (!ENABLED) return skip('disabled');
  if (!SERVER_URL) return skip('no_server_url');

  // npm 패키지가 아니라 소스에 묶어 둔 번들을 쓴다(망분리 PC 에서 npm install 없이 빌드하기 위함).
  // 다시 만드는 법: src/main/vendor/README.md
  const updater = options.updater || require('../vendor/electron-updater').autoUpdater;
  updater.logger = {
    info: (m) => log('logInfo', 'updater', { detail: String(m) }),
    warn: (m) => log('logWarn', 'updater', { detail: String(m) }),
    error: (m) => log('logError', 'updater', { detail: String(m) }),
    debug: () => {},
  };
  updater.setFeedURL({ provider: 'generic', url: SERVER_URL });
  updater.autoDownload = false;          // 화면을 먼저 바꾼 뒤 직접 내려받는다
  updater.autoInstallOnAppQuit = true;   // 설치 직전에 앱이 꺼져도 다음 종료 때 설치되게

  let info;
  try {
    log('logInfo', 'update_check_begin', { url: SERVER_URL, current: app.getVersion() });
    const result = await withTimeout(updater.checkForUpdates(), CHECK_TIMEOUT_MS);
    info = result && result.updateInfo;
    // electron-updater 6.3.9 는 결과에 isUpdateAvailable 을 주지 않아서 직접 비교한다.
    const available = !!info && isNewer(info.version, app.getVersion());
    if (!available) {
      log('logInfo', 'update_not_available', { current: app.getVersion(), latest: info && info.version });
      return 'no_update';
    }
  } catch (err) {
    log('logWarn', 'update_check_failed', { message: err && err.message });
    return 'error';
  }

  const win = getMainWindow && getMainWindow();
  if (!win || win.isDestroyed() || !canTakeOver(win)) {
    // 화면을 바꿀 수 없으면 강제 설치를 미루고 다음 실행 때 다시 확인한다.
    log('logWarn', 'update_deferred', { reason: 'window_busy', version: info.version });
    return 'skipped';
  }

  log('logInfo', 'update_available', { current: app.getVersion(), latest: info.version });
  await win.loadFile(UPDATE_PAGE).catch(() => {});
  sendStatus(win, { stage: 'downloading', version: info.version, percent: 0 });

  updater.on('download-progress', (p) => {
    sendStatus(win, { stage: 'downloading', version: info.version, percent: Math.floor((p && p.percent) || 0) });
  });

  try {
    await updater.downloadUpdate();
  } catch (err) {
    log('logError', 'update_download_failed', { message: err && err.message, version: info.version });
    sendStatus(win, { stage: 'failed', version: info.version });
    // 잠깐 안내를 보여준 뒤 원래 화면으로 돌려보낸다. 다음 실행 때 다시 시도한다.
    setTimeout(() => { if (onSkipped) onSkipped(); }, 3000);
    return 'error';
  }

  log('logInfo', 'update_downloaded', { version: info.version });
  sendStatus(win, { stage: 'installing', version: info.version, percent: 100 });
  // 안내 문구가 보일 시간을 준 뒤 설치.
  //   isSilent=true      : 설치 마법사 없이 조용히 설치
  //   isForceRunAfter=true: 설치가 끝나면 앱을 다시 실행
  // 모든 사용자용으로 설치된 경우 Windows 가 관리자 권한(UAC) 창을 띄운다.
  // 사용자가 UAC 를 거부하면 설치는 안 되고, 다음 실행 때 다시 시도한다.
  setTimeout(() => {
    try { updater.quitAndInstall(true, true); } catch (err) {
      log('logError', 'update_install_failed', { message: err && err.message });
    }
  }, 1500);
  return 'updating';

  function skip(reason) {
    log('logInfo', 'update_skipped', { reason });
    return 'skipped';
  }
}

module.exports = { runStartupUpdate, _isNewer: isNewer };
