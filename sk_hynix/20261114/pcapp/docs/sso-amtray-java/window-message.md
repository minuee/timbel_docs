Windows Message Sample
1. Loing Message 예시
    Window Message : WM-COPYDATA(0x004a)
    wParam : 로그인환경 식별값 ( 운영 : 30001, 개발 : 31001)
    IParam : 사용자 Hahs ID(COPYDATASTRUCT타입)
    COPYDATASTRUCT { 
        dwdata : 미사용
        cbData : lpData의 크기(byte)
        lpData : 사용자 ID해쉬값(SHA-256해쉬)
    }

2.Logout Message 예사
    Window Message : WM-USER(0x0400) + 연동환경식별값 ( 운영 : 30001, 개발 : 31001)
     wParam : 로그아웃환경 식별값 ( 운영 : 30001, 개발 : 31001)
     IParam :  미사용


서버단 인가토큰 검증 aPI
1. url
    개발 : https://samlamdev.skhynix.com/tray/api/ValidateToken
    운영 : https://samlam.skhynix.com/tray/api/ValidateToken
2. method : POST
3. 전달방식 : Json
4. 입력값 : systemID : 시스템아이디, authzToken : 인가토큰
5. 반환갑 : status : 300 attr { Result : "Success", USERID : 인증사용자 ID}

API-Tray API 설명
1. API의 Bool return값은 AM-Tray Service와의 통신 성공/실패 여부를 의미
2. API 동작 결과는 응답코드(변수명: lpReturnCode)도 확인되어야 한다
3. 연동대상 시스템의 개발언에 따라 cpp, C#, Java dll을 제공
4. dll은 연동대상 시스템에 포함하여 사용해야 한다
5. SetSystemToken API에서 SSOKey는 연동대상 SSO서버 설정값에 대한 정보이며 API명세서에 표기한 값을 고정으로 사용한다
6. SetSystemToken API에서 sid는 AM-Tray에서 시스템 식별을 위해 필요한 값으로 연동시스템의 세션명을 관리하기 이해 AM-Tray내부에서 사용하기 위한 값이다
   ( 시스템에서 임의로 지정해서 사용가능 ex) printChaser(운영), printChaserDev(개발))
7. getSystemToken API에서 systemID는 SSO에서 연동시스템인가, 검증 수행을 위해 필요한 값이다(시스템의 접근 통제 적용을 위해 myAccess와 함의한 ACL(시스템권한명)값 사용 필요)
   ㄴ myAccess와 협의전 연동 테스트 시 AM-Tray관리자 페이지에서 시스템인가 예외처리설정을 통해서 미리 연동 테스트진행가능)

AM-Tray DLL API 명세
- GetSystemTokenIT() API 응답코드
응답코 : 내용 : 대응처리(이런 순으로 정리
203030 : 인가토큰 발성공  : 연동Client에서 Server로 인가토큰을 전달하여 SSO Server로 토큰 검증 요청 > 서버 to 서버 검증수행
504011 : AM-Tray미로그인(ID/PW 인증필요) : 1. 연동 client자체 로그인(AD인증)전환(사용자 미 로그인 상태) 2. 로그인페이지 showSSOLoginAPI호출(사용자 미 로그인 상태), 3.시스템 대기 상태)
503031 : 시스템 접근 불가 ( 사용자 신뢰 점수 미달 ) : 응답코드에 따른 메시지 팝업 노출
503032 : 시스템 접근 불가 ( 접근 권한 없음 ) : 응답코드에 따른 메시지 팝업 노출
503033 : 시스템 접근 불가 ( 장기 미사용으로 인한 권한 회수 ) : 응답코드에 따른 메시지 팝업 노출
503034 : 유효하지 않은 토큰 ( 토큰 만료 ) : 응답코드에 따른 메시지 팝업 노출
503036 : 인증토큰 ID검증실패(토큰 탈취, ID변경등) : 응답코드에 따른 메시지 팝업 노출
503035 : 토큰 발급 aPI통신실패 : 응답코드에 따른 메시지 팝업 노출 
509090 또는 ""공백 : AM-Tray Service 통신실패, 시스템 정책에 따라 선택 : 1.연동 client 자체로그인(AD인증) 전환, 2.AM-Tray 설치 페이지이동
500001 : DLL라이브러리 로드 실패 : 연동 client 자체로그인(AD인증) 전환
500003 : DLL API 통신 실패 : 연동 client 자체로그인(AD인증) 전환

