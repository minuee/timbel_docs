# 작업 11 (선택) — 가짜 서버로 로그인·갱신 로직 검증

**손대는 파일**: 없음. 저장소 **밖** 임시 폴더에 테스트 파일 2개만 만든다.
**저장소 안의 파일은 건드리지 않는다.**
**선행 작업**: 작업 1~4

## 왜 필요한가
토큰 만료와 갱신은 실제 서버로는 재현하기 어렵다(만료까지 기다려야 함).
가짜 서버를 띄워 아래 17가지를 1초 안에 확인한다. Electron 없이 Node 만으로 돈다.

- 사번 로그인 성공/거절/빈 값
- 401 → 갱신 → 재시도, 동시 401 일 때 갱신은 1번만
- 만료 임박 시 미리 갱신, 갱신 거절 시 세션 만료
- 업로드(스트림)는 재전송하지 않음
- 로그인 게이트 화면 전환 규칙(녹음 중에는 화면 유지 등)

## 할 일

### 11-1. 임시 폴더 만들기
저장소 밖 아무 곳에 폴더를 만든다. 예: `C:\temp\authtest` (mac: `/tmp/authtest`)

### 11-2. `stub-electron.js` 만들기
```js
// Electron 없이 테스트하기 위해 require('electron') 을 가짜 객체로 바꾼다.
const Module = require('module');
const originalLoad = Module._load;
const fakeElectron = {
  app: { getVersion: () => '1.0.0', getLocale: () => 'ko-KR', getPath: () => require('os').tmpdir(), isPackaged: false, on() {} },
  ipcMain: { handle() {}, handleOnce() {} },
  shell: { openExternal: async () => {} },
};
Module._load = function (request, ...rest) {
  return request === 'electron' ? fakeElectron : originalLoad.call(this, request, ...rest);
};
```

