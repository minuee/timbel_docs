// pcapp-log-server — PC 녹음앱(timbloRecApp) 로그 수집 서버
//
// 하는 일
//   POST .../pcapp/log  앱이 보낸 로그를 받아
//     1) stdout 에 JSON 한 줄씩 출력   → docker logs / Dozzle 에서 실시간 조회
//     2) 날짜별 파일에 저장(선택)      → 컨테이너를 갈아끼워도 LOG_RETENTION_DAYS 동안 보관
//   GET  /health        상태 확인
//
// 외부 패키지를 쓰지 않는다(node 표준 라이브러리만). 망분리 서버에 반입하는 이미지에
// npm install 단계가 없어서 빌드 PC 에서 네트워크를 타는 곳이 베이스 이미지 하나뿐이다.
//
// 경로는 끝이 /pcapp/log 이면 모두 받는다. nginx 가 /m/api/ 를 떼고 넘기든 그대로 넘기든
// 서버 쪽을 고칠 필요가 없게 하기 위함이다.

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

const env = process.env;
const PORT = Number(env.PORT || 9996);
const HOST = env.HOST || '0.0.0.0';
const LOG_DIR = env.LOG_DIR || '/var/lib/pcapp-log';
const LOG_FILE_ENABLED = (env.LOG_FILE_ENABLED || '1') !== '0';
const LOG_RETENTION_DAYS = Number(env.LOG_RETENTION_DAYS || 90);
const LOG_TIMEZONE = env.LOG_TIMEZONE || 'Asia/Seoul';
const MAX_BODY_BYTES = Number(env.MAX_BODY_BYTES || 1024 * 1024);
const MAX_ENTRIES = Number(env.MAX_ENTRIES_PER_REQUEST || 500);
const MAX_STRING = 4000;
const SERVICE = 'pcapp-log';
const FILE_PREFIX = 'pcapp-';

let VERSION = 'dev';
try { VERSION = fs.readFileSync(path.join(__dirname, '..', 'VERSION'), 'utf8').trim() || 'dev'; } catch (_) {}

