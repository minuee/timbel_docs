// 로그인/세션 관련 서버 주소와 옵션을 한곳에 모은다.
// - 회사(온프레미스)마다 값이 달라질 수 있어 코드 곳곳에 흩어두지 않는다.
// - 값은 config.js 순서로 읽는다: .env(개발) → src/config/app.config.json(운영 빌드) → 아래 기본값.
//
// ★ 회사에서 확정해야 하는 값은 ★ 표시. 확정 전에도 아래 기본값으로 코드는 동작한다.

const config = require('../config');

module.exports = {
  // 모바일 서버(모바일앱과 같은 서버). baseUrl 'https://aimeeting.mobile.skhynix.com/m'
  HMP_BASE_URL: config.get('HMP_BASE_URL', 'https://aimeeting.mobile.skhynix.com/m'),
  // ★ 약관 동의 확인 전용 API 경로(authService.checkTermsAgreed) — 로그인에는 쓰지 않는다.
  //   (예전 MyAccess 딥링크 code 교환·사번 로그인은 SSO 이전 방식이라 11-17 지웠다)
  HMP_LOGIN_PATH: config.get('HMP_LOGIN_PATH', '/api/auth/sso/hmp'),
  // ★ "시스템 로그인" 버튼을 보여줄지. Windows 로그온 정보를 SSO 엔진(AM-Tray)에서 받아 입력 없이 로그인하는 방식.
  //   흐름: AM DLL(koffi) Init → GetSystemToken → 인가토큰 → 우리 백엔드(AMTRAY_LOGIN_PATH)가 검증·토큰 발급.
  //   자세히: docs/sso-amtray-java/analysis.md, 코드: services/amTrayService.js, handleAuth.js auth:system-login
  SYSTEM_LOGIN_ENABLED: config.getBool('SYSTEM_LOGIN_ENABLED', true),
  // 로그인 화면 버전. 1 = 지금 화면(사번·MyAccess·시스템 로그인 버튼) / 2 = AM-Tray 전용 화면(pages/loginV2.html)
  //   ver2: 열리면 AM-Tray 로 자동 로그인 시도 → 미로그인이면 [AM-Tray 로그인] 버튼. 테스트 로그인은 개발 빌드(APP_ENV=dev)에서만.
  LOGIN_PAGE_VERSION: Number(config.get('LOGIN_PAGE_VERSION', 1)) === 2 ? 2 : 1,
  // 개발 'dev' / 운영 'prod' (config.js — 빌드 명령 build:dev / build:prod 가 정함)
  APP_ENV: config.getAppEnv(),

  // ---- AM-Tray (시스템 로그인) ----
  // ★ SSO 환경 키. 개발 'Dev_CASSO_NF', 운영 'Prod_CASSO_NF' (11-16: _NF = AM-Tray 안내 팝업 없이 응답코드만 → 팝업은 우리 앱이 띄운다).
  //   _NF 없는 'Dev_CASSO'/'Prod_CASSO' 는 AM-Tray 가 자기 안내 팝업도 띄운다.
  AMTRAY_SSO_KEY: config.get('AMTRAY_SSO_KEY', 'Dev_CASSO'),
  // ★ AM 담당자가 우리 앱에 발급하는 시스템 ID. 비어 있으면 시스템 로그인은 "준비 중".
  AMTRAY_SYSTEM_ID: config.get('AMTRAY_SYSTEM_ID', ''),
  // sid — AM-Tray 안에서 우리 앱 세션을 구분하는 이름(우리가 정함). 비어 있으면 AMTRAY_SYSTEM_ID 를 쓴다.
  AMTRAY_SID: config.get('AMTRAY_SID', ''),
  // ★ 윈도우 메시지의 환경 식별값. 본사: 개발 31001, 운영 30001. (지금은 본사만)
  //   참고 — 우시: 개발 31011 / 운영 30011, 충칭: 개발 31021 / 운영 30021 (쓰려면 사업장 정보가 필요해 보류)
  //   로그인 알림 = WM_COPYDATA(0x004A) + wParam 이 값 / 로그아웃 알림 = WM_USER(0x0400) + 이 값.
  AMTRAY_ENV_CODE: Number(config.get('AMTRAY_ENV_CODE', 31001)),
  // DLL 부르는 방식. 'koffi'(기본) = 앱이 별도 작업 프로세스에서 바로 부름(amTrayDll.js) / 'helper' = 예전 AmHelper.exe(비교용)
  AMTRAY_ENGINE: String(config.get('AMTRAY_ENGINE', 'koffi')).toLowerCase(),
  // DLL 을 어느 프로세스에서 부를지 (11-18 시험용)
  //   ''(기본) → 별도 작업 프로세스(utilityProcess). DLL 이 죽어도 앱은 산다.
  //   'main'   → 본체(창이 있는 프로세스). AM-Tray 알림이 "Init 을 부른 프로세스의 창"으로 가는지 보려는 시험용.
  //              ⚠️ DLL 이 죽으면 앱도 같이 죽는다. 시험 뒤 "" 로 되돌릴 것.
  AMTRAY_DLL_PROCESS: String(config.get('AMTRAY_DLL_PROCESS', '')).toLowerCase() === 'main' ? 'main' : '',
  // DLL 3개가 있는 폴더. 비우면 설치 폴더 helpers/windows/amtray(개발: src/helpers/windows/amtray/bin).
  AMTRAY_DLL_DIR: config.get('AMTRAY_DLL_DIR', ''),
  // GetSystemToken 전에 Init 을 따로 부를지(기본 false). 11-16 매뉴얼: "GetSystemToken 은 Init 을 포함".
  //   (ShowSSOLoginUI·IsLoginIT·CheckLoginUserIT 앞에는 이 값과 상관없이 Init 을 부른다)
  AMTRAY_DLL_INIT: config.getBool('AMTRAY_DLL_INIT', false),
  // AM-Tray 설치 페이지(AM-Tray 없음·꺼짐 안내 팝업의 [설치 페이지로 이동]). 개발/운영 묶음에 넣는다.
  AMTRAY_INSTALL_URL: config.get('AMTRAY_INSTALL_URL', ''),
  // AM-Tray 인가토큰을 어떻게 쓰나
  //   'backend'(기본, 11-17) → 아래 AMTRAY_LOGIN_PATH(인증서버 새 API)로 보내 서버가 ValidateToken 으로 검증하고 발급한 우리 토큰을 쓴다.
  //   'direct' → 인가토큰을 그대로 accessToken 으로(11-16 시험안). ⚠️ 11-17 인증서버 소스 확인 결과 **안 된다**:
  //              서버는 Bearer 를 자기 비밀키 JWT 로만 검증한다(parserUtils.verifyToken). 비교용으로만 남김.
  AMTRAY_TOKEN_MODE: String(config.get('AMTRAY_TOKEN_MODE', 'backend')).toLowerCase() === 'direct' ? 'direct' : 'backend',
  // ★ 인증서버의 "AM 인가토큰 → 우리 토큰" API 경로. 서버에 반영되기 전이라 비어 있음 → 토큰을 받아도 "서버 준비 중".
  //   반영되면 "/api/auth/sso/amtray" (초안·요청서: docs/sso-amtray-java/backend-request/)
  AMTRAY_LOGIN_BASE_URL: config.get('AMTRAY_LOGIN_BASE_URL', ''),
  AMTRAY_LOGIN_PATH: config.get('AMTRAY_LOGIN_PATH', ''),
  // AM 로그인 창을 띄운 뒤 로그인 알림(윈도우 메시지)을 기다리는 최대 시간(ms).
  AMTRAY_LOGIN_WAIT_MS: Number(config.get('AMTRAY_LOGIN_WAIT_MS', 5 * 60 * 1000)),
  // 테스트용(운영은 비워 둔다): AmHelper·DLL 없이 결과를 흉내 낸다.
  //   token        → 토큰을 받은 것으로(이어서 백엔드 호출 — 경로가 비면 "서버 준비 중")
  //   notlogin     → 미로그인 → 로그인 창 띄움(흉내) → 3초 뒤 로그인 알림 → 토큰
  //   uifail       → 미로그인 → 로그인 창 띄우기 실패(SSO 서버 이상)
  //   unavailable  → AM-Tray 없음(509090 → 설치 페이지 안내)
  //   error        → 500001(DLL 로드 실패 → 연동 모듈 안내)
  //   denied       → 503032(접근 권한 없음 → 응답 메시지 팝업 → 앱 종료)
  //   ssofail      → 503035(토큰 발급 API 통신 실패 → AM 로그인 창 → 3초 뒤 로그인 알림)
  //   uiblock      → 미로그인 → 로그인 창 502052(SSO 로그인 불가 → 앱 종료)
  //   uialready    → 미로그인 → 로그인 창 506021(이미 로그인) → 토큰 한 번 더 → 성공
  //   amlogout     → 토큰은 되지만 IsLoginIT 가 미로그인(창 활성화·녹음 시작 전 확인 시험)
  //   otheruser    → 토큰은 되지만 CheckLoginUserIT 가 다른 사람(로그인 중 알림 시험)
  AMTRAY_MOCK: String(config.get('AMTRAY_MOCK', '')).toLowerCase(),

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
