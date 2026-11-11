// AmHelper.exe — AM-Tray(SSO) DLL 호출 중계
//
// 앱(Electron)이 AM 인터페이스 DLL 을 직접 부르지 않고 이 exe 를 한 번씩 실행한다.
//   - DLL 이 잘못돼 죽어도 앱 본체는 죽지 않는다(이 exe 만 끝난다).
//   - koffi 같은 네이티브 모듈을 망분리 환경에 들여올 필요가 없다.
//
// 사용법 (결과는 stdout 에 JSON 한 줄, 문자열은 UTF-8):
//   AmHelper.exe token   --dll-dir <폴더> --sso-key Dev_CASSO --sid <sid> --system-id <id>
//   AmHelper.exe show-ui --dll-dir <폴더> --sid <sid>
//   AmHelper.exe logout  --dll-dir <폴더> --sid <sid>
//   AmHelper.exe message --dll-dir <폴더> --code 504011 --locale ko
//   AmHelper.exe version
//   공통 옵션: --dll <파일명>(기본 AmInterface-RT-X64.dll) --fn <함수명>(이름이 다를 때) --wide(문자열이 wchar_t* 일 때)
//
// 결과 예:
//   {"ok":true,"cmd":"token","result":"eyJ..."}           ← 토큰 또는 6자리 에러코드(구분은 앱이 한다)
//   {"ok":true,"cmd":"show-ui","result":true}
//   {"ok":false,"cmd":"token","error":"dll_load_failed","winError":126}
//
// 종료 코드: 0 = 호출 성공(결과값과 무관), 1 = 인자/DLL/함수 찾기 실패, 3 = DLL 안에서 죽음
//
// ★ DLL 함수 형식은 아직 "가정" 이다(매뉴얼의 C 선언 / dumpbin 결과로 확정 필요).
//   아래 "★ 가정" 블록만 고치면 된다. x64 에서는 __stdcall / __cdecl 구분이 없어 호출 규약은 신경 쓰지 않아도 된다.

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>

#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

static const char* AMHELPER_VERSION = "0.1.0";

// ============================================
// 문자열 변환 / JSON
// ============================================

static std::string WideToCp(const std::wstring& w, UINT cp) {
    if (w.empty()) return std::string();
    int n = WideCharToMultiByte(cp, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string out(n, '\0');
    WideCharToMultiByte(cp, 0, w.c_str(), (int)w.size(), &out[0], n, nullptr, nullptr);
    return out;
}

static std::wstring CpToWide(const char* s, UINT cp) {
    if (!s || !*s) return std::wstring();
    int n = MultiByteToWideChar(cp, 0, s, -1, nullptr, 0);
    if (n <= 0) return std::wstring();
    std::wstring out(n - 1, L'\0');
    MultiByteToWideChar(cp, 0, s, -1, &out[0], n);
    return out;
}

static std::string Utf8(const std::wstring& w) { return WideToCp(w, CP_UTF8); }

// DLL 이 돌려준 char* 는 한글 Windows 기본 코드페이지(CP949)로 가정해 UTF-8 로 바꾼다.
// UTF-8 로 돌려주는 DLL 이면 --utf8-result 를 준다.
static std::string ResultToUtf8(const char* s, bool resultIsUtf8) {
    if (!s) return std::string();
    if (resultIsUtf8) return std::string(s);
    return Utf8(CpToWide(s, CP_ACP));
}

static std::string JsonEscape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += (char)c;
                }
        }
    }
    return out;
}

static std::string Q(const std::string& s) { return "\"" + JsonEscape(s) + "\""; }

static std::string g_cmd = "";

static void Emit(const std::string& json) {
    fputs(json.c_str(), stdout);
    fputs("\n", stdout);
    fflush(stdout);
}

static int Fail(const std::string& error, const std::string& extra = "") {
    std::string j = "{\"ok\":false,\"cmd\":" + Q(g_cmd) + ",\"error\":" + Q(error);
    if (!extra.empty()) j += "," + extra;
    j += "}";
    Emit(j);
    return 1;
}

// DLL 안에서 접근 위반 등으로 죽으면 여기로 온다. 앱이 원인을 알 수 있게 JSON 한 줄을 남기고 끝낸다.
static LONG WINAPI OnCrash(EXCEPTION_POINTERS* info) {
    char code[16];
    snprintf(code, sizeof(code), "0x%08lX",
             info && info->ExceptionRecord ? (unsigned long)info->ExceptionRecord->ExceptionCode : 0UL);
    Emit("{\"ok\":false,\"cmd\":" + Q(g_cmd) + ",\"error\":\"dll_crashed\",\"exceptionCode\":" + Q(code) + "}");
    ExitProcess(3);
    return EXCEPTION_EXECUTE_HANDLER;
}

// ============================================
// 인자
// ============================================

