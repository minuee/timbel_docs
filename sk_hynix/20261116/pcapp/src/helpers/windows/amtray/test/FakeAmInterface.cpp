// 테스트용 가짜 AmInterface_RT_X64.dll — 진짜 DLL 없이 koffi 시험·앱 흐름을 확인할 때만 쓴다. 배포 금지.
// 함수 모양·응답코드는 AM C++ 매뉴얼 기준(2026-11-14 모양, 11-16 응답코드 표, docs/sso-amtray-java/clean/AmInterface.h).
// 진짜처럼 ShowSSOLoginUI·IsLoginIT·CheckLoginUserIT 는 Init 전에는 501010(연결정보 없음)을 돌려준다.
// 동작은 환경변수 FAKE_AM 으로 바꾼다:
//   (없음)        → Init 201010(두 번째부터 201011), GetSystemToken 203030 + 가짜 토큰, IsLoginIT 206030
//   notlogin      → GetSystemToken·IsLoginIT 504011(미로그인), CheckLoginUserIT 504011
//   unavailable   → BOOL=false (통신 실패 = 명세의 "공백")
//   error         → GetSystemToken 503032(접근 권한 없음)
//   ssofail       → GetSystemToken 503035(토큰 발급 API 통신 실패)
//   initfail      → Init 이 501010(초기화 실패)
//   uifail        → 미로그인 + ShowSSOLoginUI 502051(SSO 로그인 페이지 통신 실패)
//   uiblock       → 미로그인 + ShowSSOLoginUI 502052(SSO 로그인 불가)
//   uialready     → 미로그인 + ShowSSOLoginUI 506021(이미 로그인 상태)
//   crash         → 접근 위반으로 죽음(작업 프로세스만 죽는지 확인용)
// CheckLoginUserIT: 사번 X0000000 이면 206040(같은 사람), 빈 값이면 506041, 그 밖은 506040(다른 사람)
// Mac 시험용으로도 빌드한다(clang -shared → .dylib). 그래서 windows.h 는 Windows 일 때만.
#ifdef _WIN32
#include <windows.h>
#define EXPORT extern "C" __declspec(dllexport)
#else
#include <cstdlib>
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define EXPORT extern "C" __attribute__((visibility("default")))
#endif
#include <cstring>
#include <cstdio>

static const char* Mode() {
#ifdef _WIN32
    static char env[64];
    DWORD n = GetEnvironmentVariableA("FAKE_AM", env, sizeof(env));
    return n ? env : "";
#else
    const char* v = getenv("FAKE_AM");
    return v ? v : "";
#endif
}
static bool Is(const char* m) { return !strcmp(Mode(), m); }
static void Put(char* dst, size_t size, const char* src) { strncpy(dst, src, size - 1); dst[size - 1] = 0; }

static bool g_init = false;
static bool NotLogin() { return Is("notlogin") || Is("uifail") || Is("uiblock") || Is("uialready"); }

EXPORT BOOL Init(char (*lpReturnCode)[8], char (*strSSOKey)[32], char (*strTraySID)[256], char (*strVersion)[32]) {
    (void)strTraySID;
    if (Is("crash")) { volatile int* p = nullptr; *p = 1; }
    if (Is("unavailable")) return FALSE;
    Put(*strVersion, 32, "9.9.9-fake");
    if (Is("initfail") || !(*strSSOKey)[0]) { Put(*lpReturnCode, 8, "501010"); return TRUE; }
    Put(*lpReturnCode, 8, g_init ? "201011" : "201010");
    g_init = true;
    return TRUE;
}

EXPORT BOOL GetSystemToken(char (*lpReturnCode)[8], char (*strSSOKey)[32], char (*strVersion)[64],
                           char (*strTraySID)[32], char (*strSystemCode)[32], char (*lpAuthzToken)[4096]) {
    (void)strSSOKey; (void)strTraySID;
    if (Is("crash")) { volatile int* p = nullptr; *p = 1; }
    if (Is("unavailable")) return FALSE;
    // 매뉴얼: version 은 출력 [64] — 64바이트를 꽉 채워 써서 버퍼가 작으면 드러나게 한다
    memset(*strVersion, 'v', 63); (*strVersion)[63] = 0;
    if (NotLogin()) { Put(*lpReturnCode, 8, "504011"); return TRUE; }
    if (Is("error")) { Put(*lpReturnCode, 8, "503032"); return TRUE; }
    if (Is("ssofail")) { Put(*lpReturnCode, 8, "503035"); return TRUE; }
    char tok[128];
    snprintf(tok, sizeof(tok), "FAKE.AUTHZ.TOKEN.%s.0123456789abcdef", *strSystemCode);
    Put(*lpAuthzToken, 4096, tok);
    Put(*lpReturnCode, 8, "203030");
    return TRUE;
}

EXPORT BOOL ShowSSOLoginUI(char (*lpReturnCode)[8], char* strTraySID) {
    (void)strTraySID;
    if (Is("unavailable")) return FALSE;
    if (!g_init) { Put(*lpReturnCode, 8, "501010"); return TRUE; }
    Put(*lpReturnCode, 8, Is("uifail") ? "502051" : Is("uiblock") ? "502052" : Is("uialready") ? "506021" : "203012");
    return TRUE;
}

EXPORT BOOL IsLoginIT(char (*lpReturnCode)[8], char* strTraySID) {
    (void)strTraySID;
    if (Is("unavailable")) return FALSE;
    if (!g_init) { Put(*lpReturnCode, 8, "501010"); return TRUE; }
    Put(*lpReturnCode, 8, NotLogin() ? "504011" : "206030");
    return TRUE;
}

EXPORT BOOL CheckLoginUserIT(char (*lpReturnCode)[8], char* strTraySID, char* strUserID) {
    (void)strTraySID;
    if (Is("unavailable")) return FALSE;
    if (!g_init) { Put(*lpReturnCode, 8, "501010"); return TRUE; }
    if (NotLogin()) { Put(*lpReturnCode, 8, "504011"); return TRUE; }
    Put(*lpReturnCode, 8, !strUserID[0] ? "506041" : !strcmp(strUserID, "X0000000") ? "206040" : "506040");
    return TRUE;
}

// SMSESSION 흉내 — 응답코드 칸이 없다. true 면 값, false 면 같은 칸에 코드(504011/509090)
EXPORT BOOL GetSmSessionToken(char (*lpSystemToken)[4096], char (*strTraySID)[32], char (*strSSOKey)[32]) {
    (void)strTraySID; (void)strSSOKey;
    if (Is("unavailable")) { Put(*lpSystemToken, 4096, "509090"); return FALSE; }
    if (NotLogin()) { Put(*lpSystemToken, 4096, "504011"); return FALSE; }
    Put(*lpSystemToken, 4096, "FAKE+SmSession/abc=XYZ%2Fqq");
    return TRUE;
}

// 한글 Windows 기본 코드페이지(CP949) 문자열을 돌려주는 상황을 흉내 낸다("가짜 메시지")
EXPORT BOOL GetReturnMessage(char* strReturnCode, char* strLocale, char (*lpMessage)[4096]) {
    (void)strReturnCode;
    if (strLocale && !strcmp(strLocale, "en")) Put(*lpMessage, 4096, "Fake message");
    else Put(*lpMessage, 4096, "\xB0\xA1\xC2\xA5 \xB8\xDE\xBD\xC3\xC1\xF6");
    return TRUE;
}

#ifdef _WIN32
BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) { return TRUE; }
#endif
