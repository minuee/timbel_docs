const fs = require('fs');
const path = require('path');

// 중앙 수집 로거 (메인 프로세스 전용)
// - JSON Lines 형식으로 기록
// - 일 단위 파일명: logs/combined-YYYYMMDD.log, logs/error-YYYYMMDD.log
// - 파일 당 10MB 초과 시 세그먼트 회전(.1, .2, ...)
// - 최근 7개 보존
// - pending/*.log 흡수(앱 시작 시)

const TEN_MB = 10 * 1024 * 1024;
const MAX_KEEP = 7; // 스트림별 보존 개수

let baseDirectory = null; // .../timbloRecApp/logs (Electron 제공 경로)
let logsDirectory = null; // 동일(baseDirectory)
let pendingDirectory = null; // .../logs/pending

let currentDateKey = null; // YYYYMMDD
let combinedSegmentIndex = 0;
let errorSegmentIndex = 0;

let combinedStream = null;
let errorStream = null;
let combinedBytesWritten = 0;
let errorBytesWritten = 0;

// 간단한 직렬화 큐로 파일쓰기 순서 보장
let writeQueueTail = Promise.resolve();

// 파일에 쓴 로그를 서버로도 보내는 출구(services/logShipper). main.js 가 연결한다.
let remoteSink = null;
function setRemoteSink(fn) {
  remoteSink = typeof fn === 'function' ? fn : null;
}

function formatDateKey(date = new Date()) {
  const yyyy = String(date.getFullYear());
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return `${yyyy}${mm}${dd}`;
}

function ensureDirectoryExists(dirPath) {
  try {
    fs.mkdirSync(dirPath, { recursive: true });
  } catch (_) {}
}

function getFilePrefixForKind(streamKind) {
  // 표준화: combined → combine, error → error
  return streamKind === 'combined' ? 'combine' : streamKind;
}

function buildFilePath(streamKind, dateKey, segmentIndex) {
  // streamKind: 'combined' | 'error'
  const prefix = getFilePrefixForKind(streamKind);
  const baseName = segmentIndex > 0 ? `${prefix}-${dateKey}.${segmentIndex}.log` : `${prefix}-${dateKey}.log`;
  return path.join(logsDirectory, baseName);
}

function openStreamFor(kind, dateKey, segmentIndex) {
  const filePath = buildFilePath(kind, dateKey, segmentIndex);
  ensureDirectoryExists(logsDirectory);
  const stream = fs.createWriteStream(filePath, { flags: 'a', encoding: 'utf8' });

  // 기존 파일 크기 조회하여 바이트 카운터 초기화
  let size = 0;
  try {
    const stat = fs.existsSync(filePath) ? fs.statSync(filePath) : null;
    size = stat ? stat.size : 0;
  } catch (_) {
    size = 0;
  }
  return { stream, filePath, initialSize: size };
}

function rotateIfNeeded(kind, nextChunkLength) {
  const dateKey = formatDateKey();
  const dateChanged = currentDateKey && currentDateKey !== dateKey;

  if (dateChanged) {
    // 날짜 변경 → 세그먼트 초기화 및 스트림 교체
    currentDateKey = dateKey;
    combinedSegmentIndex = 0;
    errorSegmentIndex = 0;
    try { if (combinedStream) combinedStream.end(); } catch (_) {}
    try { if (errorStream) errorStream.end(); } catch (_) {}

    // 새 날짜 스트림 열기
    const { stream: cStream, initialSize: cSize } = openStreamFor('combined', currentDateKey, combinedSegmentIndex);
    const { stream: eStream, initialSize: eSize } = openStreamFor('error', currentDateKey, errorSegmentIndex);
    combinedStream = cStream; combinedBytesWritten = cSize;
    errorStream = eStream; errorBytesWritten = eSize;
    cleanupOldFiles('combined');
    cleanupOldFiles('error');
    return;
  }

  // 용량 회전: 다음 쓰기 전 바이트 검사
  if (kind === 'combined') {
    if (combinedBytesWritten + nextChunkLength > TEN_MB) {
      combinedSegmentIndex += 1;
      try { if (combinedStream) combinedStream.end(); } catch (_) {}
      const { stream, initialSize } = openStreamFor('combined', currentDateKey, combinedSegmentIndex);
      combinedStream = stream; combinedBytesWritten = initialSize;
      cleanupOldFiles('combined');
    }
  } else if (kind === 'error') {
    if (errorBytesWritten + nextChunkLength > TEN_MB) {
      errorSegmentIndex += 1;
      try { if (errorStream) errorStream.end(); } catch (_) {}
      const { stream, initialSize } = openStreamFor('error', currentDateKey, errorSegmentIndex);
      errorStream = stream; errorBytesWritten = initialSize;
      cleanupOldFiles('error');
    }
  }
}