### 11-3. `mock-test.js` 만들기
```js
// 로그인/세션 로직 검증용 가짜 서버 테스트 (Electron 없이 Node 로 실행)
// 실행: node -r ./stub-electron.js ./mock-test.js <저장소 경로>
const http = require('http');
const path = require('path');
const ROOT = path.resolve(process.argv[2] || '.', 'src/main');

function jwt(expSec) {
  const b = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  return `${b({ alg: 'none' })}.${b({ exp: Math.floor(Date.now() / 1000) + expSec, n: Math.random() })}.sig`;
}
const valid = new Set();
let refreshAllowed = true;
const calls = { refresh: 0, prot: 0 };
let lastHeaders = {};

const srv = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    const send = (o, st = 200) => { res.writeHead(st, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)); };
    const auth = (req.headers.authorization || '').replace('Bearer ', '');
    if (req.url === '/m/api/auth/sso/hmp' && req.method === 'POST') {
      lastHeaders = req.headers;
      const { empno } = JSON.parse(body || '{}');
      if (empno !== '12345') return send({ httpCode: 422, message: '약관 동의가 필요합니다.' });
      const a = jwt(3600); valid.add(a);
      return send({ httpCode: 200, message: 'Success', data: { is2FA: false, tokens: { accessToken: a, refreshToken: 'r1' } } });
    }
    if (req.url === '/m/api/auth/refresh' && req.method === 'PUT') {
      calls.refresh++;
      const { token } = JSON.parse(body || '{}');
      if (!refreshAllowed || token !== 'r1') return send({ httpCode: 530, message: 'expired' }, 401);
      const a = jwt(3600); valid.add(a);
      return send({ httpCode: 200, message: 'Success', data: { tokens: { accessToken: a } } });
    }
    if (req.url === '/m/api/protected') {
      calls.prot++;
      if (!valid.has(auth)) return send({ httpCode: 401 }, 401);
      return send({ httpCode: 200, ok: true });
    }
    send({}, 404);
  });
});

let failed = 0;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) failed++; };

(async () => {
  await new Promise((r) => srv.listen(0, r));
  process.env.HMP_BASE_URL = `http://127.0.0.1:${srv.address().port}/m`;
  const authService = require(ROOT + '/services/authService');
  const { client } = require(ROOT + '/services/apiService');
  let expired = 0;
  authService.onSessionExpired(() => expired++);

  // --- 사번 로그인 ---
  let r = await authService.loginWithEmpno('99999');
  ok(!r.success && r.httpCode === 422 && r.message === '약관 동의가 필요합니다.', '거절 시 서버 메시지 전달');
  r = await authService.loginWithEmpno('  ');
  ok(r.error === 'empno_required', '빈 사번 차단');
  r = await authService.loginWithEmpno('12345', 'pw');
  ok(r.success && authService.isAuthenticated(), '사번 로그인 성공');
  ok(!!(lastHeaders['timblo-app-os'] && lastHeaders['timblo-app-version'] && lastHeaders['timblo-device']), '앱 식별 헤더 전송');

  // --- 갱신 ---
  let res = await client.get('/api/protected');
  ok(res.data.ok && calls.refresh === 0, '유효 토큰으로 정상 호출');
  valid.clear(); // 서버가 토큰을 무효화
  const rs = await Promise.all([client.get('/api/protected'), client.get('/api/protected'), client.get('/api/protected')]);
  ok(rs.every((x) => x.data.ok), '동시 401 → 갱신 후 모두 재시도 성공');
  ok(calls.refresh === 1, `갱신 요청은 1번만 (실제 ${calls.refresh}번)`);

  authService.setSession({ accessToken: jwt(10) });
  valid.add(authService.getAccessToken());
  const before = calls.refresh;
  await client.get('/api/protected');
  ok(calls.refresh === before + 1, '만료 60초 이내면 미리 갱신');

  valid.clear(); refreshAllowed = false;
  try { await client.get('/api/protected'); ok(false, '401 이 올라와야 함'); }
  catch (e) { ok(e.response && e.response.status === 401, '갱신 거절 시 401 전달'); }
  ok(expired === 1 && !authService.isAuthenticated(), '갱신 거절 시 세션 만료 처리');

  await authService.loginWithEmpno('12345'); refreshAllowed = true; valid.clear();
  const { Readable } = require('stream');
  const before2 = calls.prot;
  try { await client.post('/api/protected', Readable.from(['x'])); ok(false, '401 이 올라와야 함'); }
  catch (e) { ok(e.response.status === 401 && calls.prot === before2 + 1, '스트림(업로드) 본문은 재전송 안 함'); }
  ok(authService.isAuthenticated(), '갱신은 성공했으므로 세션 유지');

  // --- 로그인 게이트 화면 전환 ---
  authService.clearSession();
  const gate = require(ROOT + '/ipc/handleAuth');
  let url = ''; const loads = [];
  const win = { isDestroyed: () => false, loadFile: (p) => { loads.push(p.replace(/\\/g, '/').split('/src/')[1]); url = 'file:///' + p.replace(/\\/g, '/'); }, webContents: { getURL: () => url } };
  gate.registerAuthIpc({ getMainWindow: () => win });
  gate.loadHome();
  ok(loads.pop() === 'renderer/pages/login.html', '세션 없음 → 로그인 화면');
  authService.setSession({ accessToken: 'a', endpoint: 'http://x' });
  gate.onAuthenticated();
  ok(loads.pop() === 'renderer/index.html', '로그인 화면에서 로그인 성공 → 메인 화면');
  gate.onAuthenticated();
  ok(loads.length === 0, '메인 화면에서 딥링크 재수신 → 화면 유지');
  url = 'file:///x/src/renderer/pages/recordingWindow.html';
  authService.setSession({ accessToken: 'a' }); authService.expireSession('test');
  ok(loads.length === 0, '녹음 중 세션 만료 → 녹음 화면 유지');
  url = 'file:///x/src/renderer/index.html';
  authService.setSession({ accessToken: 'a' }); authService.expireSession('test');
  ok(loads.pop() === 'renderer/pages/login.html', '메인 화면에서 세션 만료 → 로그인 화면');

  srv.close();
  console.log(failed ? `\n실패 ${failed}건` : '\n전부 통과');
  process.exit(failed ? 1 : 0);
})();
```

## 실행
저장소 폴더에서 실행한다(저장소의 `node_modules` 에 있는 axios 를 쓰기 위함).
```bash
cd <저장소 경로>
node -r C:\temp\authtest\stub-electron.js C:\temp\authtest\mock-test.js .
```
마지막 줄에 `전부 통과` 가 나오면 성공. `FAIL` 줄이 있으면 그 문구를 그대로 보고한다.
