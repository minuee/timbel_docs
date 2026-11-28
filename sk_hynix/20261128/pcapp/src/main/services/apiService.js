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

// PC 에 설정된 시간대(IANA 이름, 예: Asia/Seoul). 서버가 국가별 접속 환경을 구분하는 데 쓴다.
// 사용자가 녹음 중에 시간대를 바꿀 수도 있어 요청마다 읽는다. 못 읽으면 빈 값 → 헤더를 안 붙인다.
function deviceTimezone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) { return ''; }
}

// 모든 요청에 붙이는 헤더.
// ★ 11-28(인증 API 인계문서 3-2): 인증서버는 timblo-App-OS·App-Version·App-Lang·Device 4개가 **모두** 있으면
//   요청을 모바일로 판정한다(11-27 dev 서버 로그 isMobile:true, osType:ANDROID 로 확인).
//   → PC 앱은 timblo-App-OS 만 보낸다(게이트웨이 406 검사용 — AOS-WINDOWS / IOS-MAC). 나머지 3개는 뺀다.
function appHeaders() {
  const headers = {
    'timblo-App-OS': authConfig.APP_OS,
  };
  const tz = deviceTimezone();
  if (tz) headers['x-device-timezone'] = tz;
  return headers;
}

// 모바일앱과 같은 4개 헤더. 모바일 API(HMP 약관 확인 — 로그인 유지 복원·테스트 로그인 뒤)를 부를 때만 쓴다.
// timblo-Device 는 모바일에서도 "기기 모델명"(예: SM-S918N)이지 고유 ID 가 아니다.
function mobileAppHeaders() {
  return {
    ...appHeaders(),
    'timblo-App-Version': app.getVersion(),
    'timblo-App-Lang': (app.getLocale() || 'ko').split('-')[0],
    'timblo-Device': `${os.type()} ${os.release()}`,
  };
}

// 토큰 헤더 — 예전 방식(Authorization: Bearer)과 인계문서 방식(X-Timblo-Token, Bearer 없이)을 함께 보낸다(11-28).
function tokenHeaders(token) {
  return { Authorization: `Bearer ${token}`, 'X-Timblo-Token': token };
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
      Object.assign(config.headers, tokenHeaders(token));
    }
  }

  return config;
});

// 401 → refreshToken 으로 갱신 후 1회만 재시도.
// 갱신이 거절되면 AM-Tray 로 조용히 다시 로그인을 한 번 해 보고(authService.tryReauth, 11-28),
// 그것도 안 되면 세션을 버리고(authService 가 'expired' 를 알림) 원래 오류를 그대로 돌려준다.
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

    let refreshed = alreadyRefreshed ? { success: true } : await authService.refreshAccessToken();
    if (!refreshed.success) {
      // 네트워크 오류는 토큰 탓이 아니므로 세션을 유지한다. 거절/갱신수단 없음일 때만:
      if (refreshed.error === 'network_error') throw error;
      // 529·530·531 등 갱신 거절 → AM-Tray 로 다시 로그인 한 번(인계문서 7-2). 안 되면 세션을 버린다.
      refreshed = await authService.tryReauth(refreshed);
      if (!refreshed.success) {
        authService.expireSession(refreshed.error);
        throw error;
      }
    }

    // 스트림 본문은 재전송할 수 없다. 갱신은 됐으니 사용자가 재시도하면 성공한다.
    if (!isReplayable(config)) throw error;

    config._retried = true;
    return client.request(config);
  }
);

module.exports = { client, deviceTimezone, mobileAppHeaders, tokenHeaders };