struct Args {
    std::wstring cmd;
    std::map<std::wstring, std::wstring> opts;   // --key value
    bool wide = false;
    bool resultUtf8 = false;

    std::wstring Get(const wchar_t* key, const wchar_t* def = L"") const {
        auto it = opts.find(key);
        return it == opts.end() ? std::wstring(def) : it->second;
    }
    bool Has(const wchar_t* key) const { return opts.find(key) != opts.end(); }
};

static Args ParseArgs() {
    Args a;
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return a;
    if (argc > 1) a.cmd = argv[1];
    for (int i = 2; i < argc; ++i) {
        std::wstring k = argv[i];
        if (k == L"--wide") { a.wide = true; continue; }
        if (k == L"--utf8-result") { a.resultUtf8 = true; continue; }
        if (k.rfind(L"--", 0) == 0 && i + 1 < argc) {
            a.opts[k.substr(2)] = argv[++i];
        }
    }
    LocalFree(argv);
    return a;
}

// ============================================
// DLL 로드 / 함수 찾기
// ============================================

static HMODULE g_dll = nullptr;

static int LoadAmDll(const Args& a) {
    std::wstring dir = a.Get(L"dll-dir");
    std::wstring name = a.Get(L"dll", L"AmInterface-RT-X64.dll");
    if (dir.empty()) {
        // 기본: 이 exe 와 같은 폴더(DLL 3개를 AmHelper.exe 옆에 둔다)
        wchar_t self[MAX_PATH] = {0};
        GetModuleFileNameW(nullptr, self, MAX_PATH);
        dir = self;
        size_t pos = dir.find_last_of(L"\\/");
        dir = pos == std::wstring::npos ? L"." : dir.substr(0, pos);
    }
    // AmInterface DLL 이 같은 폴더의 Rathon-CS-Crypt-X64.dll 을 찾을 수 있게 검색 경로에 넣는다.
    SetDllDirectoryW(dir.c_str());
    std::wstring full = dir + L"\\" + name;
    if (GetFileAttributesW(full.c_str()) == INVALID_FILE_ATTRIBUTES) {
        return Fail("dll_not_found", "\"path\":" + Q(Utf8(full)));
    }
    g_dll = LoadLibraryExW(full.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!g_dll) {
        // 126 = 의존 DLL(Rathon-CS-Crypt-X64.dll, VC 런타임 등) 없음, 193 = 32/64비트 불일치
        return Fail("dll_load_failed", "\"path\":" + Q(Utf8(full)) + ",\"winError\":" + std::to_string(GetLastError()));
    }
    return 0;
}

// --fn 으로 이름을 주면 그것만, 아니면 후보를 차례로 찾는다(매뉴얼 이름의 대소문자·오타 차이 대비).
static FARPROC FindFn(const Args& a, std::initializer_list<const char*> candidates, std::string& used) {
    std::wstring forced = a.Get(L"fn");
    if (!forced.empty()) {
        used = WideToCp(forced, CP_ACP);
        return GetProcAddress(g_dll, used.c_str());
    }
    for (const char* name : candidates) {
        FARPROC p = GetProcAddress(g_dll, name);
        if (p) { used = name; return p; }
    }
    used = "";
    return nullptr;
}

static int FnNotFound(std::initializer_list<const char*> candidates) {
    std::string list;
    for (const char* n : candidates) {
        if (!list.empty()) list += ",";
        list += Q(n);
    }
    return Fail("function_not_found", "\"tried\":[" + list + "]");
}

// ============================================
// ★ 가정 — DLL 함수 형식 (확정되면 여기만 고친다)
//   문자열: 기본 char*(ANSI). --wide 면 wchar_t*.
//   반환:   GetSystemTokenIT / GetReturnMessage → 문자열 포인터(DLL 이 가진 메모리, 해제하지 않음)
//           ShowSSOLoginUI / SSOLogout           → bool 또는 BOOL. 둘 다 맞도록 하위 1바이트만 본다.
//   ※ 결과를 "버퍼에 채워 주는" 형식(char* out, int size)이면 이 블록을 그 형식으로 바꿔야 한다.
// ============================================

typedef const char*    (*FnTokenA)(const char* ssoKey, const char* sid, const char* systemId);
typedef const wchar_t* (*FnTokenW)(const wchar_t* ssoKey, const wchar_t* sid, const wchar_t* systemId);
typedef int            (*FnSidA)(const char* sid);
typedef int            (*FnSidW)(const wchar_t* sid);
typedef const char*    (*FnMsgA)(const char* code, const char* locale);
typedef const wchar_t* (*FnMsgW)(const wchar_t* code, const wchar_t* locale);

