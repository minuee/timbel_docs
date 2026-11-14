// 테스트용 가짜 AmInterface_RT_X64.dll — 진짜 DLL 없이 koffi 시험·앱 흐름을 확인할 때만 쓴다. 배포 금지.
// 함수 모양은 AM C++ 매뉴얼 기준(2026-11-14, docs/sso-amtray-java/clean/AmInterface.h).
// 동작은 환경변수 FAKE_AM 으로 바꾼다:
//   (없음)        → Init 201010, GetSystemToken 203030 + 가짜 토큰
//   notlogin      → GetSystemToken 504011(미로그인)
//   unavailable   → BOOL=false (통신 실패 = 명세의 "공백")
//   error         → 503032(접근 권한 없음)
//   initfail      → Init 이 500003
//   crash         → 접근 위반으로 죽음(작업 프로세스만 죽는지 확인용)
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

EXPORT BOOL Init(char (*lpReturnCode)[8], char (*strSSOKey)[32], char (*strTraySID)[256], char (*strVersion)[32]) {
    (void)strTraySID;
    if (Is("crash")) { volatile int* p = nullptr; *p = 1; }
    if (Is("unavailable")) return FALSE;
    Put(*strVersion, 32, "9.9.9-fake");
    Put(*lpReturnCode, 8, Is("initfail") ? "500003" : ((*strSSOKey)[0] ? "201010" : "500001"));
    return TRUE;
}

EXPORT BOOL GetSystemToken(char (*lpReturnCode)[8], char (*strSSOKey)[32], char (*strVersion)[32],
                           char (*strTraySID)[256], char (*strSystemCode)[32], char (*lpAuthzToken)[4096]) {
    (void)strSSOKey; (void)strVersion; (void)strTraySID;
    if (Is("crash")) { volatile int* p = nullptr; *p = 1; }
    if (Is("unavailable")) return FALSE;
    if (Is("notlogin")) { Put(*lpReturnCode, 8, "504011"); return TRUE; }
    if (Is("error")) { Put(*lpReturnCode, 8, "503032"); return TRUE; }
    char tok[128];
    snprintf(tok, sizeof(tok), "FAKE.AUTHZ.TOKEN.%s.0123456789abcdef", *strSystemCode);
    Put(*lpAuthzToken, 4096, tok);
    Put(*lpReturnCode, 8, "203030");
    return TRUE;
}

EXPORT BOOL ShowSSOLoginUI(char (*lpReturnCode)[8], char* strTraySID) {
    (void)strTraySID;
    Put(*lpReturnCode, 8, "000000");
    return TRUE;
}

EXPORT BOOL IsLoginIT(char (*lpReturnCode)[8], char* strTraySID) {
    (void)strTraySID;
    Put(*lpReturnCode, 8, Is("notlogin") ? "504011" : "200000");
    return TRUE;
}

EXPORT BOOL CheckLoginUserIT(char (*lpReturnCode)[8], char* strTraySID, char* strUserID) {
    (void)strTraySID;
    Put(*lpReturnCode, 8, !strcmp(strUserID, "X0000000") ? "200000" : "400000");
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
