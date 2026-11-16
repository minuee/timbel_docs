// 클라이언트 샘플 — 시스템 로그인 흐름 (원본: am-tray.java)

public static void main(String[] args) {
    AmInterface am = new AmInterface();
    String ssoKey   = "Dev_CASSO";        // 운영: "Prod_CASSO"
    String sid      = "1234567890";       // [?] 정체 미확인
    String systemID = "1234567890";       // [?] 발급받을 시스템 ID

    String result = am.GetSystemTokenIT(ssoKey, sid, systemID);   // [정리] 원본: getSystemTokenIT (대소문자)

    if (result.length() <= 6) {                                   // [정리] 원본: <- 6
        // ---- 6자리 이하 = 에러코드 ----
        System.out.println("am.GetSystemTokenIT() not login result: " + result);

        if (result.equals("504011")) {
            // 사용자 미로그인 → AM 로그인 창 호출
            boolean bResult = am.ShowSSOLoginUI(sid);             // [정리] 원본: showSSOLoingUI
            System.out.println("am.ShowSSOLoginUI() result: " + bResult);
            if (bResult) {
                return;   // 창을 띄웠다. 로그인이 끝나면 AM-Tray 가 윈도우 메시지로 알려 준다(WindowMessages.md)
            } else {
                // SSO 웹서버 비정상으로 판단 → 자체 로그인으로 전환
            }

        } else if (result.equals("509090") || result.equals("503035")
                || result.equals("503034") || result.equals("500003")) {
            // AM-Tray 미처리 → 자체 로그인 처리

        } else {
            // 그 밖의 에러 → 안내 문구
            String msg = am.GetReturnMessage(result, "ko");
            System.out.println("am.GetReturnMessage() result: " + msg);
        }

    } else {
        // ---- 6자리 초과 = 인가토큰 ----
        // 서버에서 토큰 전달받음 → 우리 서버로 보내 검증(ValidateTokenApi.md)
    }
}

// 에러코드 정리
//   504011                          사용자 미로그인 → ShowSSOLoginUI
//   509090, 503035, 503034, 500003  AM-Tray 미처리 → 자체 로그인
//   그 밖                            GetReturnMessage(code, locale) 로 문구
// [?] 각 코드의 정확한 뜻(509090 = AM-Tray 미실행? 등)은 매뉴얼의 코드 표 확인
