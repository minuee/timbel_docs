// smoke_test.js — 서버가 실제로 로그를 받아 저장하는지 확인한다.
//
// build.sh 가 컨테이너 안에서 실행한다:  docker exec <컨테이너> node /tmp/smoke_test.js
// 로컬에서도 돌릴 수 있다:               BASE=http://127.0.0.1:9996 LOG_DIR=./runtime node deploy/smoke_test.js
//
// 하나라도 실패하면 종료코드 1 → build.sh 가 tar 를 만들지 않는다.

'use strict';

const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE || `http://127.0.0.1:${process.env.PORT || 9996}`;
const LOG_DIR = process.env.LOG_DIR || '/var/lib/pcapp-log';
const FILE_ENABLED = (process.env.LOG_FILE_ENABLED || '1') !== '0';
const marker = `smoke_${Date.now()}`;

let failed = 0;
function check(ok, name, detail) {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${!ok && detail ? ` — ${detail}` : ''}`);
  if (!ok) failed++;
}

async function post(urlPath, body, raw) {
  const res = await fetch(BASE + urlPath, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: raw ? body : JSON.stringify(body),
  });
  return { status: res.status, body: await res.json().catch(() => ({})) };
}

(async () => {
  const health = await fetch(`${BASE}/health`).then((r) => r.json()).catch((e) => ({ error: e.message }));
  check(health.status === 'ok', '/health', JSON.stringify(health));

  // PC 앱 형식 — nginx 가 /m/api 를 떼지 않고 넘겨도 받아야 한다
  let r = await post('/m/api/pcapp/log', {
    logs: [
      { level: 'info', process: 'main', message: `${marker}_batch1`, empno: 'X0000001', timestamp: new Date().toISOString() },
      { level: 'error', process: 'main', message: `${marker}_batch2`, empno: 'X0000001', detail: { code: 'E1' } },
    ],
  });
  check(r.status === 200 && r.body.received === 2, 'POST /m/api/pcapp/log (logs 배열)', JSON.stringify(r));

  // 모바일 형식 — nginx 가 /m/api 를 떼고 넘기는 경우
  r = await post('/pcapp/log', { msg: `${marker}_msg` });
  check(r.status === 200 && r.body.received === 1, 'POST /pcapp/log (msg 한 줄)', JSON.stringify(r));

  r = await post('/pcapp/log', '{not json', true);
  check(r.status === 400, '깨진 JSON → 400', JSON.stringify(r));

  r = await post('/pcapp/log', { foo: 1 });
  check(r.status === 400, '빈 요청 → 400', JSON.stringify(r));

  r = await post('/pcapp/log', { logs: Array.from({ length: 501 }, () => ({ message: 'x' })) });
  check(r.status === 413, '항목 501개 → 413', JSON.stringify(r));

  const notFound = await fetch(`${BASE}/nope`).then((x) => x.status);
  check(notFound === 404, '없는 경로 → 404');

  if (FILE_ENABLED) {
    // 파일 스트림이 디스크에 반영될 시간을 준다
    await new Promise((resolve) => setTimeout(resolve, 300));
    const files = fs.readdirSync(LOG_DIR).filter((n) => /^pcapp-\d{4}-\d{2}-\d{2}\.log$/.test(n));
    const text = files.map((n) => fs.readFileSync(path.join(LOG_DIR, n), 'utf8')).join('');
    check(files.length > 0, `날짜별 파일 생성 (${files.join(', ') || '없음'})`);
    const lines = text.split('\n').filter((l) => l.includes(marker));
    check(lines.length === 3, `파일에 3줄 저장 (실제 ${lines.length}줄)`);
    const rec = lines.map((l) => JSON.parse(l)).find((o) => o.message === `${marker}_batch2`);
    check(rec && rec.level === 'error' && rec.empno === 'X0000001' && rec.source === 'pcapp', '저장 형식 (level/empno/source)', JSON.stringify(rec));
  }

  console.log(failed ? `\n실패 ${failed}건` : '\n전부 통과');
  process.exit(failed ? 1 : 0);
})().catch((err) => {
  console.error('FAIL 실행 오류 —', err.message);
  process.exit(1);
});