function cleanupOldFiles(streamKind) {
  try {
    const prefix = getFilePrefixForKind(streamKind);
    const files = fs.readdirSync(logsDirectory)
      .filter((f) => f.startsWith(`${prefix}-`) && f.endsWith('.log'))
      .map((name) => ({ name, full: path.join(logsDirectory, name) }))
      .sort((a, b) => a.name.localeCompare(b.name)); // 이름 기준 정렬(YYYYMMDD + 세그먼트)

    const over = Math.max(0, files.length - MAX_KEEP);
    for (let i = 0; i < over; i += 1) {
      try { fs.unlinkSync(files[i].full); } catch (_) {}
    }
  } catch (_) {}
}

function appendLineToStream(kind, line) {
  const chunkLength = Buffer.byteLength(line, 'utf8');
  rotateIfNeeded(kind, chunkLength);

  if (kind === 'combined') {
    combinedStream.write(line);
    combinedBytesWritten += chunkLength;
  } else {
    errorStream.write(line);
    errorBytesWritten += chunkLength;
  }
}

async function ingestPendingToCentral() {
  try {
    ensureDirectoryExists(pendingDirectory);
    const items = fs.readdirSync(pendingDirectory)
      .filter((n) => n.toLowerCase().endsWith('.log'))
      .map((name) => {
        const full = path.join(pendingDirectory, name);
        let mtime = 0;
        try { mtime = fs.statSync(full).mtimeMs || 0; } catch (_) {}
        return { name, full, mtime };
      })
      .sort((a, b) => a.mtime - b.mtime);

    for (const it of items) {
      try {
        const content = fs.readFileSync(it.full, 'utf8');
        const lines = content.split(/\r?\n/).filter(Boolean);
        for (const raw of lines) {
          // 가능하면 JSON 파싱하여 에러 스트림에도 반영
          try {
            const obj = JSON.parse(raw);
            const normalized = normalizePayload(obj, { source: 'pending' });
            const text = JSON.stringify(normalized) + '\n';
            appendLineToStream('combined', text);
            if (String(normalized.level || '').toLowerCase() === 'error') {
              appendLineToStream('error', text);
            }
          } catch (_) {
            // 비정상 라인은 원문 그대로 중앙 통합에만 적재
            appendLineToStream('combined', raw + '\n');
          }
        }
        // 성공 반영 시 파일 삭제
        try { fs.unlinkSync(it.full); } catch (_) {}
      } catch (_) {}
    }
  } catch (_) {}
}

