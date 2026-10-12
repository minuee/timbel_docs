# 작업 3 — API 클라이언트 교체 (공통 헤더, 사전 갱신, 401 재시도)

**손대는 파일**: `src/main/services/apiService.js` — **통째 교체**
**다른 파일은 건드리지 않는다.**
**선행 작업**: 작업 1, 2

## 왜 필요한가
모든 서버 요청은 이 파일의 `client` 를 거친다. 여기에 세 가지를 넣는다.

1. **앱 식별 헤더**: 모바일앱과 같은 `timblo-App-OS`, `timblo-App-Version`, `timblo-App-Lang`, `timblo-Device` 를 모든 요청에 붙인다.
   (`timblo-Device` 는 모바일에서도 기기 **모델명**이지 고유 ID 가 아니다. PC 는 `Windows_NT 10.0.xxxxx` 같은 값이 된다.)
2. **사전 갱신**: 토큰 만료가 60초 안으로 다가왔으면 요청을 보내기 전에 갱신한다.
   업로드는 파일을 스트림으로 보내서, 401 을 받은 뒤 같은 요청을 다시 보낼 수 없기 때문이다.
3. **401 재시도**: 401 이 오면 토큰을 갱신하고 1번만 다시 보낸다. 갱신이 거절되면 세션을 버린다.

## 할 일
`src/main/services/apiService.js` 의 **기존 내용을 전부 지우고** 아래 내용으로 바꾼다.

```js
// 서버 통신 단일 진입점
// - baseURL(endpoint)과 Authorization 헤더를 요청 시점에 자동으로 부착한다.
// - 호출부는 경로와 본문만 넘기면 되고, 토큰을 직접 다루지 않는다.
//
// 사용 예:
//   const { client } = require('./apiService');
//   await client.post('/api/contents/upload/encryption/files', form, { headers: form.getHeaders() });
//
// 옵션:
//   skipAuth: true     → Authorization 헤더를 붙이지 않는다(토큰 교환·로그인처럼 인증 전 호출).
//   skipRefresh: true  → 401 을 받아도 토큰 갱신/재시도를 하지 않는다(갱신 요청 자신).
//   baseURL            → 지정하면 authService 의 endpoint 대신 그 값을 쓴다.

const os = require('os');
const { app } = require('electron');
const axios = require('axios');
const authService = require('./authService');
const authConfig = require('./authConfig');

// 타임아웃을 두지 않는다.
// 최대 3시간 녹음분(수백 MB~GB)의 업로드가 수십 분 이어질 수 있어,
// 타임아웃을 걸면 정상 업로드가 중간에 끊긴다.
const client = axios.create();

// 모바일앱과 같은 앱 식별 헤더. 서버가 접속 기기 종류/버전을 구분하는 데 쓴다.
// timblo-Device 는 모바일에서도 "기기 모델명"(예: SM-S918N)이지 고유 ID 가 아니다.
function appHeaders() {
  return {
    'timblo-App-OS': authConfig.APP_OS,
    'timblo-App-Version': app.getVersion(),
    'timblo-App-Lang': (app.getLocale() || 'ko').split('-')[0],
    'timblo-Device': `${os.type()} ${os.release()}`,
  };
}

// 요청 본문이 스트림(FormData 업로드)이면 이미 한 번 흘려보낸 뒤라 다시 보낼 수 없다.
function isReplayable(config) {
  const data = config && config.data;
  return !(data && typeof data.pipe === 'function');
}

client.interceptors.request.use(async (config) => {
  if (!config.baseURL) {
    const endpoint = authService.getEndpoint();
    if (endpoint) config.baseURL = endpoint;
  }

  for (const [name, value] of Object.entries(appHeaders())) {
    if (config.headers && !config.headers[name]) config.headers[name] = value;
  }

  if (!config.skipAuth) {
    // 만료가 임박했으면 보내기 전에 갱신해 둔다. 업로드처럼 재전송이 안 되는 요청을 위한 것.
    try { await authService.ensureFreshToken(); } catch (_) {}
    const token = authService.getAccessToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }

  return config;
});

// 401 → refreshToken 으로 갱신 후 1회만 재시도.
// 갱신이 거절되면 세션을 버리고(authService 가 'expired' 를 알림) 원래 오류를 그대로 돌려준다.
client.interceptors.response.use(
  (res) => res,
  async (error) => {
    const config = error && error.config;
    const status = error && error.response && error.response.status;
    if (status !== 401 || !config || config.skipAuth || config.skipRefresh || config._retried) {
      throw error;
    }

    // 동시에 나간 요청들은 같은 옛 토큰으로 401 을 받는다. 그사이 다른 요청이 이미 갱신을
    // 끝냈다면 또 갱신하지 않고 새 토큰으로 재시도만 한다(refreshToken 1회용 서버 대비).
    const sentToken = String((config.headers && config.headers.Authorization) || '').replace(/^Bearer /, '');
    const currentToken = authService.getAccessToken();
    const alreadyRefreshed = !!currentToken && currentToken !== sentToken;

    const refreshed = alreadyRefreshed ? { success: true } : await authService.refreshAccessToken();
    if (!refreshed.success) {
      // 네트워크 오류는 토큰 탓이 아니므로 세션을 유지한다. 거절/갱신수단 없음일 때만 버린다.
      if (refreshed.error !== 'network_error') authService.expireSession(refreshed.error);
      throw error;
    }

    // 스트림 본문은 재전송할 수 없다. 갱신은 됐으니 사용자가 재시도하면 성공한다.
    if (!isReplayable(config)) throw error;

    config._retried = true;
    return client.request(config);
  }
);

module.exports = { client };
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/services/apiService.js','utf8')); console.log('문법OK')"
node -e "const s=require('fs').readFileSync('src/main/services/apiService.js','utf8'); console.log(s.includes('interceptors.response.use'), s.includes('timblo-App-OS'), s.includes('alreadyRefreshed'))"
```
문법OK 와 `true true true` 가 나오면 성공.
(이 파일은 `electron` 을 불러오므로 `node -e "require(...)"` 로 실행하면 오류가 난다. 문법 검사만 한다.)
