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