function toLocalIsoString(date = new Date()) {
  // YYYY-MM-DDTHH:mm:ss.sss+HH:mm (로컬 타임존 오프셋 포함)
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  const yyyy = date.getFullYear();
  const mm = pad(date.getMonth() + 1);
  const dd = pad(date.getDate());
  const hh = pad(date.getHours());
  const mi = pad(date.getMinutes());
  const ss = pad(date.getSeconds());
  const ms = pad(date.getMilliseconds(), 3);
  const tzMin = -date.getTimezoneOffset();
  const sign = tzMin >= 0 ? '+' : '-';
  const tzH = pad(Math.trunc(Math.abs(tzMin) / 60));
  const tzM = pad(Math.abs(tzMin) % 60);
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}.${ms}${sign}${tzH}:${tzM}`;
}

function normalizePayload(payload, extra) {
  const nowIso = toLocalIsoString();
  const obj = payload && typeof payload === 'object' ? { ...payload } : { message: String(payload) };
  if (!obj.timestamp) obj.timestamp = nowIso;
  if (!obj.level) obj.level = 'info';
  if (!obj.process) obj.process = 'renderer';
  if (!obj.pid) obj.pid = process.pid;
  if (!obj.platform) obj.platform = process.platform;
  if (!obj.version) {
    try { obj.version = require('../../package.json').version; } catch (_) {}
  }
  if (extra && typeof extra === 'object') {
    for (const [k, v] of Object.entries(extra)) {
      if (obj[k] == null) obj[k] = v;
    }
  }
  return obj;
}

function enqueueWrite(lineCombined, lineError) {
  writeQueueTail = writeQueueTail.then(() => new Promise((resolve) => {
    try {
      if (lineCombined) appendLineToStream('combined', lineCombined);
      if (lineError) appendLineToStream('error', lineError);
    } catch (_) {}
    resolve();
  }));
  return writeQueueTail;
}

async function initMainLogger(app) {
  try {
    // 경로 준비: Electron의 logs 경로를 그대로 사용
    // Windows: C:\Users\<user>\AppData\Roaming\timbloRecApp\logs
    // macOS: ~/Library/Logs/timbloRecApp
    baseDirectory = app.getPath('logs');
    logsDirectory = baseDirectory;
    pendingDirectory = path.join(logsDirectory, 'pending');
    ensureDirectoryExists(baseDirectory);
    ensureDirectoryExists(logsDirectory);
    ensureDirectoryExists(pendingDirectory);

    // 날짜 키 설정 및 스트림 오픈
    currentDateKey = formatDateKey();
    const c = openStreamFor('combined', currentDateKey, combinedSegmentIndex);
    const e = openStreamFor('error', currentDateKey, errorSegmentIndex);
    combinedStream = c.stream; combinedBytesWritten = c.initialSize;
    errorStream = e.stream; errorBytesWritten = e.initialSize;

    // 시작 시 pending 흡수
    await ingestPendingToCentral();

    // 시작 로그
    logInfo('main_logger_initialized', { baseDirectory, logsDirectory });
  } catch (err) {
    // 초기화 실패는 콘솔에만 출력(파일에 쓸 수 없음)
    // eslint-disable-next-line no-console
    console.error('Logger initialization failed:', err && err.message);
  }
}

// 외부에서 호출하는 중앙 수집 API
async function logWrite(payload) {
  try {
    const normalized = normalizePayload(payload);
    const text = JSON.stringify(normalized) + '\n';
    const isError = String(normalized.level || '').toLowerCase() === 'error';
    const lineCombined = text;
    const lineError = isError ? text : null;
    await enqueueWrite(lineCombined, lineError);
    if (remoteSink) {
      try { remoteSink(normalized); } catch (_) {}
    }
    return { success: true };
  } catch (err) {
    // 폴백: pending에 저장(메인에서조차 실패하는 상황은 드묾)
    try {
      ensureDirectoryExists(pendingDirectory);
      const fallbackName = `main-fallback-${formatDateKey()}-${process.pid}.log`;
      fs.appendFileSync(path.join(pendingDirectory, fallbackName), JSON.stringify({ error: 'log_write_failed', message: String(err && err.message) }) + '\n');
    } catch (_) {}
    return { success: false, error: err && err.message };
  }
}

// 메인 프로세스 편의 함수들
// 첫 인자(message)는 이벤트 이름이다(예: 'server_upload_failed'). 로그 서버에서 이 이름으로 찾는다.
// 상세 정보(context)에 message 키가 있으면 이벤트 이름을 덮어써 버리므로 detail 로 옮긴다.
// (예전에는 logError('server_upload_failed', { message: 'timeout' }) 이 message:'timeout' 으로만 남았다)
//
// context 는 원래 객체({ token: '...' })를 받는다. 문자열을 그대로 펼치면 {0:'a',1:'b',...} 로
// 한 글자씩 쪼개지고, 키가 숫자가 되어 로그 서버의 토큰 가리기(logShipper)도 빠져나간다.
// 그래서 객체가 아닌 값은 { value }, Error 는 { errorMessage, stack } 으로 바꿔 담는다.
function toContextObject(context) {
  if (context === undefined || context === null) return {};
  if (context instanceof Error) {
    return { errorName: context.name, errorMessage: context.message, stack: context.stack };
  }
  if (typeof context !== 'object' || Array.isArray(context)) return { value: context };
  return { ...context };
}
function buildPayload(level, message, context) {
  const ctx = toContextObject(context);
  if (Object.prototype.hasOwnProperty.call(ctx, 'message')) {
    if (ctx.detail === undefined) ctx.detail = ctx.message;
    delete ctx.message;
  }
  return { level, process: 'main', ...ctx, message };
}
function logInfo(message, context) {
  const payload = buildPayload('info', message, context);
  console.log("logInfo: ", payload);
  return logWrite(payload);
}
function logWarn(message, context) {
  const payload = buildPayload('warn', message, context);
  console.log("logWarn: ", payload);
  return logWrite(payload);
}
function logError(message, context) {
  const payload = buildPayload('error', message, context);
  console.log("logError: ", payload);
  return logWrite(payload);
}
function logDebug(message, context) {
  const payload = buildPayload('debug', message, context);
  console.log("logDebug: ", payload);
  return logWrite(payload);
}

// 사용자 동작 로그(로그인 시도, 녹음 시작/일시정지/재개 …). 로그 서버에서 category:"user_action" 으로 모아 본다.
// 렌더러 버튼 클릭은 preload 의 developerAPI.logAction → 'log-user-action' IPC 로 여기까지 온다.
function logUserAction(action, context, processName = 'main') {
  const payload = buildPayload('info', action, { ...toContextObject(context), category: 'user_action' });
  payload.process = processName;
  console.log("logUserAction: ", payload);
  return logWrite(payload);
}

// 렌더러 developerAPI.sendInfo/sendError… 용. context 에 message 가 있어도 이벤트 이름이 지워지지 않게 buildPayload 를 쓴다.
function logFromRenderer(level, message, context) {
  const payload = buildPayload(level, message, context);
  payload.process = 'renderer';
  return logWrite(payload);
}

module.exports = {
  initMainLogger,
  setRemoteSink,
  logWrite,
  logInfo,
  logWarn,
  logError,
  logDebug,
  logUserAction,
  logFromRenderer,
};
