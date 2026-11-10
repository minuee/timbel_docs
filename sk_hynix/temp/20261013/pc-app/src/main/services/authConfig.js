// 로그인/세션 관련 서버 주소와 옵션을 한곳에 모은다.
// - 회사(온프레미스)마다 값이 달라질 수 있어 코드 곳곳에 흩어두지 않는다.
// - 값은 config.js 순서로 읽는다: .env(개발) → src/config/app.config.json(운영 빌드) → 아래 기본값.
//
// ★ 회사에서 확정해야 하는 값은 ★ 표시. 확정 전에도 아래 기본값으로 코드는 동작한다.

const config = require('../config');

module.exports = {
  // ★ MyAccess(SSO) 로그인 페이지. "MyAccess 로그인" 버튼이 기본 브라우저로 이 주소를 연다.
  //   로그인이 끝나면 웹이 timbloRecApp://connect?code=..&host=.. 딥링크를 호출한다.
  SSO_LOGIN_URL: config.get(
    'SSO_LOGIN_URL',
    'https://amdev.skhynix.com/sso/m/login.jsp?TYPE=XX&REALMOID=XX&GUID=XX'
  ),

  // ★ 사번 직접 로그인(HMP) 서버. 모바일앱과 같은 서버를 쓴다.
  //   모바일 소스(api_const.dart) 기준: baseUrl 'https://aimeeting.mobile.skhynix.com/m'
  //   + 경로 '/api/auth/sso/hmp'
  HMP_BASE_URL: config.get('HMP_BASE_URL', 'https://aimeeting.mobile.skhynix.com/m'),
  HMP_LOGIN_PATH: config.get('HMP_LOGIN_PATH', '/api/auth/sso/hmp'),
  // ★ 현재 HMP API 는 body 에 empno 하나만 받는다(비밀번호 검증 없음).
  //   서버가 비밀번호를 검증하게 되면 그 필드 이름(예: 'password')을 넣는다. 비어 있으면 보내지 않는다.
  HMP_PASSWORD_FIELD: config.get('HMP_PASSWORD_FIELD', ''),
  // ★ 사번 직접 로그인 폼을 보여줄지. 비밀번호 검증이 없는 동안에는 운영 빌드에서 false 로 둘 것.
  EMPNO_LOGIN_ENABLED: config.getBool('EMPNO_LOGIN_ENABLED', true),

  // 토큰 갱신. 모바일 소스(api_service.dart tokenRefresh) 기준으로
  //   PUT /api/auth/refresh, body { token: refreshToken, fcmToken }, Authorization: Bearer {만료된 accessToken}
  //   응답 data.tokens.accessToken (refreshToken 도 내려오면 함께 교체)
  // ★ 서버 담당자가 POST 라고 하면 REFRESH_METHOD 만 'post' 로 바꾼다.
  REFRESH_PATH: config.get('REFRESH_PATH', '/api/auth/refresh'),
  REFRESH_METHOD: String(config.get('REFRESH_METHOD', 'put')).toLowerCase(),

  // accessToken 만료 이 시간(ms) 전부터 미리 갱신한다.
  // 업로드는 파일 스트림이라 401 후 재전송이 불가능해서, 보내기 전에 갱신해 두는 편이 안전하다.
  REFRESH_BEFORE_EXPIRY_MS: 60 * 1000,

  // ★ 테스트용 수동 로그인(이름·사번·accessToken 직접 입력) 폼을 보여줄지. 운영 빌드에서는 false.
  MANUAL_LOGIN_ENABLED: config.getBool('MANUAL_LOGIN_ENABLED', true),
  // 수동 로그인에서 서버 주소를 비워 두면 쓸 기본 주소(업로드·내 정보 조회가 이 서버로 간다).
  DEFAULT_API_BASE_URL: config.get('DEFAULT_API_BASE_URL', 'https://aimeeting.mobile.skhynix.com/m'),

  // 녹음 시작 시 부서장에게 안내 메일을 보낼지(apiEndpoints.alertRecording).
  ALERT_ON_RECORDING_START: config.getBool('ALERT_ON_RECORDING_START', true),

  // ★ 모바일은 'AOS' / 'IOS' 를 보낸다. PC 값은 서버와 합의 필요.
  APP_OS: config.get('APP_OS', process.platform === 'win32' ? 'WINDOWS' : 'MAC'),
};
