// AM-Tray Interface DLL — C/C++ 함수 선언 정리본
// 근거: AM C++ 매뉴얼을 손으로 옮긴 것(../window-message.md 63행~, 2026-11-13 회사), 6-1 exports 결과(../analysis.md 146행)
// 오타는 바로잡았다. 뜻이 바뀔 수 있는 곳은 // [정리] 원본: ... , 확실하지 않은 곳은 // [?]
// 우리 앱은 이 파일을 컴파일하지 않는다. koffi 선언(src/main/services/amTrayDll.js 맨 위)의 기준 자료다.
//
// DLL (Windows, 32/64bit 각각)
//   AmInterface_RT_X64.dll        본체 — 앱이 koffi 로 부른다     (32bit: AmInterface_RT.dll)
//   Rathon-CS_crypt_X64.dll       암호화 — 같은 폴더에만 둔다       (32bit: Rathon-CS_crypt.dll)
//   RTSessionClientCSharpDll_RT.dll  C#(.NET) 앱용 — 안 쓴다
//
// 공통 규칙 (명세 "API-Tray API 설명")
//   - BOOL 반환 = AM-Tray Service 와 통신 성공/실패. 결과는 lpReturnCode(6자리 + NUL) 로 확인한다.
//   - char (*x)[N] = N바이트 char 배열을 가리키는 포인터. 호출하는 쪽이 N바이트 버퍼를 만들어 넘긴다.
//   - 문자열은 char*(ANSI). 이름 끝 _WC 판은 wchar_t 용(Init_WC, GetSystemToken_WC) — 안 쓴다.

#include <windows.h>

// 1) 초기화 — 성공 201010
BOOL Init(                                   // [정리] 원본: Inot
    char (*lpReturnCode)[8],                 // out 6자리 응답코드
    char (*strSSOKey)[32],                   // in  연동 SSO 키 (Dev_CASSO / Prod_CASSO)
    char (*strTraySID)[256],                 // in  sid — AM-Tray 안 세션 이름(우리가 정함)
    char (*strVersion)[32]);                 // [?] 연동 AM-Tray 버전 — 입력인지 출력인지 미확인(샘플은 빈 값)

// 2) 인가토큰 발급 — 성공 203030 (실제 DLL 이름. GetSystemTokenIT 는 Java 쪽 이름)
//    [?] 매뉴얼 함수원형은 옮겨 오지 않음 → 샘플 1 호출 줄로 복원. sid·systemCode 버퍼 크기는 샘플 선언이 빠짐
BOOL GetSystemToken(                         // [정리] 샘플 원본: GetSystenToken
    char (*lpReturnCode)[8],                 // out 6자리 응답코드
    char (*strSSOKey)[32],                   // in
    char (*strVersion)[32],                  // [?] Init 과 같음
    char (*strTraySID)[256],                 // in  [?] 크기 — Init 기준 256 으로 봄
    char (*strSystemCode)[32],               // in  systemID (myAccess 와 협의한 ACL 시스템 권한명) — 신청 중
    char (*lpAuthzToken)[4096]);             // out 인가토큰 → 우리 백엔드로

// 3) AM 로그인 창 띄우기 (504011 일 때)
BOOL ShowSSOLoginUI(
    char (*lpReturnCode)[8],
    char *strTraySID);

// 4) 사용자 상태 확인 — AM-Tray 에 로그인돼 있나 (토큰 요청 없이)
BOOL IsLoginIT(
    char (*lpReturnCode)[8],
    char *strTraySID);                       // [정리] 원본: char strTraySID

// 5) 사용자 확인 — AM-Tray 로그인 사용자가 strUserID 와 같은가
BOOL CheckLoginUserIT(
    char (*lpReturnCode)[8],
    char *strTraySID,                        // [정리] 원본: char strTraySID
    char *strUserID);                        // [정리] 원본: char strUserID   [?] 사번인지 AD 계정인지

// 6) 응답코드 → 안내 문구
BOOL GetReturnMessage(
    char *strReturnCode,                     // in  6자리 코드
    char *strLocale,                         // in  "ko" 등
    char (*lpMessage)[4096]);                // out 문구

// ---- 매뉴얼에는 있지만 쓰지 않는 것 ----
// SSOLogout — 진짜 DLL 에 없다(6-1). 로그아웃은 AM-Tray 메시지를 받는 쪽만 처리한다.
BOOL SSOLogout(char (*lpReturnCode)[8], char *strTraySID, char *strUserID);
// GetSmSessionToken — SMSESSION 쿠키(웹용). [?] 6-1 목록에 없음 → 16번째 함수일 수 있음
BOOL GetSmSessionToken(char (*lpSystemToken)[4096], char (*strTraySID)[32], char (*strSSOKey)[32]);
// 6-1 목록의 나머지(뜻 미확인, 안 씀): AccessSystem, CheckMenuAuthz, CheckVersion, Close, GetEncrypt, GetDecrypt,
//                                      GetReturnMessageInterface, Init_WC, GetSystemToken_WC

// ---- 샘플 1 (C++, 회사 매뉴얼 — 정리) ----
// HMODULE h = LoadLibraryA("AmInterface_RT_X64.dll");          // [?] 원본: "AmInterface_RT" (확장자 유무 헷갈림)
// GETSYSTEMTOKEN API_GetSystemToken = (GETSYSTEMTOKEN)GetProcAddress(h, "GetSystemToken");
// char szReturnCode[8] = {0,}, szSSOKey[32] = {0,}, szVersion[32] = {0,}, szSID[256] = {0,};
// char szSystemCode[32] = {0,}, szAuthzToken[4096] = {0,};
// strcpy(szSSOKey, "Prod_CASSO"); strcpy(szSID, "aimm"); strcpy(szSystemCode, "aimm");   // 예시값
// BOOL bResult = API_GetSystemToken(&szReturnCode, &szSSOKey, &szVersion, &szSID, &szSystemCode, &szAuthzToken);
// if (strcmp(szReturnCode, "203030") == 0) { /* 인가토큰 → 서버 검증 */ }
// [?] 샘플에 Init 호출이 안 보임 → 우리 앱은 Init 을 먼저 한 번 부른다(설정 AMTRAY_DLL_INIT 로 끌 수 있음)

// ---- 윈도우 메시지 (AM-Tray → 앱) ----
// 로그인  : WM_COPYDATA(0x004A), wParam = 환경값, lParam = COPYDATASTRUCT* (lpData = 사용자 ID SHA-256)
// 로그아웃: WM_USER(0x0400) + 환경값, wParam = 환경값
// 환경값   |  운영  |  개발
//   본사   | 30001 | 31001   ← 우리 앱은 본사만 (AMTRAY_ENV_CODE)
//   우시   | 30011 | 31011
//   충칭   | 30021 | 31021
