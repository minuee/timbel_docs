// 녹음 파일 저장 위치(Windows)
// - 1순위: C:\Users\<사용자>\Documents\<APP_DISPLAY_NAME>
// - 2순위: C:\<APP_DISPLAY_NAME>  (문서 경로를 못 얻거나, 그 안에 폴더를 만들고 파일을 쓸 수 없을 때)
// APP_DISPLAY_NAME 은 src/config/app.config.json (기본 SKHynixRecApp)
// 이 폴더 아래에 헬퍼가 recordings/{sessionId}/{sessionId}_N.pcm 을 만든다.
//
// 헬퍼도 이 폴더를 작업 폴더(cwd)로 실행한다(audioHelperManager).
// 헬퍼가 set_output_dir 을 반영하지 못하고 기본값 "recordings"(상대경로)로 저장해도
// 결국 같은 위치(이 폴더\recordings)에 저장되게 하기 위함이다.
// (예전에는 cwd 가 헬퍼 exe 폴더라 개발 모드에서 src/helpers/windows/recordings 에 저장되고
//  업로드는 문서 폴더를 찾다가 "filePath is not a directory" 로 실패했다)

const fs = require('fs');
const path = require('path');
const { app } = require('electron');
const logger = require('./logger');
const config = require('./config');

// 폴더 이름에 쓸 수 없는 문자( \ / : * ? " < > | )는 지운다.
const APP_FOLDER = String(config.get('APP_DISPLAY_NAME', 'SKHynixRecApp')).replace(/[\\/:*?"<>|]/g, '').trim() || 'SKHynixRecApp';
const FALLBACK_BASE = `C:\\${APP_FOLDER}`;

let cachedBase = null;

// 폴더를 만들고 실제로 파일을 써 본다. (Windows 는 accessSync(W_OK) 로는 쓰기 권한을 알 수 없다)
function ensureWritable(dir) {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const probe = path.join(dir, `.write-test-${process.pid}`);
    fs.writeFileSync(probe, '');
    fs.unlinkSync(probe);
    return null;
  } catch (err) {
    return (err && (err.code || err.message)) || 'unknown_error';
  }
}

function getRecordingBase() {
  if (cachedBase) return cachedBase;

  let documentsDir = '';
  try { documentsDir = app.getPath('documents') || ''; } catch (_) {}

  const primary = documentsDir ? path.join(documentsDir, APP_FOLDER) : '';
  const primaryError = primary ? ensureWritable(primary) : 'documents_path_empty';
  if (!primaryError) {
    cachedBase = primary;
    try { logger.logInfo('recording_base_selected', { base: cachedBase, fallback: false }); } catch (_) {}
    return cachedBase;
  }

  const fallbackError = ensureWritable(FALLBACK_BASE);
  // 둘 다 안 되면 그래도 2순위를 쓴다. 녹음 저장 실패는 헬퍼가 DISK_WRITE_OPEN_FAILED 로 알린다.
  cachedBase = FALLBACK_BASE;
  try {
    logger[fallbackError ? 'logError' : 'logWarn']('recording_base_selected', {
      base: cachedBase,
      fallback: true,
      primary: primary || null,
      primaryError,
      fallbackError,
    });
  } catch (_) {}
  return cachedBase;
}

// 녹음 삭제 전 확인: 녹음 폴더(…\recordings) "아래"의 폴더/파일만 지워도 된다.
// recordings 폴더 자체나 그 밖의 경로가 들어오면 false (경로가 잘못 조립되면 다른 녹음까지 지워지는 것을 막는다).
// 예전 저장 위치(문서\timbloRecApp, 헬퍼 exe 폴더)에 남은 녹음도 정리할 수 있게 허용한다.
function recordingRoots(extraRoots) {
  const roots = [];
  try {
    if (process.platform === 'win32') {
      roots.push(path.join(getRecordingBase(), 'recordings'));
      try { roots.push(path.join(app.getPath('documents'), 'timbloRecApp', 'recordings')); } catch (_) {}
    } else if (process.platform === 'darwin') {
      roots.push(path.join('/tmp', 'recordings'));
    }
  } catch (_) {}
  for (const r of extraRoots || []) if (r) roots.push(r);
  return roots;
}

function isSafeRecordingTarget(target, extraRoots) {
  if (!target || typeof target !== 'string') return false;
  if (!path.isAbsolute(target)) return false;
  const norm = (p) => {
    const r = path.resolve(p);
    return process.platform === 'win32' ? r.toLowerCase() : r;
  };
  const t = norm(target);
  return recordingRoots(extraRoots).some((root) => {
    const rel = path.relative(norm(root), t);
    return !!rel && !rel.startsWith('..') && !path.isAbsolute(rel);
  });
}

module.exports = { getRecordingBase, isSafeRecordingTarget };
