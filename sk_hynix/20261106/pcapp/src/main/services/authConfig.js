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
  // ★ "시스템 로그인" 버튼을 보여줄지. Windows 로그온 정보를 SSO 엔진(TmTray 등)에서 받아 입력 없이 로그인하는 방식.
  //   엔진 연동 방식(매뉴얼)이 확정되기 전이라 지금은 눌러도 "준비 중"만 돌려준다(handleAuth.js auth:system-login).
  SYSTEM_LOGIN_ENABLED: config.getBool('SYSTEM_LOGIN_ENABLED', true),

  // 약관 동의 확인. 모바일과 같이 위 HMP API 에 사번을 보내 httpCode 404/422 면 미동의로 본다.
  //   사번 로그인은 로그인 응답으로 판단하고, MyAccess(SSO)·로그인 유지 복원은 로그인 뒤 한 번 더 불러 판단한다.
  //   미동의면 로그아웃하고 로그인 화면에 안내 팝업을 띄운다.
  TERMS_CHECK_ENABLED: config.getBool('TERMS_CHECK_ENABLED', true),
  // 안내 팝업의 링크. 누르면 기본 브라우저로 연다.
  TERMS_AGREE_URL: config.get('TERMS_AGREE_URL', 'https://aimeeting.skhynix.com/'),

  // AI회의록 이용 권한(MyAccess 승인) 확인. 로그인(약관 확인) 뒤에 부르고, 권한이 없으면 로그아웃 + 로그인 화면에
  //   "AI회의록을 이용할 권한이 없으십니다…" 팝업 → [확인] 누르면 앱 종료.
  // ★ 백엔드가 확인 API 를 새로 만드는 중(2026-11-06). 확정되면 ACCESS_CHECK_PATH(·METHOD)를 넣고
  //   응답 해석은 authService.js checkMinutesAccess 의 "★ 응답 해석" 부분만 맞춘다.
  //   경로가 비어 있으면(지금) 확인하지 않고 통과한다. 확인 실패(네트워크 등)도 막지 않는다.
  ACCESS_CHECK_ENABLED: config.getBool('ACCESS_CHECK_ENABLED', true),
  ACCESS_CHECK_PATH: config.get('ACCESS_CHECK_PATH', ''),
  ACCESS_CHECK_METHOD: String(config.get('ACCESS_CHECK_METHOD', 'get')).toLowerCase(),
  // 테스트용: 'denied' 면 서버를 부르지 않고 권한 없음으로, 'allowed' 면 권한 있음으로 본다. 운영은 비워 둔다.
  ACCESS_CHECK_MOCK: String(config.get('ACCESS_CHECK_MOCK', '')).toLowerCase(),

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

  // timblo-App-OS 헤더 값. 모바일은 'AOS' / 'IOS'. 게이트웨이는 AOS/IOS 포함 여부만 보므로(아니면 406)
  // PC 는 실행 OS 로 자동: 윈도우 AOS-WINDOWS, 맥 IOS-MAC, 그 외 AOS-ETC. .env / app.config.json 에 적으면 그 값 우선.
  APP_OS: config.get('APP_OS', process.platform === 'win32' ? 'AOS-WINDOWS' : process.platform === 'darwin' ? 'IOS-MAC' : 'AOS-ETC'),
};