오류코드별 안내 메시지
503031 : 접속환경 Risk평가 결과 허가된 접근 범위를 초과하여 접속이 차단되었습니다.
503032 : 시스템 접근 권한이 없습니다.
503033 : 시스템 장기 미사용으로 인하여 권한이 회수되었습니다.
509090 : AM-Tray가 설치되지 안았습니다.
504011 : 통합인증이 필요합니다(미 로그인 상태)
503034 : 사용자 인증 정보가 만료되어 AM-Tray로그아웃 후 재로그인이 필요합니다.
503035 : 인가토큰 발급에 실패하였습니다. 
503036 : 인증토큰 ID검증에 실패하였습니다. 

Interface DLL은 연동대상 클라이언트에 포함하여 배포하라?
.Net RTSessionClientCShaprDll_RT.dll파일이 있는데 .net파일용인가 왜이파일을 담당자가 줬는지 모르겠네..

API-Tray DLL API 설명
1) AM-Tray 상세 초기화 - Init() API
  함수원형 
  BOOL Init( char( * lpReturnCode)[8]
    ,char(* strSSOKey)[32]
    ,char(* strTraySID)[256]
    ,char(* strVersion)[32]
  )
4가지 인자 순서대로 6자리응답코드(성공: 201010) 연동시스템SSOKey,연동시스템 ID-지급 발급신청중, 연동AM-Tray버전

2) 로그인 UI요청 ShowSSOLoginUI() API
  함수원형
  BOOL ShowSSOLoginUI( 
    char (* lpReturnCode)[8])
    ,char * strTraySID
  )
  순서대로 6자리 응답코드 , 연동시스템ID

3) 사용자 상태확인 - CheckLoginUserIT() API
  함수원형
  BOOL CheckLoginUserIT(
    char(*lpReturnCode)[8]
    ,char strTraySID
    ,char strUserID
  )
  순서대로 6자리 응답코드 , 연동시스템ID, 확인요청 사용자 ID

4) AM-Tray API응답코드에 따르 메시지들 
  함수원형
  BOOL GetReturnMessage(
    char * strReturnCode
    ,char * strLocale
    ,char(*lpMessage)[4096]
  )
   순서대로 6자리 코드 , 언어, 메시지내용

5) 사용자상태확인 IsLoginIT() 함수
  함수원형 
  BOOL IsLoginIT(
    char(*lpReturnCode)[8]
    ,char strTraySID
  )
  서대로 6자리 응답코드 , 연동시스템ID

6) 사용자로그아웃 SSOLogout()
  함수원형
  BOOL SSOLogout(
    char(*lpreturnCode)[8]
    ,char * strTraySID
    ,char * strUserID
  )

7) AM-Tray가 가진 SMSESSION정보행동 GetSmSessionToken() 
  함수원형
  BOOL GetSmSessionToken(
    char(*lpSystemToken)[4096]
    ,char(* strTraySID)[32]
    ,char(* strSSOKey)[32]
  )
  ㄴ 가져온 SMSession을 Cookie헤더값에 사용 Ex) Cookie:SMSESSION=uxndjlfkdjfdjldjflddfdfd

일단 문서는 여기까지만 함수원형에 대해 나왔어 
샘플코드는 기존 xx.java소스인데 몇개만 적어볼께 너무 손가락이 아파서 ㅠ

