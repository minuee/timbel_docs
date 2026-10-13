// 앱 로그를 로그 서버(docs/logserver)로 보낸다.
// - logger.js 가 파일에 쓰는 모든 로그 중 LOG_SERVER_MIN_LEVEL 이상만 보낸다(기본 info → info/warn/error).
// - 모아서 몇 초마다 한 번에 보낸다. 로그 한 줄마다 요청을 보내면 녹음/업로드 중에 부담이 된다.
// - 서버가 죽어 있어도 앱은 그대로 동작해야 한다. 실패분은 메모리에 쌓아 두었다가 다시 보내고,
//   너무 많이 쌓이면 오래된 것부터 버린다(파일 로그에는 그대로 남아 있다).
// - 이 모듈의 실패는 logger 로 남기지 않는다. 남기면 그 로그를 또 보내려다 실패하는 고리가 생긴다.
// - 다른 API 와 같이 apiService 로 보낸다 → Authorization(Bearer)·timblo-App-* 헤더가 자동으로 붙는다.
//   서버(게이트웨이)가 토큰 없는 요청을 막아서, 로그인 전에는 보내지 않고 모아 두었다가 로그인 후 보낸다.
//   401 을 받아도 토큰 갱신·세션 종료는 하지 않는다(skipRefresh). 로그 때문에 로그아웃되면 안 된다.

const config = require('../config');

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const FLUSH_INTERVAL_MS = 3000;
const BATCH_SIZE = 100;
const MAX_QUEUE = 2000;
const MAX_BACKOFF_MS = 60 * 1000;
const MAX_STRING = 2000;
// 이름에 이게 들어간 값은 서버로 보내지 않는다.
const SECRET_KEY = /token|password|passwd|authorization|secret|cookie/i;

const enabled = config.getBool('LOG_SERVER_ENABLED', true);
const url = config.get('LOG_SERVER_URL', 'https://aimeeting.mobile.skhynix.com/m/api/pcapp/log');
const minLevel = LEVELS[String(config.get('LOG_SERVER_MIN_LEVEL', 'info')).toLowerCase()] || LEVELS.info;

const SEND_TIMEOUT_MS = 5000;
let queue = [];
let dropped = 0;
let sending = false;
let timer = null;
let backoffUntil = 0;
let backoffMs = FLUSH_INTERVAL_MS;
let failingSince = 0;
let getContext = () => ({});

function levelOf(entry) {
  const name = String(entry.level || 'info').toLowerCase();
  return LEVELS[name === 'warning' ? 'warn' : name] || LEVELS.info;
}

// 토큰·비밀번호를 지우고, 너무 긴 문자열(스택 등)은 자른다.
function sanitize(value, depth = 0) {
  if (typeof value === 'string') {
    const masked = value.replace(/Bearer\s+[A-Za-z0-9\-._~+/]+=*/g, 'Bearer ***');
    return masked.length > MAX_STRING ? `${masked.slice(0, MAX_STRING)}…(${masked.length})` : masked;
  }
  if (!value || typeof value !== 'object' || depth > 4) return value;
  if (Array.isArray(value)) return value.slice(0, 50).map((v) => sanitize(v, depth + 1));
  const out = {};
  for (const [k, v] of Object.entries(value)) out[k] = SECRET_KEY.test(k) ? '***' : sanitize(v, depth + 1);
  return out;
}

// logger.logWrite 가 파일에 쓴 직후 호출한다.
function enqueue(entry) {
  if (!enabled || !url || !entry) return;
  const level = levelOf(entry);
  if (level < minLevel) return;
  // 렌더러 console.log 는 양이 많아서 warn 이상만 보낸다.
  if (entry.channel === 'console' && level < LEVELS.warn) return;

  queue.push(sanitize({ ...getContext(), ...entry }));
  if (queue.length > MAX_QUEUE) {
    dropped += queue.length - MAX_QUEUE;
    queue = queue.slice(queue.length - MAX_QUEUE);
  }
  if (queue.length >= BATCH_SIZE) flush();
}

// 순환 require 를 피하려고 쓸 때 불러온다(apiService → authService → logger).
function api() {
  return {
    client: require('./apiService').client,
    authService: require('./authService'),
  };
}

async function flush() {
  if (sending || queue.length === 0 || Date.now() < backoffUntil) return;
  const { client, authService } = api();
  // 로그인 전(토큰 없음)에는 보내지 않는다. 큐에 그대로 두었다가 로그인 후 다음 주기에 보낸다.
  if (!authService.getAccessToken()) return;
  sending = true;
  const batch = queue.slice(0, BATCH_SIZE);
  if (dropped > 0) {
    batch.push({ ...getContext(), level: 'warn', process: 'main', message: 'log_shipper_dropped', count: dropped });
  }
  try {
    await client.post(url, { logs: batch }, {
      headers: { 'Content-Type': 'application/json' },
      timeout: SEND_TIMEOUT_MS,
      skipRefresh: true,
    });
    queue = queue.slice(Math.min(BATCH_SIZE, batch.length));
    dropped = 0;
    backoffMs = FLUSH_INTERVAL_MS;
    backoffUntil = 0;
    if (failingSince) {
      // eslint-disable-next-line no-console
      console.log(`[logShipper] 로그 서버 복구 (${Math.round((Date.now() - failingSince) / 1000)}초 만에)`);
      failingSince = 0;
    }
  } catch (err) {
    // 다음 시도까지 간격을 늘린다(3초 → 6초 → … → 최대 60초). 서버를 두드리지 않기 위함.
    backoffUntil = Date.now() + backoffMs;
    backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
    if (!failingSince) {
      failingSince = Date.now();
      // eslint-disable-next-line no-console
      console.warn('[logShipper] 로그 서버 전송 실패, 재시도 예정:', err && (err.code || err.message));
    }
  } finally {
    sending = false;
  }
}

// getContext: 모든 로그에 붙일 값(사번, 디바이스 ID 등)을 돌려주는 함수
function start(options = {}) {
  if (!enabled || !url) return;
  if (typeof options.getContext === 'function') getContext = options.getContext;
  if (timer) return;
  timer = setInterval(flush, FLUSH_INTERVAL_MS);
  // 이 타이머 때문에 앱이 안 꺼지는 일이 없게 한다.
  if (timer.unref) timer.unref();
}

// 앱 종료 직전에 남은 로그를 한 번 더 보내 본다. 기다리는 시간은 짧게.
async function flushOnQuit(timeoutMs = 2000) {
  if (!enabled || !url || queue.length === 0) return;
  backoffUntil = 0;
  await Promise.race([flush(), new Promise((resolve) => setTimeout(resolve, timeoutMs))]);
}

module.exports = { start, enqueue, flush, flushOnQuit, _sanitize: sanitize };
