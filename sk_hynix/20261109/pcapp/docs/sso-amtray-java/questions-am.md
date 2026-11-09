# AM-Tray 연동 질문서 (AM 담당자용)

> PC 녹음앱(Electron, Windows 64bit)에서 AM-Tray 시스템 로그인을 붙이려 합니다.
> 앱이 Java 가 아니어서 **`AmInterface-RT-X64.dll` 을 C/C++ 에서 직접** 부를 예정입니다(JNI DLL 은 쓰지 않음).
> 받은 Java 샘플 기준으로 아래만 확인 부탁드립니다. 매뉴얼에서 해당 페이지를 알려 주셔도 됩니다.

## A. DLL 함수 형식 (가장 중요)

**Q1. `AmInterface-RT-X64.dll` 의 C 함수 선언(헤더)을 알려 주세요.**
지금 이렇게 가정하고 있습니다. 다른 곳만 고쳐 주시면 됩니다.
```c
const char* GetSystemTokenIT(const char* ssoKey, const char* sid, const char* systemID);
bool        ShowSSOLoginUI(const char* sid);
bool        SSOLogout(const char* sid);
const char* GetReturnMessage(const char* code, const char* locale);
```
- 문자열: `char*`(ANSI/CP949? UTF-8?) 인가요, `wchar_t*` 인가요?
- 결과 문자열: **반환값**으로 주나요, **버퍼에 채워** 주나요(`char* out, int size`)? 반환값이면 메모리 해제가 필요한가요?
- `ShowSSOLoginUI` / `SSOLogout` 반환형: `bool` 인가요 `BOOL(int)` 인가요?
- 함수 이름 정확한 철자 (`ShowSSOLoginUI` / `ShowSSOLoingUI`?)
- 초기화·종료 함수(Init / Release 등)를 먼저 불러야 하나요?
- C/C++ 예제 코드가 있으면 그대로 주시면 가장 좋습니다.

## B. 호출 값

**Q2. `systemID` — 우리 앱용으로 발급받아야 하나요?** 개발/운영 값이 다른가요? 신청 절차는?
(서버 샘플의 `"printChaser"` 는 다른 시스템 값으로 이해했습니다)

**Q3. `sid` 는 무엇인가요?** 샘플은 `"1234567890"` 으로 `systemID` 와 같습니다.
- 시스템 ID 와 같은 값인가요, 세션 ID / 사용자 ID 인가요? 어디서 얻나요?

## C. 윈도우 메시지

**Q4. AM-Tray 는 로그인/로그아웃 알림(WM_COPYDATA, WM_USER+30001)을 어느 창으로 보내나요?**
- 창 제목이나 창 클래스명을 정해 두어야 하나요? 아니면 등록 함수(창 핸들 등록)가 있나요? 브로드캐스트인가요?
- `ShowSSOLoginUI` 를 부른 프로세스의 창으로 보내나요?
- 로그인 알림이 오면 `GetSystemTokenIT` 를 다시 부르면 토큰이 오는 것이 맞나요?
- lpData 의 해시는 무엇의 SHA-256 인가요? (사번? AD 계정?)

## D. 에러코드 / 응답

**Q5. 에러코드 표를 알려 주세요.** 특히 `504011`, `509090`, `503035`, `503034`, `500003` 의 뜻.
(509090 = AM-Tray 미실행? 등) 사용자에게 보여 줄 문구를 정하려 합니다.

**Q6. `GetReturnMessage` 반환형** — 문구 문자열이 맞나요? (자료에 `Bool` 로 적혀 있어 확인)
locale 은 `"ko"`, `"en"` 외에 무엇이 되나요?

**Q7. 서버 검증 API(`/tray/api/ValidateToken`) 실제 응답 예시**를 그대로 받을 수 있을까요?
- 요청 키: `systemID` 인가요 `SystemID` 인가요?
- 응답: `status: 300` 이 맞나요? `attr.RESULTID` 인가요 `attr.Result` 인가요? 성공 값은 `SUCCESS` / `Success`?
- `USERID` 는 사번인가요 AD 계정인가요?
- 우리 백엔드 서버에서 samlam(dev) 으로 방화벽이 열려 있어야 하나요? 신청 절차는?

## E. 기타

**Q8.** `ShowSSOLoginUI` 는 창을 띄우고 **바로 돌아오나요**, 로그인이 끝날 때까지 **기다리나요**?
**Q9.** `ssoKey` 는 `Dev_CASSO` / `Prod_CASSO` 두 개뿐인가요?
**Q10.** DLL 배포: 앱 설치 폴더에 3개를 같이 넣으면 되나요? VC++ 재배포 패키지 등 추가로 필요한 것이 있나요? DLL 버전이 바뀌면 알려 주시나요?
