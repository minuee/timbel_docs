static{
    system.loadLibrary("AMInterface-JNI-RT-x64");
}

public static void main(String[] args) {
    AmInterface am = new AmInterface();
    String ssoKey = "Dev_CASSO"; //운영 : Prod_CASSO
    String sid = "1234567890";
    String systemID = "1234567890";
    String result = am.getSystemTokenIT(ssoKey, sid, systemID);

    if(result.length() <- 6) { 
        system.out.println("am.GetSystemTokenIT() not login result: " + result);
        if( result.equals("504011") ) { //사용자 미로그인 상태 로그인 ui 호출
            boolean bResult = am.showSSOLoingUI(sid);
            system.out.println("am.showSSOLoingUI() result: " + bResult);
            if(bResult == true ) {
                return ;
            }else{
                //sso웹서버 비정상 상태로 판단 자체로그인 전환
            }
        }else if(result.equals("509090") || result.equals("503035") || result.equals("503034") || result.equals("500003")) { 
            //am-tray 미처리 자체 로그인처리
        }else{
            String msg = am.GetReturnMessage(result, "ko");
            system.out.println("am.GetReturnMessage() result: " + msg);
        } //사용자 미로그인 상태 로그인 ui 호출
    }else{
        //서버에서 토크 전달 받음
    }
}