sample 1)
    HMODULE hModule = LoadLibraryA("AmInterface_RT") //또는 AmInterface_RT_X64, AmInterface_RT.dll인지 그냥 AmInterface_RT이건지 헷갈리게 적어왓네 ㅠ
    GETSYSTEMTOKEN API_GetSystemToken = ( GETSYSTEMTOKEN ) GetProcAddress(hModule,"GetSystenToken");
    ShowSSOLoginUI API_ShowSSOLoginUI = ( SHOWSSOLOGINUI ) GetProcAddress(hModule,"ShowSSOLoginUI");
    char szRetunCode[8] = {0,};
    char szSSOKey[32] = {0,};
    char szVersion[32] = {0,};
    char szSystemCode[32] = {0,};
    char szAuthzToken[4096] = {0,};
    bool bResult = false;
    strcpy(szSSOKeym, "받은값~~~~~");
    strcpy(szSID,"aimm") // 예시
    strcpy(szSystemCode,"aimm") //예시
    bResult = API_GetSystemToken(szReturnCode, szSSOKey,szVersion,szSID,szSystemCode,szAuthzToken)
    if(strcmp(szReturnCode,"203030) == 0) {
        //STEP3-1 토큰발급 성공이후 처리 
    }
   이후는 기존 자바소스랑 비슷해 정 필요하면 내가 다시 다 적어올께, 아직 더 잇긴한데 너무 길어서 ㅠㅠ

다음은 WindowMessage 샘플
1) Login Message : 연동환경 식별값(시스템과 연동된 Am-Tray에 보낸 메시지인지 확인을 위함 
  ㄴ 전에 공유한 문서와 동일 다만 추가된게 사업장별로 구분을 해야해, 그것도 운영과 개발, 사업장 3곳 총 6개인데 일단 공유는 다할께 아마도 본사만 적용시킬거 같긴한데 이건 너와 고민읗 해보자 
  WParma  
  구분 | 운영   | 개발
  본사 | 30000 | 31001
  우시 | 30011 | 31011
  충칭 | 30021 | 31021
  
함수원형
BEGIN_MESSAGE_MAP(CWindowsFormsApp2Dlg, CDialogEx)
    OW_WM_PAINT()
    ON_WM_QUERYDRAGICON()
    ON_MESSAGE(WM_COPYDATA,ONCopyData)
END_MESSAGE_MAP()

afx_msg LRESULT CWindowsFormsApp2Dlg::OnCopyData(WPARAM wParam, LPARAM lparam){
    int sendKey = wParam;
    char* receivedData;
    if(sendKey == 31001 ) {  // 이 응답코드가 위의 사업장별 
        COPYDATASTRUCT *pCopyData = reinterpret_cast<COPYDATASTRUCT*>(lParam);
        (string LginHashID(static_cast<char*>(pCopyData->lpData),pCopyData->cbData))
    }
    return true
}
2. Logout Message
함수원형
BEGIN_MESSAGE_MAP(CWindowsFormsApp2Dlg,CDialogEx)
    OW_WM_PAINT()
    ON_WM_QUERYDRAGICON()
    ON_MESSAGE(WM_USER + 31001,,ONPostData)
END_MESSAGE_MAP()

afx_msg LRESULT CWindwosFormsApp2Dlog::OnPostData(WPARAM wParam, LPARAM lParam) {
    int sendKey = wParma;
    char* recivedData;
    if(sendKey == 31001){
        //시스템정책에 맞게 로그아웃처리 또는 로그인 유지 등 우리 앱은 녹음중에는 얼로드중에는 로그아웃을 하면 안된다 
    }
    return 0;
}

서버단 인가토큰 검증 aPI
1. url도 3군데 별로 달라 기존과도 주소도 달라졌어
우선 본사
    개발 : https://samlamdev.skhynix.com/tray/api/ValidateToken
    운영 : https://csam.skhynix.com/tray/api/ValidateToken
우시
    개발 : https://csamlamdev.skhynix.com.cn/tray/api/ValidateToken
    운영 : https://csam.skhynix.com.cn/tray/api/ValidateToken
충칭
    개발 : https://csamlamdev.skhynix-cq.com.cn/tray/api/ValidateToken
    운영 : https://csam.skhynix-cq.com.cn/tray/api/ValidateToken
그외 정보는 전과 동일한듯해 