#define TOKEN_FNS   { "GetSystemTokenIT", "getSystemTokenIT", "GetSystemToken" }
#define SHOWUI_FNS  { "ShowSSOLoginUI", "ShowSSOLoingUI", "showSSOLoginUI", "ShowSsoLoginUI" }
#define LOGOUT_FNS  { "SSOLogout", "SsoLogout", "ssoLogout" }
#define MESSAGE_FNS { "GetReturnMessage", "getReturnMessage" }

static std::string StrResult(const char* a, const wchar_t* w, const Args& args) {
    if (args.wide) return w ? Utf8(w) : std::string();
    return ResultToUtf8(a, args.resultUtf8);
}

static int CmdToken(const Args& a) {
    std::wstring ssoKey = a.Get(L"sso-key"), sid = a.Get(L"sid"), systemId = a.Get(L"system-id");
    if (ssoKey.empty() || systemId.empty()) return Fail("missing_args", "\"need\":[\"sso-key\",\"system-id\"]");
    if (int rc = LoadAmDll(a)) return rc;
    std::string used;
    FARPROC p = FindFn(a, TOKEN_FNS, used);
    if (!p) return FnNotFound(TOKEN_FNS);

    std::string result;
    bool isNull = false;
    if (a.wide) {
        const wchar_t* r = ((FnTokenW)p)(ssoKey.c_str(), sid.c_str(), systemId.c_str());
        isNull = !r;
        result = StrResult(nullptr, r, a);
    } else {
        std::string k = WideToCp(ssoKey, CP_ACP), s = WideToCp(sid, CP_ACP), i = WideToCp(systemId, CP_ACP);
        const char* r = ((FnTokenA)p)(k.c_str(), s.c_str(), i.c_str());
        isNull = !r;
        result = StrResult(r, nullptr, a);
    }
    if (isNull) return Fail("null_result", "\"fn\":" + Q(used));
    Emit("{\"ok\":true,\"cmd\":\"token\",\"fn\":" + Q(used) + ",\"result\":" + Q(result) + "}");
    return 0;
}

static int CmdSidBool(const Args& a, bool isShowUi) {
    std::wstring sid = a.Get(L"sid");
    if (int rc = LoadAmDll(a)) return rc;
    std::string used;
    FARPROC p = isShowUi ? FindFn(a, SHOWUI_FNS, used) : FindFn(a, LOGOUT_FNS, used);
    if (!p) return isShowUi ? FnNotFound(SHOWUI_FNS) : FnNotFound(LOGOUT_FNS);

    int raw;
    if (a.wide) {
        raw = ((FnSidW)p)(sid.c_str());
    } else {
        std::string s = WideToCp(sid, CP_ACP);
        raw = ((FnSidA)p)(s.c_str());
    }
    bool ok = (raw & 0xFF) != 0;
    Emit("{\"ok\":true,\"cmd\":" + Q(g_cmd) + ",\"fn\":" + Q(used) + ",\"result\":" + (ok ? "true" : "false") +
         ",\"raw\":" + std::to_string(raw) + "}");
    return 0;
}

static int CmdMessage(const Args& a) {
    std::wstring code = a.Get(L"code"), locale = a.Get(L"locale", L"ko");
    if (code.empty()) return Fail("missing_args", "\"need\":[\"code\"]");
    if (int rc = LoadAmDll(a)) return rc;
    std::string used;
    FARPROC p = FindFn(a, MESSAGE_FNS, used);
    if (!p) return FnNotFound(MESSAGE_FNS);

    std::string result;
    bool isNull = false;
    if (a.wide) {
        const wchar_t* r = ((FnMsgW)p)(code.c_str(), locale.c_str());
        isNull = !r;
        result = StrResult(nullptr, r, a);
    } else {
        std::string c = WideToCp(code, CP_ACP), l = WideToCp(locale, CP_ACP);
        const char* r = ((FnMsgA)p)(c.c_str(), l.c_str());
        isNull = !r;
        result = StrResult(r, nullptr, a);
    }
    if (isNull) return Fail("null_result", "\"fn\":" + Q(used));
    Emit("{\"ok\":true,\"cmd\":\"message\",\"fn\":" + Q(used) + ",\"result\":" + Q(result) + "}");
    return 0;
}

int main() {
    SetUnhandledExceptionFilter(OnCrash);
    // 에러 팝업(DLL 없음 등) 대신 실패 코드로 받는다 — 숨김 실행이라 팝업이 뜨면 아무도 못 누른다.
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);

    Args a = ParseArgs();
    g_cmd = Utf8(a.cmd);
    if (a.cmd == L"version") {
        Emit(std::string("{\"ok\":true,\"cmd\":\"version\",\"result\":") + Q(AMHELPER_VERSION) + "}");
        return 0;
    }
    if (a.cmd == L"token") return CmdToken(a);
    if (a.cmd == L"show-ui") return CmdSidBool(a, true);
    if (a.cmd == L"logout") return CmdSidBool(a, false);
    if (a.cmd == L"message") return CmdMessage(a);
    return Fail("unknown_command");
}