// ---------------------------------------------------------------- 시간
// 파일명과 ts 는 서버 시간대(기본 KST) 기준. alpine 에 tzdata 가 없어도 node 의 ICU 로 계산된다.
const dateFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: LOG_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
function localParts(date = new Date()) {
  const p = Object.fromEntries(dateFmt.formatToParts(date).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}:${p.second}` };
}
function nowTs() {
  const d = new Date();
  const { day, time } = localParts(d);
  return `${day} ${time}.${String(d.getMilliseconds()).padStart(3, '0')}`;
}

// ------------------------------------------------------------- 서버 자체 로그
function serverLog(level, message, extra) {
  process.stdout.write(JSON.stringify({ ts: nowTs(), level, source: 'server', message, ...(extra || {}) }) + '\n');
}

// ---------------------------------------------------------------- 파일 저장
let currentDay = null;
let fileStream = null;

function writeToFile(line) {
  if (!LOG_FILE_ENABLED) return;
  const { day } = localParts();
  if (day !== currentDay) {
    if (fileStream) fileStream.end();
    currentDay = day;
    fileStream = fs.createWriteStream(path.join(LOG_DIR, `${FILE_PREFIX}${day}.log`), { flags: 'a' });
    fileStream.on('error', (err) => {
      serverLog('error', 'log_file_write_failed', { error: err.message, dir: LOG_DIR });
      fileStream = null;
      currentDay = null;
    });
  }
  if (fileStream) fileStream.write(line);
}

// 파일명의 날짜로 판단한다(수정 시각은 복사·백업하면 바뀌므로 믿지 않는다).
function cleanupOldFiles() {
  if (!LOG_FILE_ENABLED || !(LOG_RETENTION_DAYS > 0)) return;
  const cutoff = localParts(new Date(Date.now() - LOG_RETENTION_DAYS * 86400000)).day;
  let removed = 0;
  try {
    for (const name of fs.readdirSync(LOG_DIR)) {
      const m = name.match(/^pcapp-(\d{4}-\d{2}-\d{2})\.log$/);
      if (m && m[1] < cutoff) {
        fs.unlinkSync(path.join(LOG_DIR, name));
        removed++;
      }
    }
    if (removed) serverLog('info', 'log_files_cleaned', { removed, keepDays: LOG_RETENTION_DAYS });
  } catch (err) {
    serverLog('warn', 'log_cleanup_failed', { error: err.message });
  }
}

// --------------------------------------------------------------- 로그 처리
function clip(value, depth = 0) {
  if (typeof value === 'string') return value.length > MAX_STRING ? `${value.slice(0, MAX_STRING)}…` : value;
  if (!value || typeof value !== 'object' || depth > 5) return value;
  if (Array.isArray(value)) return value.slice(0, 100).map((v) => clip(v, depth + 1));
  const out = {};
  for (const [k, v] of Object.entries(value)) out[k] = clip(v, depth + 1);
  return out;
}

// 앱이 보낸 항목 하나를 출력용 한 줄로 만든다.
// 앞쪽 키(ts, level, source, empno, userName, message)는 Dozzle 목록에서 바로 보이도록 고정 순서로 둔다.
function toRecord(entry, ip) {
  const e = entry && typeof entry === 'object' ? entry : { message: String(entry) };
  const { level, message, msg, empno, userName, timestamp, ...rest } = e;
  return {
    ts: nowTs(),
    level: String(level || 'info').toLowerCase(),
    source: 'pcapp',
    empno: empno || '',
    userName: userName || '',
    message: message || msg || '',
    clientTs: timestamp,
    ip,
    ...clip(rest),
  };
}

function handleLog(req, res, body) {
  let data;
  try {
    data = JSON.parse(body || '{}');
  } catch (_) {
    return send(res, 400, { httpCode: 400, message: 'invalid_json' });
  }

  // 두 형식을 받는다.
  //   { logs: [ {...}, ... ] }  PC 앱(logShipper)이 모아서 보내는 형식
  //   { msg: "..." }            모바일 /app/log 와 같은 한 줄 형식
  let entries;
  if (Array.isArray(data.logs)) entries = data.logs;
  else if (data.msg || data.message) entries = [data];
  else return send(res, 400, { httpCode: 400, message: 'logs_or_msg_required' });

  if (entries.length > MAX_ENTRIES) {
    return send(res, 413, { httpCode: 413, message: `too_many_entries (max ${MAX_ENTRIES})` });
  }

  const forwarded = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim();
  const ip = forwarded || req.socket.remoteAddress || '';
  let out = '';
  for (const entry of entries) out += JSON.stringify(toRecord(entry, ip)) + '\n';
  process.stdout.write(out);
  writeToFile(out);
  return send(res, 200, { httpCode: 200, message: 'Success', received: entries.length });
}

function send(res, status, obj) {
  const text = JSON.stringify(obj);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(text) });
  res.end(text);
}

// ------------------------------------------------------------------- 서버
const server = http.createServer((req, res) => {
  const urlPath = (req.url || '').split('?')[0].replace(/\/+$/, '');

  if (req.method === 'GET' && urlPath.endsWith('/health')) {
    return send(res, 200, { status: 'ok', service: SERVICE, version: VERSION });
  }

  if (req.method === 'POST' && urlPath.endsWith('/pcapp/log')) {
    const chunks = [];
    let size = 0;
    let aborted = false;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES && !aborted) {
        aborted = true;
        send(res, 413, { httpCode: 413, message: 'body_too_large' });
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (!aborted) handleLog(req, res, Buffer.concat(chunks).toString('utf8'));
    });
    req.on('error', () => {});
    return;
  }

  return send(res, 404, { httpCode: 404, message: 'not_found' });
});

function start() {
  if (LOG_FILE_ENABLED) {
    try {
      fs.mkdirSync(LOG_DIR, { recursive: true });
      // 권한 문제는 기동할 때 바로 드러나야 한다. 첫 로그가 올 때 알게 되면 이미 유실이다.
      const probe = path.join(LOG_DIR, '.write_probe');
      fs.writeFileSync(probe, '');
      fs.unlinkSync(probe);
    } catch (err) {
      serverLog('error', 'log_dir_not_writable', { dir: LOG_DIR, error: err.message });
      process.exit(1);
    }
    cleanupOldFiles();
    setInterval(cleanupOldFiles, 60 * 60 * 1000).unref();
  }

  server.listen(PORT, HOST, () => {
    serverLog('info', 'server_started', {
      version: VERSION, port: PORT, logFile: LOG_FILE_ENABLED ? LOG_DIR : 'off',
      retentionDays: LOG_RETENTION_DAYS, timezone: LOG_TIMEZONE,
    });
  });
}

function shutdown(signal) {
  serverLog('info', 'server_stopping', { signal });
  server.close(() => {
    if (fileStream) fileStream.end(() => process.exit(0));
    else process.exit(0);
  });
  setTimeout(() => process.exit(0), 5000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('uncaughtException', (err) => {
  serverLog('error', 'uncaught_exception', { error: err.message, stack: err.stack });
  process.exit(1);
});

if (require.main === module) start();

module.exports = { toRecord, cleanupOldFiles, localParts };
