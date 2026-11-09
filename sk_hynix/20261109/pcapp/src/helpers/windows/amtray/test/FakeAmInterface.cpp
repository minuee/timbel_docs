// 테스트용 가짜 AmInterface-RT-X64.dll — 진짜 DLL 없이 AmHelper.exe / 앱 흐름을 확인할 때만 쓴다. 배포 금지.
// 동작은 환경변수 FAKE_AM 으로 바꾼다:
//   (없음)        → GetSystemTokenIT 가 가짜 토큰을 돌려줌
//   notlogin      → "504011"(미로그인)
//   unavailable   → "509090"(AM-Tray 미처리)
//   error         → "500001"(그 밖의 에러)
//   crash         → 접근 위반으로 죽음(AmHelper 의 dll_crashed 확인용)
#include <windows.h>
#include <cstring>

static char g_env[64];
static const char* Mode() {
    DWORD n = GetEnvironmentVariableA("FAKE_AM", g_env, sizeof(g_env));
    return n ? g_env : "";
}

extern "C" __declspec(dllexport) const char* GetSystemTokenIT(const char* ssoKey, const char* sid, const char* systemId) {
    (void)ssoKey; (void)sid; (void)systemId;
    const char* m = Mode();
    if (!strcmp(m, "notlogin")) return "504011";
    if (!strcmp(m, "unavailable")) return "509090";
    if (!strcmp(m, "error")) return "500001";
    if (!strcmp(m, "crash")) { volatile int* p = nullptr; *p = 1; }
    return "FAKE.AUTHZ.TOKEN.0123456789abcdef";
}

extern "C" __declspec(dllexport) bool ShowSSOLoginUI(const char* sid) { (void)sid; return true; }
extern "C" __declspec(dllexport) bool SSOLogout(const char* sid) { (void)sid; return true; }

// 한글 Windows 기본 코드페이지(CP949) 문자열을 돌려주는 상황을 흉내 낸다("가짜 메시지")
extern "C" __declspec(dllexport) const char* GetReturnMessage(const char* code, const char* locale) {
    (void)code;
    if (locale && !strcmp(locale, "en")) return "Fake message";
    return "\xB0\xA1\xC2\xA5 \xB8\xDE\xBD\xC3\xC1\xF6";
}

BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) { return TRUE; }
