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