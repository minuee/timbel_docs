// AM Interface — DLL 함수 선언 (Java JNI 쪽)
// DLL 3개 (Windows 64bit):
//   AmInterface-RT-X64.dll      AM Interface 모듈 (실제 기능)            ← PC앱(AmHelper.exe)이 직접 부른다
//   Rathon-CS-Crypt-X64.dll     API 암호화 (위 DLL 이 내부에서 쓰는 것으로 보임)  ← 같은 폴더에만 두면 됨
//   AmInterface-JNI-RT-X64.dll  Java 연동 다리                             ← Java 전용. PC앱은 안 씀

public class AmInterface {                         // [?] 패키지명·클래스명 미확인 (JNI 함수 이름에 들어감)

    static {
        System.loadLibrary("AmInterface-JNI-RT-X64");   // [정리] 원본: system.loadLibrary("AMInterface-JNI-RT-x64")
    }

    // 인가토큰 발급. 성공 = 긴 문자열(토큰), 실패 = 6자리 에러코드
    //   ssoKey   : 개발 "Dev_CASSO" / 운영 "Prod_CASSO"
    //   sid      : [?] 무엇인지 미확인 (샘플값 "1234567890")
    //   systemID : [?] AM 담당자가 발급하는 시스템 ID 로 추정 (샘플값 "1234567890")
    public native String GetSystemTokenIT(String ssoKey, String sid, String systemID);   // [정리] 원본: Strung

    // AM 로그인 창 띄우기. true = 창 띄움, false = SSO 웹서버 비정상
    public native boolean ShowSSOLoginUI(String sid);   // [정리] 원본: ShowSSOLoingUI(char * sid) — Loing 은 오타로 봄 [?] 실제 이름 확인

    // SSO 로그아웃
    public native boolean SSOLogout(String sid);        // [정리] 원본: SSOLogout(char * sid)

    // 에러코드 → 안내 문구 (locale: "ko" 등)
    public native String GetReturnMessage(String code, String locale);  // [정리] 원본: Bool GetReturnMessage(char * code, char * locale)
                                                                        //   샘플은 반환값을 문자열로 씀 → String 으로 봄 [?]
}

// ---- C 형식 메모 ----
// 원본에 char *, Bool 같은 C 형식이 섞여 있었다 → 매뉴얼에 C 함수 선언도 있었던 것으로 보인다.
// PC앱(AmHelper.exe)이 가정한 C 형식 (src/helpers/windows/amtray/AmHelper.cpp "★ 가정"):
//   const char* GetSystemTokenIT(const char* ssoKey, const char* sid, const char* systemID);
//   bool        ShowSSOLoginUI(const char* sid);
//   bool        SSOLogout(const char* sid);
//   const char* GetReturnMessage(const char* code, const char* locale);
// 확인할 것: 문자열이 char* 인지 wchar_t* 인지 / 결과를 반환값으로 주는지, 버퍼(char* out, int size)에 채워 주는지
